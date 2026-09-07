# encoding:utf-8

"""Unit tests for the WeChatFerry channel adapter (Milestone 4.2).

These exercise the adapter's own logic — WxMsg -> ChatMessage mapping, the
send() routing, self/dup filtering, and which contacts may reach the agent —
without a real WeChat, a real wcferry, or a model call.
"""

import os
import sys

import logging

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.wcf.contact_filter import ALL_CONTACT, is_allowed_contact, normalize_white_list
from channel.wcf.wcf_channel import WcfChannel
from channel.wcf.wcf_message import WcfMessage
from config import conf


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
def white_list():
    """Set wcf_contact_white_list for one test and put it back afterwards.

    The channel reads it per message rather than caching it, so a test that
    left it changed would silently gate the next one.
    """
    original = conf().get("wcf_contact_white_list", None)

    def _set(value):
        conf()["wcf_contact_white_list"] = value

    _set(["wxid_alice"])
    yield _set
    if original is None:
        conf().pop("wcf_contact_white_list", None)
    else:
        conf()["wcf_contact_white_list"] = original


@pytest.fixture
def channel(white_list):
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


# ------------------------------------------------------ contact white list
# WeChat is the operator's own account, so "who may talk to the bot" is a
# safety property, not a preference: every one of these asserts a message is
# NOT answered unless the operator named the contact.
def test_a_whitelisted_contact_reaches_the_agent(channel, white_list):
    white_list(["wxid_alice"])
    produced = []
    channel.produce = produced.append
    channel._handle_wxmsg(FakeWxMsg(id=1, sender="wxid_alice", content="hi"))
    assert len(produced) == 1


def test_a_contact_outside_the_white_list_is_ignored(channel, white_list):
    white_list(["wxid_alice"])
    produced = []
    channel.produce = produced.append
    channel._handle_wxmsg(FakeWxMsg(id=2, sender="wxid_stranger", content="hi"))
    assert produced == []


def test_an_empty_white_list_answers_nobody(channel, white_list):
    """A truncated or half-written config must fail closed, never open."""
    white_list([])
    produced = []
    channel.produce = produced.append
    channel._handle_wxmsg(FakeWxMsg(id=3, sender="wxid_alice", content="hi"))
    assert produced == []


def test_all_contact_opens_every_private_chat(channel, white_list):
    white_list([ALL_CONTACT])
    produced = []
    channel.produce = produced.append
    channel._handle_wxmsg(FakeWxMsg(id=4, sender="wxid_anyone", content="hi"))
    assert len(produced) == 1


def test_the_white_list_matches_a_display_name_too(channel, white_list):
    """get_contacts() is broken on 3.9.12.56, so a name may resolve to the raw
    wxid. Both spellings have to work or the operator's entry goes dead."""
    channel._contacts = {"wxid_bob": {"wxid": "wxid_bob", "name": "小明"}}
    white_list(["小明"])
    produced = []
    channel.produce = produced.append
    channel._handle_wxmsg(FakeWxMsg(id=5, sender="wxid_bob", content="hi"))
    assert len(produced) == 1


def test_group_messages_are_not_gated_by_the_contact_list(channel, white_list):
    """Groups gate on group_name_white_list inside ChatChannel; applying the
    contact list to them as well would silently double-filter."""
    white_list([])
    composed = []
    channel._compose_context = lambda *a, **k: composed.append(1) or None
    channel._handle_wxmsg(
        FakeWxMsg(id=6, sender="wxid_alice", roomid="room1@chatroom",
                  at_wxids=["wxid_bot"])
    )
    assert len(composed) == 1


def test_a_reload_of_the_white_list_takes_effect_without_a_restart(channel, white_list):
    """spy.dll is a singleton injection (WCF-BUG-03), so a restart is expensive;
    adding a contact in the console must land on the next message instead."""
    white_list([])
    produced = []
    channel.produce = produced.append
    channel._handle_wxmsg(FakeWxMsg(id=7, sender="wxid_alice", content="hi"))
    assert produced == []

    white_list(["wxid_alice"])
    channel._handle_wxmsg(FakeWxMsg(id=8, sender="wxid_alice", content="hi"))
    assert len(produced) == 1


# --------------------------------------------------- contact_filter, in isolation
def test_a_comma_separated_string_is_accepted_as_a_white_list():
    """The console edits list fields as one line, so the value read back from
    config.json can be a string rather than a list."""
    assert is_allowed_contact("filehelper, wxid_alice", "wxid_alice") is True
    assert is_allowed_contact("filehelper, wxid_alice", "wxid_bob") is False


def test_blank_entries_do_not_match_a_contact_without_a_name():
    """A stray comma leaves an empty entry; it must not become a wildcard for
    contacts whose display name failed to resolve."""
    assert is_allowed_contact(["filehelper", "", "  "], "wxid_alice", "") is False


