# encoding:utf-8

"""Sending to WeChat from the console composer.

Typing into a WeChat conversation in the console now reaches the contact, so
these tests pin down the two things that separates it from the agent's own
replies: the operator is not subject to the observe-only switch (taking over by
hand is exactly what that switch is for), and what they sent has to be recorded
where the console will show it -- otherwise the message leaves and the operator
sees nothing happen.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channel.wcf.contact_state import ContactState, set_contact_state
from channel.wcf.wcf_channel import WcfChannel


class FakeWcf:
    def __init__(self, status=0):
        self.sent = []
        self.status = status

    def send_text(self, msg, receiver, aters=""):
        self.sent.append({"msg": msg, "receiver": receiver, "aters": aters})
        return self.status


@pytest.fixture
def state(tmp_path):
    store = ContactState(state_path=str(tmp_path / "contacts_state.json"))
    set_contact_state(store)
    yield store
    set_contact_state(None)


@pytest.fixture
def channel(state):
    ch = WcfChannel.new_instance()
    ch.user_id = "wxid_bot"
    ch.name = "CowBot"
    ch.wcf = FakeWcf()
    ch.gateway = None
    return ch


def test_the_operator_reaches_a_contact_they_are_observing(channel, state):
    """The observe-only switch silences the agent, not the person operating it."""
    state.set_auto_answer("wxid_alice", False)

    assert channel.send_as_operator("wxid_alice", "typed by hand") is True
    assert channel.wcf.sent[0] == {
        "msg": "typed by hand", "receiver": "wxid_alice", "aters": "",
    }


def test_a_normal_contact_is_reachable_too(channel, state):
    state.set_allowed("wxid_alice", True)
    assert channel.send_as_operator("wxid_alice", "hello") is True


def test_an_empty_message_is_not_sent(channel, state):
    assert channel.send_as_operator("wxid_alice", "   ") is False
    assert channel.wcf.sent == []


def test_an_empty_receiver_is_not_sent(channel, state):
    assert channel.send_as_operator("", "hello") is False
    assert channel.wcf.sent == []


def test_a_failed_send_is_reported_as_failure(channel, state):
    """send_text answers with a status; a wedged spy returns non-zero."""
    channel.wcf = FakeWcf(status=-1)
    assert channel.send_as_operator("wxid_alice", "hello") is False


def test_no_connection_is_reported_rather_than_raising(channel, state):
    channel.wcf = None
    assert channel.send_as_operator("wxid_alice", "hello") is False
