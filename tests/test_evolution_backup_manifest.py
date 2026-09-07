# encoding:utf-8
"""The evolution backup manifest is a persisted, cross-platform format.

restore_backup rebuilds each destination as ``workspace / entry["rel"]``. When
the manifest was written with OS-native separators, a Windows-written entry
("skills\\writer\\SKILL.md") still resolved on Windows but became a single
filename containing literal backslashes anywhere else. The existing coverage
backed up one top-level file only, so nested entries were never exercised.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.evolution.backup import _backups_root, create_backup, restore_backup


def _nested_workspace(tmp_path):
    skill = tmp_path / "skills" / "writer" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("original\n", encoding="utf-8")
    return skill


def test_manifest_records_nested_paths_in_posix_form(tmp_path):
    import json

    skill = _nested_workspace(tmp_path)
    backup_id = create_backup(tmp_path, [skill])
    assert backup_id

    manifest = json.loads(
        (_backups_root(tmp_path) / backup_id / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    rels = [entry["rel"] for entry in manifest]
    assert rels == ["skills/writer/SKILL.md"]
    assert not any(chr(92) in rel for rel in rels)


def test_a_nested_file_round_trips_through_restore(tmp_path):
    skill = _nested_workspace(tmp_path)
    backup_id = create_backup(tmp_path, [skill])

    skill.write_text("CORRUPTED\n", encoding="utf-8")
    assert restore_backup(tmp_path, backup_id) is True

    assert skill.read_text(encoding="utf-8") == "original\n"
