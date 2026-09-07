# encoding:utf-8

"""Unit tests for the WeChatFerry channel adapter (Milestone 4.2).

These exercise the adapter's own logic — WxMsg -> ChatMessage mapping, the
send() routing, self/dup filtering — without a real WeChat, a real wcferry,
or a model call. The end-to-end path (against the fake RPC server, with GLM
mocked and live) lives in tests/wcf_sim/.
"""

import os
import sys

import logging

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.wcf.wcf_channel import WcfChannel
from channel.wcf.wcf_message import WcfMessage


# --------------------------------------------------------------------------- fakes
class FakeWxMsg:
    """The subset of wcferry.WxMsg the adapter touches."""

    def __init__(self, *, id=1, ts=1_756_000_000, type=1, content="hi",
                 sender="wxid_alice", roomid="", is_self=False, at_wxids=()):
        self.id = id
        self.ts = ts
        self.type = type
        self.content = content
        self.sender = sender
        self.roomid = roomid
        self._is_self = is_self
        self._at = set(at_wxids)

    def from_self(self):
        return self._is_self

    def from_group(self):
        return bool(self.roomid)

    def is_at(self, wxid):
        return wxid in self._at


class FakeWcf:
    def __init__(self):
        self.sent = []
        self.send_status = 0

    def send_text(self, msg, receiver, aters=""):
        self.sent.append({"msg": msg, "receiver": receiver, "aters": aters})
        return self.send_status

    def get_alias_in_chatroom(self, wxid, roomid):
        return ""

    def get_contacts(self):
        return []


@pytest.fixture
def channel():
    ch = WcfChannel.new_instance()      # bypass the @singleton cache
    ch.user_id = "wxid_bot"
    ch.name = "CowBot"
    ch.wcf = FakeWcf()
    return ch


# ------------------------------------------------------------------ WcfMessage
def test_private_text_maps_reply_target_to_the_sender(channel):
    cmsg = WcfMessage(channel, FakeWxMsg(sender="wxid_alice", content="ping"))
    assert cmsg.ctype == ContextType.TEXT
    assert cmsg.content == "ping"
    assert cmsg.is_group is False
    assert cmsg.from_user_id == "wxid_alice"
    assert cmsg.other_user_id == "wxid_alice"      # base class copies this into receiver
    assert cmsg.is_at is False


def test_group_text_maps_reply_target_to_the_room(channel):
    wxmsg = FakeWxMsg(sender="wxid_alice", roomid="room1@chatroom",
                      content="@CowBot hello", at_wxids=["wxid_bot"])
    cmsg = WcfMessage(channel, wxmsg)
    assert cmsg.is_group is True
    assert cmsg.other_user_id == "room1@chatroom"  # reply to the room, never the speaker
    assert cmsg.actual_user_id == "wxid_alice"
    assert cmsg.is_at is True
    assert "CowBot" in cmsg.at_list                # feeds the base class's @-prefix strip


def test_group_text_without_a_mention_is_not_at(channel):
    cmsg = WcfMessage(channel, FakeWxMsg(roomid="room1@chatroom", at_wxids=[]))
    assert cmsg.is_at is False


def test_non_text_message_is_rejected(channel):
    with pytest.raises(NotImplementedError):
        WcfMessage(channel, FakeWxMsg(type=3, content=""))   # 3 == image


# ----------------------------------------------------------------- send() routing
def _ctx(isgroup, receiver, cmsg=None):
    ctx = Context(ContextType.TEXT, "q")
    ctx["isgroup"] = isgroup
    ctx["receiver"] = receiver
    if cmsg is not None:
        ctx["msg"] = cmsg
    return ctx


def test_send_private_text_has_no_at(channel):
    channel.send(Reply(ReplyType.TEXT, "pong"), _ctx(False, "wxid_alice"))
    assert channel.wcf.sent == [{"msg": "pong", "receiver": "wxid_alice", "aters": ""}]


def test_send_group_text_ats_the_asker(channel):
    cmsg = WcfMessage(channel, FakeWxMsg(sender="wxid_alice", roomid="room1@chatroom",
                                         at_wxids=["wxid_bot"]))
    channel.send(Reply(ReplyType.TEXT, "pong"), _ctx(True, "room1@chatroom", cmsg))
    sent = channel.wcf.sent[0]
    assert sent["receiver"] == "room1@chatroom"
    assert sent["aters"] == "wxid_alice"


def test_send_drops_unsupported_reply_types(channel):
    channel.send(Reply(ReplyType.VOICE, "/tmp/a.mp3"), _ctx(False, "wxid_alice"))
    assert channel.wcf.sent == []
    assert ReplyType.VOICE in channel.NOT_SUPPORT_REPLYTYPE


def test_send_with_no_receiver_is_a_noop(channel):
    channel.send(Reply(ReplyType.TEXT, "pong"), _ctx(False, None))
    assert channel.wcf.sent == []


# ------------------------------------------------------- _handle_wxmsg filtering
def test_handle_skips_the_bots_own_messages(channel):
    produced = []
    channel.produce = produced.append
    channel._handle_wxmsg(FakeWxMsg(sender="wxid_bot", is_self=True))
    assert produced == []


def test_handle_deduplicates_by_message_id(channel):
    calls = []
    channel._compose_context = lambda *a, **k: calls.append(1) or None
    channel._handle_wxmsg(FakeWxMsg(id=42))
    channel._handle_wxmsg(FakeWxMsg(id=42))
    assert len(calls) == 1


def test_handle_skips_unsupported_types_without_producing(channel):
    produced = []
    channel.produce = produced.append
    channel._handle_wxmsg(FakeWxMsg(id=7, type=34, content=""))   # 34 == voice
    assert produced == []


# ------------------------------------------------------------------- the factory
def test_factory_builds_the_wcf_channel():
    from channel import channel_factory
    from common import const

    ch = channel_factory.create_channel(const.WCF)
    assert isinstance(ch, WcfChannel.__wrapped__)
    assert ch.channel_type == "wcf"


def test_a_failed_send_is_reported_as_an_error(channel, caplog):
    """send_text returns 0 on success; the channel used to log "sent text"
    regardless, so a wedged spy - whose RPC just times out after the socket's
    5s send + 5s recv - still looked like a delivered reply."""
    channel.wcf.send_status = 1

    with caplog.at_level(logging.ERROR):
        channel.send(Reply(ReplyType.TEXT, "pong"), _ctx(False, "wxid_alice"))

    assert any("failed (status=1)" in r.message for r in caplog.records)
    assert not any("sent text to" in r.message for r in caplog.records)


def test_a_successful_send_still_logs_success(channel, caplog):
    with caplog.at_level(logging.INFO):
        channel.send(Reply(ReplyType.TEXT, "pong"), _ctx(False, "wxid_alice"))

    assert any("sent text to wxid_alice" in r.message for r in caplog.records)
