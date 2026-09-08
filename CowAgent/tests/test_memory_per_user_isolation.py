"""Long-term memory is partitioned per person on WeChat.

Memory lives on disk as ``memory/*.md`` (shared) or ``memory/users/<id>/*.md``
(one person's), and ``scope`` is inferred from that path when the index is
built. Both halves of the machinery already took a ``user_id`` and nothing ever
supplied one, so every WeChat contact wrote into and read from the same pile:
what the agent learned about one person surfaced while it talked to another.

These pin the rule that decides the owner, the sanitising that stands between a
wxid and a directory name, and the fence that stops one conversation reading
another's file by naming it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.memory.identity import (
    PER_PERSON_CHANNELS,
    memory_owner_id,
    sanitize_owner_id,
)


def _ctx(channel, session_id):
    return {"channel_type": channel, "session_id": session_id}


# ------------------------------------------------------------- who owns a turn
def test_a_wechat_contact_owns_their_own_memory():
    assert memory_owner_id(_ctx("wcf", "wxid_alice")) == "wxid_alice"


def test_two_wechat_contacts_get_different_owners():
    a = memory_owner_id(_ctx("wcf", "wxid_alice"))
    b = memory_owner_id(_ctx("wcf", "wxid_bob"))
    assert a != b and a and b


def test_the_console_keeps_one_shared_pile():
    """Every console conversation is the same operator talking to their own
    agent. Splitting those would scatter one person's memory across
    conversations, which is worse than sharing it."""
    assert memory_owner_id(_ctx("web", "session_abc")) is None
    assert memory_owner_id(_ctx("terminal", "session_abc")) is None


def test_an_unknown_channel_keeps_the_previous_shared_behaviour():
    """Channels are opted in one at a time; anything unlisted must behave
    exactly as it did before this existed."""
    assert memory_owner_id(_ctx("feishu", "u_1")) is None
    assert "web" not in PER_PERSON_CHANNELS


def test_a_group_room_is_one_shared_room_memory():
    """session_id is the room, so the room gets one memory rather than a
    scattering of per-speaker ones."""
    room = memory_owner_id(_ctx("wcf", "room1@chatroom"))
    assert room == "room1@chatroom"


def test_no_context_and_no_session_fall_back_to_shared():
    assert memory_owner_id(None) is None
    assert memory_owner_id({}) is None
    assert memory_owner_id(_ctx("wcf", "")) is None


# ------------------------------------------- a wxid becomes a directory name
def test_real_wxid_shapes_survive_unchanged():
    """These are the ids actually seen on this host; mangling them would split
    one person's memory across two directories."""
    for wxid in ("filehelper", "wxid_1u2zfb3han0g22", "25984984666999465@openim",
                 "room1@chatroom", "a-b.c_d"):
        assert sanitize_owner_id(wxid) == wxid


def test_a_traversing_id_cannot_climb_out_of_the_users_directory(tmp_path):
    """The id arrives from WeChat and becomes a path segment.

    Asserted the way it actually matters: join the result under the users
    directory and confirm it resolves inside. A sanitised "../../etc" becomes
    the odd but harmless single name ".._.._etc" -- ugly is fine, escaping is
    not, and asserting on the literal ".." would have failed a safe result.
    """
    base = (tmp_path / "memory" / "users").resolve()
    hostile_ids = (
        "../../etc",
        "..\\..\\windows",
        "a/../../b",
        "a/b",
        "C:\\Windows\\System32",
        "/etc/passwd",
    )
    for hostile in hostile_ids:
        cleaned = sanitize_owner_id(hostile)
        if cleaned is None:
            continue
        resolved = (base / cleaned).resolve()
        assert str(resolved).startswith(str(base) + os.sep), (
            f"{hostile!r} -> {cleaned!r} escaped to {resolved}"
        )


def test_ids_that_are_only_dots_are_refused():
    """"." and ".." survive a character filter but are not directory names."""
    assert sanitize_owner_id(".") is None
    assert sanitize_owner_id("..") is None
    assert sanitize_owner_id("   ") is None
    assert sanitize_owner_id(None) is None


def test_a_long_id_is_capped():
    assert len(sanitize_owner_id("x" * 500)) <= 64


def test_distinct_ids_stay_distinct_after_sanitising():
    """Folding characters must not collapse two people into one directory."""
    assert sanitize_owner_id("wxid_a") != sanitize_owner_id("wxid_b")


# ------------------------------------------------- reading another's memory
class _Config:
    def __init__(self, workspace):
        self._workspace = workspace

    def get_workspace(self):
        return self._workspace


class _Manager:
    def __init__(self, workspace):
        self.config = _Config(workspace)


def _get_tool(workspace, user_id):
    from agent.tools.memory.memory_get import MemoryGetTool
    return MemoryGetTool(_Manager(workspace), user_id=user_id)


def _read(tool, workspace, rel_path):
    return tool.execute({"path": rel_path})


def _seed(workspace, rel_path, text="secret"):
    target = workspace / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def test_a_contact_can_read_their_own_memory(tmp_path):
    _seed(tmp_path, "memory/users/wxid_alice/MEMORY.md", "alice's notes")
    result = _read(_get_tool(tmp_path, "wxid_alice"), tmp_path,
                   "memory/users/wxid_alice/MEMORY.md")
    assert result.status != "error", result.result
    assert "alice's notes" in result.result


def test_a_contact_cannot_read_another_contacts_memory(tmp_path):
    """The model chooses this path, so naming someone else's file is the
    obvious way to defeat a write-side-only split."""
    _seed(tmp_path, "memory/users/wxid_bob/MEMORY.md", "bob's private notes")
    result = _read(_get_tool(tmp_path, "wxid_alice"), tmp_path,
                   "memory/users/wxid_bob/MEMORY.md")
    assert result.status == "error"
    assert "another user" in result.result
    assert "bob's private notes" not in result.result


def test_shared_memory_stays_readable_by_everyone(tmp_path):
    """Shared is shared on purpose; only the users/ subtree is fenced."""
    _seed(tmp_path, "memory/2026-09-06.md", "a shared daily note")
    result = _read(_get_tool(tmp_path, "wxid_alice"), tmp_path,
                   "memory/2026-09-06.md")
    assert result.status != "error", result.result
    assert "a shared daily note" in result.result


def test_the_console_cannot_read_a_wechat_contacts_memory(tmp_path):
    """The console's owner is None, which must not act as a master key."""
    _seed(tmp_path, "memory/users/wxid_bob/MEMORY.md", "bob's private notes")
    result = _read(_get_tool(tmp_path, None), tmp_path,
                   "memory/users/wxid_bob/MEMORY.md")
    assert result.status == "error"
    assert "bob's private notes" not in result.result


def test_the_workspace_fence_still_holds(tmp_path):
    outside = tmp_path.parent / "outside.md"
    outside.write_text("not yours", encoding="utf-8")
    result = _read(_get_tool(tmp_path, "wxid_alice"), tmp_path, "../outside.md")
    assert result.status == "error"
    assert "not yours" not in result.result
