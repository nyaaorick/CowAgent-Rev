# encoding:utf-8

"""Unit tests for the per-contact / per-room switch store.

The store decides who may reach the agent, so every test here is really a
question about the gate: what happens to an unknown id, to a half-written
file, to a list someone hand-edited into nonsense. The answer must always be
"narrow the gate", never "open it".
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channel.wcf.contact_state import ContactState


@pytest.fixture
def state(tmp_path):
    """A store backed by a throwaway file, never the operator's real one."""
    return ContactState(state_path=str(tmp_path / "contacts_state.json"))


# --------------------------------------------------------------------- defaults
def test_unknown_contact_has_no_record():
    """An id nobody has toggled is not recorded, so the caller falls back."""
    store = ContactState(state_path=os.devnull + "-missing")
    assert store.get("wxid_nobody") is None


def test_unknown_contact_is_not_allowed(state):
    """No record means no permission — the store never invents an allow."""
    assert state.is_allowed("wxid_nobody") is False


def test_recorded_contact_defaults_to_answering(state):
    """Whitelisting someone means the agent answers them; that is the point."""
    state.set_allowed("wxid_alice", True)
    assert state.is_allowed("wxid_alice") is True
    assert state.auto_answer("wxid_alice") is True


def test_at_mention_is_required_until_switched_off(state):
    """Existing behaviour: a group message without an @ is ignored."""
    state.set_allowed("room1@chatroom", True)
    assert state.at_free("room1@chatroom") is False


# ------------------------------------------------------------------ round trips
def test_toggle_survives_a_reload(state, tmp_path):
    state.set_allowed("wxid_alice", True)
    state.set_auto_answer("wxid_alice", False)
    state.set_at_free("room1@chatroom", True)

    reloaded = ContactState(state_path=str(tmp_path / "contacts_state.json"))
    assert reloaded.is_allowed("wxid_alice") is True
    assert reloaded.auto_answer("wxid_alice") is False
    assert reloaded.at_free("room1@chatroom") is True


def test_turning_a_switch_off_persists_too(state, tmp_path):
    """A removed permission must not come back after a restart."""
    state.set_allowed("wxid_alice", True)
    state.set_allowed("wxid_alice", False)

    reloaded = ContactState(state_path=str(tmp_path / "contacts_state.json"))
    assert reloaded.is_allowed("wxid_alice") is False


def test_written_file_is_readable_json_with_chinese_intact(state, tmp_path):
    state.set_allowed("wxid_alice", True)
    raw = (tmp_path / "contacts_state.json").read_text(encoding="utf-8")
    assert json.loads(raw)["sessions"]["wxid_alice"]["allowed"] is True


# ------------------------------------------------------------- malformed input
def test_unreadable_file_denies_rather_than_crashing(tmp_path):
    """A truncated write must fail closed, not take the channel down."""
    path = tmp_path / "contacts_state.json"
    path.write_text('{"sessions": {"wxid_alice": {"allo', encoding="utf-8")

    store = ContactState(state_path=str(path))
    assert store.is_allowed("wxid_alice") is False


def test_an_unreadable_file_also_silences_the_agent(tmp_path):
    """Every switch fails closed, not just `allowed`.

    A lost document loses the operator's manual takeovers too. Defaulting
    auto_answer back to True there would put the agent back to speaking for
    them in exactly the conversations they had taken over by hand.
    """
    path = tmp_path / "contacts_state.json"
    path.write_text("{ truncated", encoding="utf-8")

    store = ContactState(state_path=str(path))
    assert store.auto_answer("wxid_alice") is False
    assert store.at_free("room1@chatroom") is False


def test_an_unreadable_file_is_reported_as_degraded(tmp_path):
    path = tmp_path / "contacts_state.json"
    path.write_text("{ truncated", encoding="utf-8")
    assert ContactState(state_path=str(path)).degraded is True


def test_a_missing_file_is_not_degraded(tmp_path):
    """A fresh install has no document yet; that is normal, not a failure."""
    store = ContactState(state_path=str(tmp_path / "nothing.json"))
    assert store.degraded is False
    assert store.auto_answer("wxid_alice") is True


def test_concurrent_toggles_leave_a_readable_document(tmp_path):
    """Two console requests can toggle at once: cheroot runs up to 80 threads.

    A shared temp filename let two writers interleave into one file and then
    race os.replace, publishing truncated JSON -- which the load above turns
    into "every switch lost".
    """
    import json as _json
    import threading

    path = str(tmp_path / "contacts_state.json")
    store = ContactState(state_path=path)

    def hammer(start):
        for i in range(start, start + 40):
            store.set_allowed(f"wxid_{i}", True)

    threads = [threading.Thread(target=hammer, args=(n * 40,)) for n in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    with open(path, encoding="utf-8") as f:
        _json.load(f)  # raises if any writer published a torn document
    assert ContactState(state_path=path).degraded is False


def test_non_dict_session_entry_is_dropped(tmp_path):
    """A hand-edited list where a dict belongs must not become an allow."""
    path = tmp_path / "contacts_state.json"
    path.write_text(json.dumps({"sessions": {"wxid_alice": ["allowed"]}}), encoding="utf-8")

    store = ContactState(state_path=str(path))
    assert store.is_allowed("wxid_alice") is False
    assert store.get("wxid_alice") is None


def test_non_boolean_switch_is_not_treated_as_true(tmp_path):
    """Truthiness must not widen the gate: only a real True allows."""
    path = tmp_path / "contacts_state.json"
    path.write_text(
        json.dumps({"sessions": {"wxid_alice": {"allowed": "yes"}}}), encoding="utf-8"
    )

    store = ContactState(state_path=str(path))
    assert store.is_allowed("wxid_alice") is False


def test_empty_id_is_never_allowed(state):
    state.set_allowed("", True)
    assert state.is_allowed("") is False


# ------------------------------------------------------------------- projection
def test_snapshot_reports_every_switch(state):
    state.set_allowed("wxid_alice", True)
    state.set_auto_answer("wxid_alice", False)

    snap = state.snapshot("wxid_alice")
    assert snap == {"allowed": True, "auto_answer": False, "at_free": False}


def test_snapshot_of_unknown_id_is_all_defaults(state):
    assert state.snapshot("wxid_nobody") == {
        "allowed": False,
        "auto_answer": True,
        "at_free": False,
    }
