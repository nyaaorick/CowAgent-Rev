"""Editing workspace files from the web console preview panel."""

import json
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.protocol.artifact import EDITABLE_KINDS
from agent.workspace.service import (
    MAX_TEXT_BYTES,
    WorkspaceConflictError,
    WorkspaceService,
)


def _service(tmp_path):
    return WorkspaceService(str(tmp_path))


def _write(path, text):
    """Write LF-only bytes; Path.write_text would translate to CRLF on Windows."""
    path.write_bytes(text.encode("utf-8"))
    return path


# ----------------------------------------------------------------------
# WorkspaceService.write_text
# ----------------------------------------------------------------------
def test_write_text_overwrites_and_reports_fresh_metadata(tmp_path):
    target = _write(tmp_path / "notes.md", "old\n")
    svc = _service(tmp_path)

    result = svc.write_text("notes.md", "# new\nbody\n")

    assert target.read_text(encoding="utf-8") == "# new\nbody\n"
    assert result["path"] == "notes.md"
    assert result["size"] == target.stat().st_size
    assert result["mtime"] == pytest.approx(target.stat().st_mtime)


def test_write_text_round_trips_through_read_text(tmp_path):
    _write(tmp_path / "a.py", "print(1)\n")
    svc = _service(tmp_path)

    loaded = svc.read_text("a.py")
    assert loaded["editable"] is True
    assert loaded["truncated"] is False

    svc.write_text("a.py", loaded["content"] + "print(2)\n",
                   expected_mtime=loaded["mtime"])
    assert svc.read_text("a.py")["content"] == "print(1)\nprint(2)\n"


def test_write_text_rejects_stale_mtime(tmp_path):
    target = _write(tmp_path / "notes.md", "original\n")
    svc = _service(tmp_path)
    stale = svc.read_text("notes.md")["mtime"]

    os.utime(target, (stale + 60, stale + 60))

    with pytest.raises(WorkspaceConflictError):
        svc.write_text("notes.md", "mine\n", expected_mtime=stale)
    # The conflicting content must survive an attempt that lost the race.
    assert target.read_text(encoding="utf-8") == "original\n"

    # Without a baseline the write is an explicit overwrite and goes through.
    svc.write_text("notes.md", "mine\n")
    assert target.read_text(encoding="utf-8") == "mine\n"


def test_write_text_refuses_binary_kinds(tmp_path):
    (tmp_path / "chart.png").write_bytes(b"\x89PNG\r\n")
    svc = _service(tmp_path)

    with pytest.raises(ValueError):
        svc.write_text("chart.png", "not an image")
    assert (tmp_path / "chart.png").read_bytes() == b"\x89PNG\r\n"


def test_write_text_refuses_to_create_missing_file(tmp_path):
    svc = _service(tmp_path)

    with pytest.raises(FileNotFoundError):
        svc.write_text("does-not-exist.md", "hello")
    assert not (tmp_path / "does-not-exist.md").exists()


def test_write_text_rejects_path_escaping_the_workspace(tmp_path):
    outside = tmp_path.parent / "outside.md"
    _write(outside, "secret\n")
    root = tmp_path / "root"
    root.mkdir()
    svc = _service(root)

    with pytest.raises(ValueError):
        svc.write_text("../outside.md", "tampered\n")
    assert outside.read_text(encoding="utf-8") == "secret\n"


def test_write_text_rejects_oversized_content(tmp_path):
    _write(tmp_path / "big.txt", "x")
    svc = _service(tmp_path)

    with pytest.raises(ValueError):
        svc.write_text("big.txt", "y" * (MAX_TEXT_BYTES + 1))
    assert (tmp_path / "big.txt").read_text(encoding="utf-8") == "x"


def test_write_text_keeps_crlf_line_endings(tmp_path):
    target = tmp_path / "win.txt"
    target.write_bytes(b"one\r\ntwo\r\n")
    svc = _service(tmp_path)

    # The browser hands back LF-only text even for a CRLF file.
    svc.write_text("win.txt", "one\ntwo\nthree\n")

    assert target.read_bytes() == b"one\r\ntwo\r\nthree\r\n"


def test_write_text_leaves_lf_files_alone(tmp_path):
    target = tmp_path / "unix.txt"
    target.write_bytes(b"one\ntwo\n")

    _service(tmp_path).write_text("unix.txt", "one\r\ntwo\r\n")

    assert target.read_bytes() == b"one\ntwo\n"


