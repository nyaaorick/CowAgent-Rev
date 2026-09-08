"""The console lists WeChat conversations beside its own.

A WeChat chat the agent held is stored in the same conversation store as a
console chat, tagged ``channel_type='wcf'``. The console used to query
``channel_type='web'`` only, so those conversations existed but were invisible.
These tests pin the two halves of making them visible: the store can filter on
several channels at once and reports which one each row came from, and the
console asks for exactly the channels it can display.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.memory.conversation_store import ConversationStore, _channel_where


def _store(tmpdir):
    return ConversationStore(Path(tmpdir) / "index.db")


def _seed(store, session_id, channel_type):
    store.append_messages(
        session_id,
        [{"role": "user", "content": f"from {channel_type}"}],
        channel_type=channel_type,
    )


# ------------------------------------------------------------ the channel filter
def test_no_filter_selects_every_channel():
    assert _channel_where(None) == ("", ())


def test_a_filter_naming_only_blanks_is_treated_as_no_filter():
    """Otherwise it would compile to `channel_type = ''` and quietly match
    nothing, which reads on screen as "the user has no conversations"."""
    assert _channel_where(["", "  "]) == ("", ())


def test_one_channel_compiles_to_an_equality_test():
    where, params = _channel_where("web")
    assert where == " WHERE channel_type = ?"
    assert params == ("web",)


def test_several_channels_compile_to_an_in_test():
    where, params = _channel_where(["web", "wcf"])
    assert where == " WHERE channel_type IN (?, ?)"
    assert params == ("web", "wcf")


# --------------------------------------------------------------- list_sessions
def test_listing_several_channels_returns_conversations_from_each():
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        _seed(store, "console_chat", "web")
        _seed(store, "wxid_alice", "wcf")
        _seed(store, "feishu_chat", "feishu")

        result = store.list_sessions(channel_type=["web", "wcf"])

        listed = {s["session_id"] for s in result["sessions"]}
        assert listed == {"console_chat", "wxid_alice"}
        assert result["total"] == 2


def test_each_listed_conversation_reports_its_own_channel():
    """The console badges a WeChat chat and locks its composer, so it has to be
    told which rows came from WeChat -- the session id alone does not say."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        _seed(store, "console_chat", "web")
        _seed(store, "wxid_alice", "wcf")

        by_id = {
            s["session_id"]: s["channel"]
            for s in store.list_sessions(channel_type=["web", "wcf"])["sessions"]
        }
        assert by_id == {"console_chat": "web", "wxid_alice": "wcf"}


def test_a_single_channel_filter_still_excludes_the_others():
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        _seed(store, "console_chat", "web")
        _seed(store, "wxid_alice", "wcf")

        result = store.list_sessions(channel_type="web")
        assert [s["session_id"] for s in result["sessions"]] == ["console_chat"]


def test_list_session_ids_accepts_several_channels():
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        _seed(store, "console_chat", "web")
        _seed(store, "wxid_alice", "wcf")
        _seed(store, "feishu_chat", "feishu")

        ids = store.list_session_ids(channel_type=["web", "wcf"])
        assert set(ids) == {"console_chat", "wxid_alice"}


def test_a_wechat_conversation_reads_back_in_full():
    """Displaying the conversation is the point; the history endpoint is
    channel-agnostic, so this asserts the turns survive the round trip."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        store.append_messages(
            "wxid_alice",
            [
                {"role": "user", "content": "你是谁"},
                {"role": "assistant", "content": "我是电子鹦鹉"},
            ],
            channel_type="wcf",
        )

        page = store.load_history_page("wxid_alice", page=1, page_size=20)
        texts = [m.get("content") for m in page["messages"]]
        assert "你是谁" in texts
        assert "我是电子鹦鹉" in texts


def test_load_history_page_preserves_leading_assistant_messages():
    """Messages sent by the operator to a contact before any user message must
    not be dropped by turn grouping."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        store.append_messages(
            "wxid_bob",
            [
                {"role": "assistant", "content": "你好，我是客服"},
                {"role": "assistant", "content": "请问有什么可以帮您？"},
            ],
            channel_type="wcf",
        )
        page = store.load_history_page("wxid_bob", page=1, page_size=20)
        assert page["total"] == 2
        assert len(page["messages"]) == 2
        assert page["messages"][0]["role"] == "assistant"
        assert page["messages"][0]["content"] == "你好，我是客服"
        assert page["messages"][1]["role"] == "assistant"
        assert page["messages"][1]["content"] == "请问有什么可以帮您？"


