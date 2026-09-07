# encoding:utf-8

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import conf, available_setting, load_config
from agent.tools.base_tool import BaseTool, ToolResult, is_tool_available
from agent.protocol.agent_stream import AgentStreamExecutor


class _MockTool(BaseTool):
    name = "mock_tool"
    description = "A mock tool for testing"
    params = {"type": "object", "properties": {"q": {"type": "string"}}}

    def execute(self, params):
        return ToolResult.success("executed")


def test_tool_call_enabled_default_is_false():
    """Verify tool_call_enabled defaults to False in configuration."""
    assert available_setting.get("tool_call_enabled") is False
    load_config()
    assert conf().get("tool_call_enabled") is False


def test_is_tool_available_respects_toggle():
    """Verify is_tool_available returns False when toggle is off, True when on."""
    tool = _MockTool()
    
    conf()["tool_call_enabled"] = False
    assert is_tool_available(tool) is False

    conf()["tool_call_enabled"] = True
    assert is_tool_available(tool) is True

    # Clean up
    conf()["tool_call_enabled"] = False


def test_select_tools_for_injection_respects_toggle():
    """Verify _select_tools_for_injection returns empty list when toggle is off."""
    tool = _MockTool()
    executor = object.__new__(AgentStreamExecutor)
    executor.tools = {tool.name: tool}

    conf()["tool_call_enabled"] = False
    assert executor._select_tools_for_injection() == []

    conf()["tool_call_enabled"] = True
    assert executor._select_tools_for_injection() == [tool]

    # Clean up
    conf()["tool_call_enabled"] = False


def test_execute_tool_blocks_when_disabled():
    """Verify _execute_tool returns disabled error when toggle is off and agent is set."""
    tool = _MockTool()
    executor = object.__new__(AgentStreamExecutor)
    executor.tools = {tool.name: tool}
    executor.agent = object()
    executor._record_tool_result = lambda *a, **kw: None

    conf()["tool_call_enabled"] = False
    res = executor._execute_tool({"id": "1", "name": "mock_tool", "arguments": {"q": "test"}})
    assert res["status"] == "error"
    assert "Tool calling is currently disabled" in res["result"]

    # Clean up
    conf()["tool_call_enabled"] = False


def test_system_prompt_excludes_tools_when_toggle_is_off(tmp_path):
    """Verify get_full_system_prompt omits tooling section when toggle is off."""
    from agent.protocol.agent import Agent

    tool = _MockTool()
    agent = Agent(
        system_prompt="Base prompt",
        tools=[tool],
        workspace_dir=str(tmp_path),
    )

    conf()["tool_call_enabled"] = False
    prompt_off = agent.get_full_system_prompt()
    assert "mock_tool" not in prompt_off
    assert "## 🔧" not in prompt_off

    conf()["tool_call_enabled"] = True
    prompt_on = agent.get_full_system_prompt()
    assert "mock_tool" in prompt_on
    assert "## 🔧" in prompt_on

    # Clean up
    conf()["tool_call_enabled"] = False


def test_config_handler_reflects_and_updates_toggle(monkeypatch, tmp_path):
    """Verify ConfigHandler GET and POST properly serialize tool_call_enabled."""
    from channel.web.web_channel import ConfigHandler
    import json
    import web

    web.ctx.headers = []
    handler = ConfigHandler()

    # Test GET
    conf()["tool_call_enabled"] = False
    data = json.loads(handler.GET())
    assert data["tool_call_enabled"] is False

    conf()["tool_call_enabled"] = True
    data = json.loads(handler.GET())
    assert data["tool_call_enabled"] is True

    # Test POST
    monkeypatch.setattr("channel.web.web_channel._require_auth", lambda: None)
    monkeypatch.setattr("channel.web.web_channel.get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr("channel.web.web_channel._read_config_file_for_write", lambda: {})
    web.data = lambda: json.dumps({"updates": {"tool_call_enabled": False}}).encode("utf-8")

    post_res = json.loads(handler.POST())
    assert post_res["status"] == "success"
    assert conf()["tool_call_enabled"] is False

    web.data = lambda: json.dumps({"updates": {"tool_call_enabled": True}}).encode("utf-8")
    post_res = json.loads(handler.POST())
    assert post_res["status"] == "success"
    assert conf()["tool_call_enabled"] is True

    # Clean up
    conf()["tool_call_enabled"] = False