def test_read_text_marks_non_utf8_file_uneditable(tmp_path):
    """A GBK document previews with replacement chars; saving would destroy it."""
    (tmp_path / "gbk.txt").write_bytes("运动训练计划\n".encode("gbk"))

    loaded = _service(tmp_path).read_text("gbk.txt")

    assert loaded["lossy"] is True
    assert loaded["editable"] is False


def test_write_text_refuses_to_overwrite_a_non_utf8_file(tmp_path):
    original = "运动训练计划\n".encode("gbk")
    (tmp_path / "gbk.txt").write_bytes(original)

    with pytest.raises(ValueError):
        _service(tmp_path).write_text("gbk.txt", "\ufffd\ufffd\n")
    assert (tmp_path / "gbk.txt").read_bytes() == original


def test_write_text_refuses_a_file_too_large_to_have_been_read_whole(tmp_path):
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * (MAX_TEXT_BYTES + 10))

    with pytest.raises(ValueError):
        _service(tmp_path).write_text("big.txt", "truncated")
    assert big.stat().st_size == MAX_TEXT_BYTES + 10


def test_read_text_reports_clean_utf8_as_lossless(tmp_path):
    _write(tmp_path / "zh.md", "# 运动训练计划\n")

    loaded = _service(tmp_path).read_text("zh.md")

    assert loaded["lossy"] is False
    assert loaded["editable"] is True
    assert loaded["content"] == "# 运动训练计划\n"


def test_read_text_marks_truncated_file_uneditable(tmp_path):
    _write(tmp_path / "huge.txt", "z" * 4096)

    loaded = _service(tmp_path).read_text("huge.txt", max_bytes=1024)

    assert loaded["truncated"] is True
    assert loaded["editable"] is False


def test_dispatch_stays_read_only():
    """Remote transports forward action strings straight into dispatch."""
    result = WorkspaceService(".").dispatch("write", {"path": "a.md", "content": "x"})

    assert result["code"] == 400
    assert "unknown action" in result["message"]


# ----------------------------------------------------------------------
# HTTP handlers
# ----------------------------------------------------------------------
def _post(handler_cls, body):
    from channel.web import web_channel

    with patch.object(web_channel, "_require_auth"), \
         patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "data", return_value=json.dumps(body).encode()):
        return json.loads(handler_cls().POST())


def _get(handler_cls, params):
    from channel.web import web_channel

    with patch.object(web_channel, "_require_auth"), \
         patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "input", return_value=web_channel.web.storage(**params)):
        return json.loads(handler_cls().GET())


def test_read_handler_returns_content_and_baseline(tmp_path):
    from channel.web.web_channel import WorkspaceReadHandler

    _write(tmp_path / "notes.md", "hello\n")

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)), \
         patch("common.state_dir.state_root_str", return_value=str(tmp_path)):
        response = _get(WorkspaceReadHandler, {"path": "notes.md", "session": "s1", "agent": ""})

    assert response["status"] == "success"
    assert response["content"] == "hello\n"
    assert response["editable"] is True
    assert response["mtime"] == pytest.approx((tmp_path / "notes.md").stat().st_mtime)


def test_write_handler_saves_file(tmp_path):
    from channel.web.web_channel import WorkspaceWriteHandler

    target = _write(tmp_path / "notes.md", "hello\n")

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)), \
         patch("common.state_dir.state_root_str", return_value=str(tmp_path)):
        response = _post(WorkspaceWriteHandler, {
            "path": str(target),
            "content": "goodbye\n",
            "session": "s1",
            "expected_mtime": target.stat().st_mtime,
        })

    assert response["status"] == "success"
    assert target.read_text(encoding="utf-8") == "goodbye\n"


def test_write_handler_reports_conflict_code(tmp_path):
    from channel.web.web_channel import WorkspaceWriteHandler

    target = _write(tmp_path / "notes.md", "hello\n")

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)), \
         patch("common.state_dir.state_root_str", return_value=str(tmp_path)):
        response = _post(WorkspaceWriteHandler, {
            "path": "notes.md",
            "content": "mine\n",
            "expected_mtime": target.stat().st_mtime - 60,
        })

    assert response["status"] == "error"
    assert response["code"] == "conflict"
    assert target.read_text(encoding="utf-8") == "hello\n"


