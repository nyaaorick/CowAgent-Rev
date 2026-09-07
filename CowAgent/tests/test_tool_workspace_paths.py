"""Workspace-relative paths in tool arguments.

This cost the model a turn: vision rejected a relative path that read had just
accepted.
"""

import os

from agent.tools.vision.vision import Vision


def test_vision_resolves_relative_paths_against_the_workspace(tmp_path):
    (tmp_path / "tmp").mkdir()
    image = tmp_path / "tmp" / "shot.png"
    image.write_bytes(b"not really a png")

    tool = Vision({"cwd": str(tmp_path)})

    assert tool._resolve_path("tmp/shot.png") == str(image)


def test_vision_leaves_absolute_paths_alone(tmp_path):
    # Has to be absolute for *this* platform: os.path.isabs("/a/b.png") is
    # False on Windows, where a rooted path with no drive letter is
    # drive-relative, so a hardcoded POSIX path would test the relative branch.
    absolute = os.path.join(os.path.abspath(os.sep), "a", "b.png")

    assert Vision({"cwd": str(tmp_path)})._resolve_path(absolute) == absolute


def test_vision_names_the_resolved_path_when_the_image_is_missing(tmp_path):
    tool = Vision({"cwd": str(tmp_path)})
    try:
        tool._build_image_content("tmp/missing.png")
    except FileNotFoundError as error:
        assert "tmp/missing.png" in str(error)
        assert str(tmp_path) in str(error)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_every_tool_can_receive_the_workspace():
    """The bridge assigns cwd unconditionally; BaseTool declares it."""
    from agent.tools.base_tool import BaseTool

    assert hasattr(BaseTool, "cwd")
    assert hasattr(Vision(), "cwd")
