# encoding:utf-8

"""The console's address-book endpoints, tested below the web.py layer.

Following the house pattern for this file (see ``test_wcf_console_sessions``),
these exercise the functions the handlers delegate to rather than the request
cycle: the filtering the search box relies on, and the profile-file resolution
behind the Workspace button -- which turns a contact-chosen id into a path on
the operator's disk and is therefore the part worth pinning down hardest.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channel.wcf.scanner import ContactScanner
from channel.web.contacts_api import (
    ensure_profile,
    filter_rows,
    is_wechat_session,
    normalize_switch,
    set_scanner,
)


def row(wxid, name="", remark="", alias="", is_group=False):
    return {
        "wxid": wxid,
        "name": name or wxid,
        "nickname": remark or name or wxid,
        "remark": remark,
        "alias": alias,
        "is_group": is_group,
        "allowed": False,
        "auto_answer": True,
        "at_free": False,
        "last_seen": 0,
    }


@pytest.fixture
def rows():
    return [
        row("wxid_alice", name="Alice", remark="同事小明", alias="alice_wx"),
        row("wxid_bob", name="Bob", alias="bob2024"),
        row("12345@chatroom", name="项目群", is_group=True),
        row("67890@chatroom", name="家人群", is_group=True),
    ]


# ------------------------------------------------------------------ filtering
def test_no_filter_returns_everything(rows):
    assert len(filter_rows(rows)) == 4


def test_contacts_and_groups_are_separate_views(rows):
    assert [r["wxid"] for r in filter_rows(rows, kind="contact")] == [
        "wxid_alice", "wxid_bob"
    ]
    assert [r["wxid"] for r in filter_rows(rows, kind="group")] == [
        "12345@chatroom", "67890@chatroom"
    ]


def test_an_unknown_kind_does_not_silently_return_everything(rows):
    """A typo in the query string must not leak groups into the contact list."""
    assert filter_rows(rows, kind="contacts") == []


def test_search_matches_the_remark(rows):
    assert [r["wxid"] for r in filter_rows(rows, query="小明")] == ["wxid_alice"]


def test_search_matches_the_wechat_id(rows):
    assert [r["wxid"] for r in filter_rows(rows, query="bob2024")] == ["wxid_bob"]


def test_search_matches_the_nickname(rows):
    assert [r["wxid"] for r in filter_rows(rows, query="Alice")] == ["wxid_alice"]


def test_search_matches_the_raw_wxid(rows):
    """The id is what the operator has when the contact table is unreadable."""
    assert [r["wxid"] for r in filter_rows(rows, query="wxid_bob")] == ["wxid_bob"]


def test_search_ignores_case(rows):
    assert [r["wxid"] for r in filter_rows(rows, query="ALICE")] == ["wxid_alice"]


def test_search_ignores_surrounding_whitespace(rows):
    assert [r["wxid"] for r in filter_rows(rows, query="  Alice  ")] == ["wxid_alice"]


def test_search_and_kind_compose(rows):
    assert filter_rows(rows, kind="group", query="Alice") == []


def test_a_search_matching_nothing_returns_nothing(rows):
    assert filter_rows(rows, query="nobody-by-that-name") == []


# -------------------------------------------------------------- switch names
def test_only_known_switches_are_accepted():
    assert normalize_switch("allowed") == "allowed"
    assert normalize_switch("auto_answer") == "auto_answer"
    assert normalize_switch("at_free") == "at_free"


def test_an_unknown_switch_is_refused():
    """The name arrives in a request body and indexes into the state document."""
    assert normalize_switch("admin") is None
    assert normalize_switch("") is None
    assert normalize_switch(None) is None


# ------------------------------------------------------------ profile files
def test_profile_is_created_on_first_open(tmp_path):
    rel = ensure_profile(str(tmp_path), "wxid_alice")

    assert rel == "memory/users/wxid_alice/PROFILE.md"
    assert (tmp_path / "memory" / "users" / "wxid_alice" / "PROFILE.md").exists()


def test_an_existing_profile_is_not_overwritten(tmp_path):
    target = tmp_path / "memory" / "users" / "wxid_alice" / "PROFILE.md"
    target.parent.mkdir(parents=True)
    target.write_text("# 我写的偏好\n", encoding="utf-8")

    ensure_profile(str(tmp_path), "wxid_alice")

    assert target.read_text(encoding="utf-8") == "# 我写的偏好\n"


def test_a_new_profile_is_not_an_empty_file(tmp_path):
    """An empty file gives the operator nothing to react to, and the prompt
    loader skips it anyway."""
    ensure_profile(str(tmp_path), "wxid_alice")
    content = (tmp_path / "memory" / "users" / "wxid_alice" / "PROFILE.md").read_text(
        encoding="utf-8"
    )
    assert content.strip()


def test_a_room_gets_a_profile_too(tmp_path):
    rel = ensure_profile(str(tmp_path), "12345@chatroom")
    assert rel == "memory/users/12345@chatroom/PROFILE.md"


def test_a_traversing_id_cannot_escape_the_users_directory(tmp_path):
    """AC-007: the id is chosen by WeChat, not by us.

    The sanitizer folds separators into "_" rather than rejecting dots, so the
    check that matters is where the file actually lands, not how the name looks.
    """
    rel = ensure_profile(str(tmp_path), "../../../../etc/passwd")

    users_dir = os.path.realpath(str(tmp_path / "memory" / "users"))
    written = os.path.realpath(os.path.join(str(tmp_path), rel))
    assert written.startswith(users_dir + os.sep)
    # One directory below users/, not a chain climbing out of it.
    assert os.path.dirname(os.path.dirname(written)) == users_dir


def test_an_unusable_id_is_refused_rather_than_guessed(tmp_path):
    with pytest.raises(ValueError):
        ensure_profile(str(tmp_path), "..")


def test_an_empty_id_is_refused(tmp_path):
    with pytest.raises(ValueError):
        ensure_profile(str(tmp_path), "")


# --------------------------------------------------- where a message is going
@pytest.fixture
def catalog(tmp_path):
    """A scanner holding one contact and one room, and nothing else."""
    scanner = ContactScanner(cache_path=str(tmp_path / "contacts_cache.json"))
    scanner.register_or_update("wxid_alice", name="Alice", source="micromsg_contact",
                               auto_save=False)
    scanner.register_or_update("12345@chatroom", name="Team", is_group=True,
                               source="micromsg_contact", auto_save=False)
    set_scanner(scanner)
    yield scanner
    set_scanner(None)


def test_a_known_contact_is_a_wechat_session(catalog):
    """The first message to a contact must reach WeChat, not the model.

    Whether a conversation is a WeChat one cannot be read off the stored
    history: a contact nobody has written to yet has no history, and answering
    "no" for them sent the operator's message to the agent instead -- which
    then recorded the session as a console chat and made the mistake permanent.
    """
    assert is_wechat_session("wxid_alice") is True


def test_a_known_room_is_a_wechat_session(catalog):
    assert is_wechat_session("12345@chatroom") is True


def test_a_console_session_is_not(catalog):
    assert is_wechat_session("session_4f344d1e-8f0f-46e8-8c69-cdf7817eea5d") is False


def test_an_id_absent_from_the_address_book_is_not(catalog):
    """The id arrives in a request body, so the catalog is the authority."""
    assert is_wechat_session("wxid_never_seen") is False


def test_an_empty_id_is_not(catalog):
    assert is_wechat_session("") is False
    assert is_wechat_session(None) is False


def test_relay_to_wechat_heals_misclassified_web_session(monkeypatch, tmp_path):
    """When a session previously got stored as channel_type='web' due to routing
    mistakes, relay_to_wechat corrects its channel_type to 'wcf'."""
    from agent.memory.conversation_store import get_conversation_store, clear_conversation_store_cache
    from channel.web import contacts_api
    from common import const

    clear_conversation_store_cache()
    # Mock workspace root to return our temp dir
    monkeypatch.setattr("channel.web.web_channel._get_workspace_root", lambda **kwargs: str(tmp_path))

    store = get_conversation_store(str(tmp_path))
    # Seed a session that was erroneously recorded as 'web'
    store.append_messages(
        "wxid_alice",
        [{"role": "user", "content": "hello"}],
        channel_type="web",
    )
    assert store.get_channel_type("wxid_alice") == "web"

    # Mock WcfChannel to succeed on send_as_operator
    class MockWcf:
        def send_as_operator(self, session_id, text):
            return True

    monkeypatch.setattr("channel.wcf.wcf_channel.WcfChannel", lambda: MockWcf())

    res = contacts_api.relay_to_wechat("wxid_alice", "my reply")
    assert res == {"status": "success", "relayed": True}

    # Verify channel_type was healed to 'wcf'
    assert store.get_channel_type("wxid_alice") == const.WCF

