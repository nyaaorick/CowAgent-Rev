# encoding:utf-8
"""The path key shared by MemoryManager and KnowledgeService.

``chunks.path`` / ``files.path`` are keys matched with ``WHERE path = ?``, and
the two sides that use them build them differently: MemoryManager derives them
from ``Path.relative_to`` (OS-native separators) while KnowledgeService joins
them by hand with "/". On Windows those disagreed, so deleting or moving a
knowledge document never removed its chunks and the stale text kept coming back
from memory search. The knowledge tests could not catch it - they drive a
FakeMemoryManager, so the contract between the two was never exercised.
"""
import asyncio
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory.config import MemoryConfig
from agent.memory.manager import MemoryManager
from agent.memory.storage import MemoryChunk, MemoryStorage, canonical_memory_path


def _synced_manager(tmp_path):
    (tmp_path / "knowledge" / "concepts").mkdir(parents=True)
    (tmp_path / "knowledge" / "concepts" / "a.md").write_text(
        "# A\nsomething about rag\n", encoding="utf-8"
    )
    (tmp_path / "MEMORY.md").write_text("# mem\nhello\n", encoding="utf-8")

    manager = MemoryManager(
        MemoryConfig(workspace_root=str(tmp_path)), embedding_provider=None
    )
    manager.mark_dirty()
    result = manager.sync()
    if asyncio.iscoroutine(result):
        asyncio.run(result)
    return manager


def _paths(manager, table):
    return sorted(
        row[0] for row in manager.storage.conn.execute(f"SELECT DISTINCT path FROM {table}")
    )


def test_nested_paths_are_stored_in_posix_form(tmp_path):
    manager = _synced_manager(tmp_path)
    try:
        assert "knowledge/concepts/a.md" in _paths(manager, "files")
        assert "knowledge/concepts/a.md" in _paths(manager, "chunks")
    finally:
        manager.storage.close()


def test_knowledge_service_style_delete_removes_manager_written_rows(tmp_path):
    """The contract itself: KnowledgeService._sync_index deletes by
    f"knowledge/{rel_path}", where rel_path is always slash-joined."""
    manager = _synced_manager(tmp_path)
    try:
        manager.storage.delete_by_path("knowledge/concepts/a.md")

        assert _paths(manager, "files") == ["MEMORY.md"]
        assert _paths(manager, "chunks") == ["MEMORY.md"]
    finally:
        manager.storage.close()


def test_a_native_separator_key_still_finds_the_row(tmp_path):
    """Callers that pass an OS-native path are canonicalized, not missed."""
    manager = _synced_manager(tmp_path)
    try:
        assert manager.storage.get_file_hash("knowledge\\concepts\\a.md") is not None

        manager.storage.delete_by_path("knowledge\\concepts\\a.md")

        assert _paths(manager, "files") == ["MEMORY.md"]
    finally:
        manager.storage.close()


def test_legacy_backslash_rows_are_migrated_keeping_their_embeddings():
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "index.db"
    storage = MemoryStorage(db)
    storage.save_chunk(MemoryChunk(
        id="c1", user_id=None, scope="shared", source="knowledge",
        path="knowledge/concepts/a.md", start_line=1, end_line=1,
        text="rag", embedding=[0.1, 0.2, 0.3], hash="h1",
    ))
    storage.update_file_metadata("knowledge/concepts/a.md", "knowledge", "h1", 0, 10)
    storage.close()

    # Rewrite to what a pre-fix Windows run would have stored.
    conn = sqlite3.connect(db)
    conn.execute(r"UPDATE chunks SET path = 'knowledge\concepts\a.md'")
    conn.execute(r"UPDATE files  SET path = 'knowledge\concepts\a.md'")
    conn.commit()
    conn.close()

    reopened = MemoryStorage(db)
    try:
        assert _paths_of(reopened, "chunks") == ["knowledge/concepts/a.md"]
        assert _paths_of(reopened, "files") == ["knowledge/concepts/a.md"]
        # Rewritten, not dropped: embeddings cost API calls to recompute, and
        # the chunk id (derived from the path) is deliberately left alone.
        row = reopened.conn.execute("SELECT id, embedding FROM chunks").fetchone()
        assert row[0] == "c1"
        assert row[1] is not None
        assert reopened.get_file_hash("knowledge/concepts/a.md") == "h1"
    finally:
        reopened.close()


def _paths_of(storage, table):
    return sorted(row[0] for row in storage.conn.execute(f"SELECT DISTINCT path FROM {table}"))


def test_canonical_memory_path_is_idempotent_and_posix():
    assert canonical_memory_path("knowledge\\a.md") == "knowledge/a.md"
    assert canonical_memory_path("knowledge/a.md") == "knowledge/a.md"
    assert canonical_memory_path(Path("knowledge") / "a.md") in (
        "knowledge/a.md",
    )


def test_the_chunk_dataclass_canonicalizes_on_construction():
    chunk = MemoryChunk(
        id="x", user_id=None, scope="shared", source="knowledge",
        path="knowledge\\concepts\\a.md", start_line=1, end_line=1,
        text="t", embedding=None, hash="h",
    )
    assert chunk.path == "knowledge/concepts/a.md"