def test_load_history_page_preserves_consecutive_assistant_messages_after_user():
    """Multiple operator messages following a user message should each be their
    own turn, not collapsed into the last one."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        store.append_messages(
            "wxid_bob",
            [
                {"role": "user", "content": "在吗"},
                {"role": "assistant", "content": "在的"},
                {"role": "assistant", "content": "有什么事吗"},
            ],
            channel_type="wcf",
        )
        page = store.load_history_page("wxid_bob", page=1, page_size=20)
        assert page["total"] == 3
        assert [m["content"] for m in page["messages"]] == ["在吗", "在的", "有什么事吗"]



# --------------------------------------------------------- what the console asks
def test_the_console_lists_web_and_wechat_but_not_every_channel():
    from channel.web.web_channel import CONSOLE_SESSION_CHANNELS

    assert set(CONSOLE_SESSION_CHANNELS) == {"web", "wcf"}


def test_wechat_conversations_are_read_only_in_the_console():
    """Sending into one from the console would answer in the browser while the
    contact keeps waiting in WeChat."""
    from channel.web.web_channel import (
        CONSOLE_SESSION_CHANNELS,
        READ_ONLY_SESSION_CHANNELS,
    )

    assert "wcf" in READ_ONLY_SESSION_CHANNELS
    assert "web" not in READ_ONLY_SESSION_CHANNELS
    # Anything unanswerable must still be listed, or it is simply missing.
    assert set(READ_ONLY_SESSION_CHANNELS) <= set(CONSOLE_SESSION_CHANNELS)


# --------------------------------------------- the read-only rule is enforced
# The composer being disabled is a courtesy to whoever is looking at the page.
# session_id arrives in the request body, so the rule has to hold on the server
# too -- these drive the predicate that /message consults.
def _read_only(monkeypatch, tmp, session_id):
    """Run web_channel's read-only check against a store built in `tmp`."""
    from channel.web import web_channel

    monkeypatch.setattr(web_channel, "_get_workspace_root", lambda **kw: str(tmp))
    return web_channel._is_read_only_session(session_id)


def test_a_wechat_session_is_refused_server_side(monkeypatch, tmp_path):
    from agent.memory import get_conversation_store
    from agent.memory.conversation_store import clear_conversation_store_cache

    clear_conversation_store_cache()
    _seed(get_conversation_store(str(tmp_path)), "wxid_alice", "wcf")

    assert _read_only(monkeypatch, tmp_path, "wxid_alice") is True


def test_a_console_session_stays_writable(monkeypatch, tmp_path):
    from agent.memory import get_conversation_store
    from agent.memory.conversation_store import clear_conversation_store_cache

    clear_conversation_store_cache()
    _seed(get_conversation_store(str(tmp_path)), "console_chat", "web")

    assert _read_only(monkeypatch, tmp_path, "console_chat") is False


def test_a_brand_new_session_stays_writable(monkeypatch, tmp_path):
    """Every conversation the console starts is unknown to the store until its
    first turn lands; refusing those would break the console outright."""
    from agent.memory.conversation_store import clear_conversation_store_cache

    clear_conversation_store_cache()
    assert _read_only(monkeypatch, tmp_path, "session_not_created_yet") is False


def test_an_empty_session_id_is_not_treated_as_read_only(monkeypatch, tmp_path):
    from agent.memory.conversation_store import clear_conversation_store_cache

    clear_conversation_store_cache()
    assert _read_only(monkeypatch, tmp_path, "") is False


def test_an_unreadable_store_does_not_lock_the_operator_out(monkeypatch, tmp_path):
    """Failing closed here would mean a broken store bricks the console; the
    client-side guard still covers the case this is defending."""
    from channel.web import web_channel

    def boom(**kwargs):
        raise OSError("store unavailable")

    monkeypatch.setattr(web_channel, "_get_workspace_root", boom)
    assert web_channel._is_read_only_session("wxid_alice") is False


def test_the_store_reports_a_sessions_channel():
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        _seed(store, "wxid_alice", "wcf")

        assert store.get_channel_type("wxid_alice") == "wcf"
        assert store.get_channel_type("never_seen") == ""


# ------------------------------------------------- the console's list-typed field
def test_a_list_config_value_survives_the_console_round_trip():
    """The contact white list is edited as one line in the channel panel; it has
    to come back a list so config.json keeps one shape for the key."""
    from channel.web.web_channel import _join_list_field, _split_list_field

    line = _join_list_field(["filehelper", "wxid_alice"])
    assert line == "filehelper, wxid_alice"
    assert _split_list_field(line) == ["filehelper", "wxid_alice"]


def test_an_emptied_contact_field_saves_as_an_empty_list():
    from channel.web.web_channel import _split_list_field

    assert _split_list_field("") == []
    assert _split_list_field("  ,  ") == []


def test_a_list_value_sent_directly_is_not_stringified():
    """The desktop client and the API can POST a real list; re-splitting one
    would turn it into a single "['a', 'b']" entry."""
    from channel.web.web_channel import _split_list_field

    assert _split_list_field(["filehelper", "wxid_alice"]) == ["filehelper", "wxid_alice"]