# ------------------------------------------------- console mirroring, at the seam
def test_a_wechat_message_is_stamped_with_its_channel(channel, white_list):
    """The whole console-mirroring feature hangs off this one field: the bridge
    copies context["channel_type"] into the conversation store, and the console
    lists sessions by it. A message that arrived unstamped would be persisted
    under the empty channel and never appear in the console."""
    white_list(["wxid_alice"])
    from channel import channel_factory
    from common import const

    # channel_type is stamped by the factory, not by the class.
    built = channel_factory.create_channel(const.WCF)
    built.user_id = "wxid_bot"
    built.name = "CowBot"
    built.wcf = FakeWcf()

    produced = []
    built.produce = produced.append
    built._handle_wxmsg(FakeWxMsg(id=101, sender="wxid_alice", content="你是谁"))

    assert len(produced) == 1
    assert produced[0]["channel_type"] == "wcf"
    # session_id is the contact, so one contact is one conversation in the list.
    assert produced[0]["session_id"] == "wxid_alice"


def test_a_null_in_the_white_list_does_not_become_a_contact_named_None():
    """A JSON null stringified to "None" would be matchable: a contact picks
    their own display name, so a stranger could rename themselves to match.
    A malformed list has to narrow the gate, never widen it."""
    assert normalize_white_list(["filehelper", None]) == ["filehelper"]
    assert is_allowed_contact(["", None], "wxid_stranger", "None") is False


def test_non_string_entries_are_dropped_rather_than_coerced():
    assert normalize_white_list([None, 0, True, {}, ["nested"]]) == []
    assert is_allowed_contact([None, 0], "wxid_stranger", "0") is False


# ----------------------------------------------------- the spy start pre-flight
# wcferry answers a failed dial with os._exit(-2) -- a process kill no except
# block can catch, which took the web console down with it. The channel drives
# the injection itself so a bad outcome is an ordinary exception instead.
class _FakeRun:
    def __init__(self, returncode):
        self.returncode = returncode


def _preflight(channel, monkeypatch, *, rc, listening):
    """Run _ensure_spy_listening with wcf.exe and the port both faked."""
    import subprocess
    from channel.wcf import wcf_channel as mod

    monkeypatch.setattr(mod, "_port_listening", lambda port, host="127.0.0.1": listening)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeRun(rc))
    # Keep the retry loop from costing the test 15 seconds.
    monkeypatch.setattr(type(channel), "_wait_for_port",
                        staticmethod(lambda port, timeout=15: listening))
    return channel._ensure_spy_listening(10086, False)


def test_an_already_listening_spy_needs_no_injection(channel, monkeypatch):
    import subprocess
    from channel.wcf import wcf_channel as mod

    monkeypatch.setattr(mod, "_port_listening", lambda port, host="127.0.0.1": True)

    def fail(*a, **k):
        raise AssertionError("wcf.exe must not run when the port already answers")

    monkeypatch.setattr(subprocess, "run", fail)
    assert channel._ensure_spy_listening(10086, False) is None


def test_a_wedged_spy_raises_instead_of_killing_the_process(channel, monkeypatch):
    """Exit code 10 means "already injected", which wcferry treats as ready.
    It is also what a stopped-but-loaded spy returns, and then nothing is
    listening -- the case that used to reach os._exit."""
    with pytest.raises(RuntimeError) as excinfo:
        _preflight(channel, monkeypatch, rc=10, listening=False)

    message = str(excinfo.value)
    assert "10086" in message
    assert "quit WeChat" in message  # the only remedy that actually works


def test_an_injected_and_healthy_spy_is_accepted(channel, monkeypatch):
    assert _preflight(channel, monkeypatch, rc=10, listening=True) is None


def test_a_fresh_injection_that_comes_up_is_accepted(channel, monkeypatch):
    assert _preflight(channel, monkeypatch, rc=0, listening=True) is None


def test_a_fresh_injection_that_never_binds_raises(channel, monkeypatch):
    with pytest.raises(RuntimeError):
        _preflight(channel, monkeypatch, rc=0, listening=False)


def test_wechat_not_running_says_so(channel, monkeypatch):
    with pytest.raises(RuntimeError) as excinfo:
        _preflight(channel, monkeypatch, rc=4, listening=False)
    assert "WeChat is not running" in str(excinfo.value)


def test_an_unknown_exit_code_still_raises_rather_than_continuing(channel, monkeypatch):
    with pytest.raises(RuntimeError) as excinfo:
        _preflight(channel, monkeypatch, rc=5, listening=False)
    assert "exit 5" in str(excinfo.value)
