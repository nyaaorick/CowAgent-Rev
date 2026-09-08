# encoding:utf-8

"""Who reaches the agent, who gets answered, and which rooms need an @mention.

These are the tests behind the console's four switches. Every one of them is an
access-control question, so each asserts on the gate's own answer rather than
on what the console renders: a greyed-out toggle is not an interception.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel
from channel.wcf.contact_filter import ALL_CONTACT, is_allowed_contact
from channel.wcf.contact_state import ContactState, set_contact_state
from channel.wcf.wcf_channel import WcfChannel


class FakeWcf:
    def __init__(self):
        self.sent = []

    def send_text(self, msg, receiver, aters=""):
        self.sent.append({"msg": msg, "receiver": receiver, "aters": aters})
        return 0


@pytest.fixture
def state(tmp_path):
    """Install a throwaway switch store for the duration of one test."""
    store = ContactState(state_path=str(tmp_path / "contacts_state.json"))
    set_contact_state(store)
    yield store
    set_contact_state(None)


@pytest.fixture
def channel(state):
    ch = WcfChannel.new_instance()      # bypass the @singleton cache
    ch.user_id = "wxid_bot"
    ch.name = "CowBot"
    ch.wcf = FakeWcf()
    ch.gateway = None
    return ch


# ------------------------------------------------------ whitelist precedence
def test_console_switch_admits_a_contact_absent_from_the_config_list(state):
    """Flipping the switch is the whole point; it must not need a config edit."""
    state.set_allowed("wxid_alice", True)
    assert is_allowed_contact([], "wxid_alice", state=state) is True


def test_console_switch_off_overrides_the_config_list(state):
    """Turning someone off in the console is the newer, more specific act."""
    state.set_allowed("wxid_alice", False)
    assert is_allowed_contact(["wxid_alice"], "wxid_alice", state=state) is False


def test_console_switch_off_overrides_all_contact(state):
    """ALL_CONTACT must not resurrect a contact the operator switched off."""
    state.set_allowed("wxid_alice", False)
    assert is_allowed_contact([ALL_CONTACT], "wxid_alice", state=state) is False


def test_a_contact_with_no_record_falls_back_to_the_config_list(state):
    """Existing installs keep working before anyone touches the console."""
    assert is_allowed_contact(["wxid_alice"], "wxid_alice", state=state) is True


def test_a_record_holding_only_other_switches_does_not_deny(state):
    """Setting a room's @mention rule must not revoke its config permission."""
    state.set_at_free("wxid_alice", True)
    assert is_allowed_contact(["wxid_alice"], "wxid_alice", state=state) is True


def test_nobody_is_allowed_when_both_sources_are_empty(state):
    assert is_allowed_contact([], "wxid_alice", state=state) is False


def test_a_lost_switch_document_does_not_fall_back_to_all_contact(state):
    """The fallback answers a question the operator has already answered.

    config.json is the older, broader source. Falling back to it while the
    operator's own decisions are missing is how a contact they switched off
    walks back in through ALL_CONTACT.
    """
    state._degraded = True
    assert is_allowed_contact([ALL_CONTACT], "wxid_alice", state=state) is False
    assert is_allowed_contact(["wxid_alice"], "wxid_alice", state=state) is False


def test_a_lost_switch_document_closes_rooms_too(channel, state):
    """Same for ALL_GROUP, which is a live setting on this host."""
    state._degraded = True
    assert channel.room_allowed("12345@chatroom") is False


def test_the_gate_still_works_without_a_switch_store():
    """contact_filter predates the store and must not require one."""
    assert is_allowed_contact(["wxid_alice"], "wxid_alice") is True
    assert is_allowed_contact([], "wxid_alice") is False


# --------------------------------------------------------------- reply mode
def test_an_observed_contact_receives_nothing(channel, state):
    """Manual takeover: the agent may think, but nothing reaches WeChat."""
    state.set_allowed("wxid_alice", True)
    state.set_auto_answer("wxid_alice", False)

    context = Context(ContextType.TEXT, "hi")
    context["receiver"] = "wxid_alice"
    channel.send(Reply(ReplyType.TEXT, "generated answer"), context)

    assert channel.wcf.sent == []


def test_a_normal_contact_still_receives_the_reply(channel, state):
    state.set_allowed("wxid_alice", True)

    context = Context(ContextType.TEXT, "hi")
    context["receiver"] = "wxid_alice"
    channel.send(Reply(ReplyType.TEXT, "generated answer"), context)

    assert channel.wcf.sent[0]["receiver"] == "wxid_alice"


def test_observing_one_contact_does_not_silence_another(channel, state):
    state.set_auto_answer("wxid_alice", False)

    context = Context(ContextType.TEXT, "hi")
    context["receiver"] = "wxid_bob"
    channel.send(Reply(ReplyType.TEXT, "generated answer"), context)

    assert channel.wcf.sent[0]["receiver"] == "wxid_bob"


# ------------------------------------------------------------ @mention rule
def test_channels_require_an_at_mention_by_default():
    """The base class must not change behaviour for every other channel."""
    assert ChatChannel.at_free_session(None, "12345@chatroom") is False


def test_a_room_switched_to_at_free_is_reported_as_such(channel, state):
    state.set_at_free("12345@chatroom", True)
    assert channel.at_free_session("12345@chatroom") is True


def test_a_room_without_the_switch_still_needs_an_at_mention(channel, state):
    state.set_allowed("12345@chatroom", True)
    assert channel.at_free_session("12345@chatroom") is False


# ----------------------------------------------------------- room whitelist
def test_a_room_switched_on_in_the_console_is_allowed(channel, state):
    state.set_allowed("12345@chatroom", True)
    assert channel.room_allowed("12345@chatroom") is True


def test_a_room_with_no_record_defers_to_the_existing_name_whitelist(channel, state):
    """group_name_white_list still governs rooms nobody has toggled."""
    assert channel.room_allowed("12345@chatroom") is None


def test_a_room_switched_off_is_refused_outright(channel, state):
    state.set_allowed("12345@chatroom", False)
    assert channel.room_allowed("12345@chatroom") is False
