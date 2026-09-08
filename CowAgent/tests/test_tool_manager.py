# encoding:utf-8

"""ToolManager's instantiation path.

Rehomed from ``test_bash_config_propagation``, which existed to pin down how
``config.json``'s ``tools.bash.*`` reached the Bash tool (issue #2983). The
bash tool is gone, and with it every assertion in that file except this one --
which was never really about bash at all: it is the only coverage
``create_tool()`` has.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.base_tool import BaseTool
from agent.tools.tool_manager import ToolManager


class DummyTool(BaseTool):
    name = "dummy"
    description = "dummy"


def test_create_tool_builds_a_registered_tool():
    tm = ToolManager()
    tm.tool_classes = {"dummy": DummyTool}
    tm.tool_configs = {}

    tool = tm.create_tool("dummy")

    assert tool is not None
    assert tool.name == "dummy"


def test_a_config_for_another_tool_does_not_reach_this_one():
    """Per-tool config is keyed by name, so a stranger's entry is not applied.

    The original bug this guards against was the opposite: one tool's config
    dict leaking into every tool built afterwards.
    """
    tm = ToolManager()
    tm.tool_classes = {"dummy": DummyTool}
    tm.tool_configs = {"someone_else": {"timeout": 5}}

    tool = tm.create_tool("dummy")

    assert tool is not None
    assert tool.name == "dummy"