def test_write_handler_rejects_non_string_content(tmp_path):
    from channel.web.web_channel import WorkspaceWriteHandler

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)):
        response = _post(WorkspaceWriteHandler, {"path": "notes.md", "content": None})

    assert response["status"] == "error"
    assert "content" in response["message"]


def test_write_handler_rejects_path_outside_workspace(tmp_path):
    from channel.web.web_channel import WorkspaceWriteHandler

    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "elsewhere.md"
    _write(outside, "secret\n")

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(project)), \
         patch("common.state_dir.state_root_str", return_value=str(project)):
        response = _post(WorkspaceWriteHandler, {
            "path": str(outside),
            "content": "tampered\n",
        })

    assert response["status"] == "error"
    assert outside.read_text(encoding="utf-8") == "secret\n"


def test_write_handler_falls_back_to_state_root_for_system_assets(tmp_path):
    """Memory files stay in the state root even while a project is open."""
    from channel.web.web_channel import WorkspaceWriteHandler

    state_root = tmp_path / "cow"
    (state_root / "memory").mkdir(parents=True)
    memory_file = _write(state_root / "memory" / "MEMORY.md", "old\n")
    project = tmp_path / "project"
    project.mkdir()

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(project)), \
         patch("common.state_dir.state_root_str", return_value=str(state_root)):
        response = _post(WorkspaceWriteHandler, {
            "path": "memory/MEMORY.md",
            "content": "new\n",
            "session": "s1",
        })

    assert response["status"] == "success"
    assert memory_file.read_text(encoding="utf-8") == "new\n"


# ----------------------------------------------------------------------
# Frontend contract
# ----------------------------------------------------------------------
def test_web_console_editor_contract():
    root = Path(__file__).parents[1]
    html = (root / "channel/web/chat.html").read_text(encoding="utf-8")
    js = (root / "channel/web/static/js/workspace.js").read_text(encoding="utf-8")
    css = (root / "channel/web/static/css/console.css").read_text(encoding="utf-8")
    console = (root / "channel/web/static/js/console.js").read_text(encoding="utf-8")

    assert 'id="ws-btn-edit"' in html
    assert 'id="ws-btn-save"' in html
    assert 'id="ws-btn-edit-cancel"' in html
    assert "onclick=\"startPreviewEdit()\"" in html
    assert "onclick=\"savePreviewEdit()\"" in html
    assert "onclick=\"cancelPreviewEdit()\"" in html

    assert "async function startPreviewEdit(" in js
    assert "async function savePreviewEdit(" in js
    assert "function cancelPreviewEdit(" in js
    assert "function wsGuardUnsaved(" in js
    # A text area normalizes CRLF to LF in its value, so the dirty baseline has
    # to come from the mounted element and not from the raw response text -
    # otherwise every CRLF file looks edited the moment it is opened.
    assert "wsEditBaseline = wsMountEditor(body, data.content).value;" in js
    # The guard clears the editing flag before it retries, so discarding must
    # retry through wsExitEdit; retrying through cancelPreviewEdit would hit its
    # own `if (!wsEditing) return` and leave the editor on screen.
    assert "wsGuardUnsaved(wsExitEdit)" in js
    assert "/api/workspace/read?path=" in js
    assert "fetch('/api/workspace/write'" in js
    assert "expected_mtime:" in js
    assert "data.code === 'conflict'" in js

    assert ".ws-editor" in css
    # Every string the editor shows must exist in all three locales.
    for key in ("ws_edit", "ws_edit_save", "ws_edit_cancel", "ws_edit_saved",
                "ws_edit_save_failed", "ws_edit_load_failed", "ws_edit_too_large",
                "ws_edit_unsupported", "ws_edit_encoding", "ws_edit_conflict_title",
                "ws_edit_conflict_msg", "ws_edit_overwrite", "ws_edit_discard_title",
                "ws_edit_discard_msg", "ws_edit_discard_ok"):
        assert console.count(f"{key}:") == 3, key

    # An unchanged file must not be rewritten, and Ctrl+S must not be able to
    # race a second write against the first one's mtime.
    assert "if (!force && !wsEditorDirty())" in js
    assert "if (wsSaving) return;" in js

    # Switching session or starting a new chat resets the panel, so both have to
    # settle an open editor before they commit rather than dropping it silently.
    assert "!wsGuardUnsaved(() => switchSession(newSessionId))" in console
    assert "!wsGuardUnsaved(() => newChat(optimistic, inherit))" in console
