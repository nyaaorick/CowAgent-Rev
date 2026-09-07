# encoding:utf-8
"""The scheduler's tasks.json backup must survive non-ASCII task text.

save_tasks writes the store as UTF-8 with ensure_ascii=False, but its backup
copy read it back in text mode with no encoding - i.e. the locale codec. On any
non-UTF-8 locale a task described in Chinese raised UnicodeDecodeError, and by
then opening the destination in 'w' mode had already truncated the previous
good backup. The bare `except: pass` swallowed it, so every save silently left
a 0-byte .bak behind.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.tools.scheduler.task_store import TaskStore

_CHINESE = "每天早上八点提醒我开会"


def _store(tmp_path):
    return TaskStore(str(tmp_path / "scheduler" / "tasks.json"))


def test_a_non_ascii_task_round_trips(tmp_path):
    store = _store(tmp_path)
    store.save_tasks({"t1": {"id": "t1", "description": _CHINESE}})

    assert store.load_tasks()["t1"]["description"] == _CHINESE


def test_the_backup_holds_the_previous_content_verbatim(tmp_path):
    store = _store(tmp_path)
    store.save_tasks({"t1": {"id": "t1", "description": _CHINESE}})
    first = Path(store.store_path).read_bytes()

    store.save_tasks({"t1": {"id": "t1", "description": _CHINESE + "（改）"}})

    backup = Path(f"{store.store_path}.bak")
    assert backup.exists()
    # Byte-for-byte, not a re-encoded approximation.
    assert backup.read_bytes() == first
    assert json.loads(backup.read_text(encoding="utf-8"))["tasks"]["t1"][
        "description"
    ] == _CHINESE


def test_an_existing_good_backup_is_never_left_empty(tmp_path):
    store = _store(tmp_path)
    store.save_tasks({"t1": {"id": "t1", "description": "ascii only"}})
    store.save_tasks({"t1": {"id": "t1", "description": _CHINESE}})
    store.save_tasks({"t1": {"id": "t1", "description": _CHINESE + "!"}})

    backup = Path(f"{store.store_path}.bak")
    assert backup.stat().st_size > 0
