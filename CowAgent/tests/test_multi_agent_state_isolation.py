import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.memory import (
    MemoryConfig,
    clear_conversation_store_cache,
    get_default_memory_config,
    get_conversation_store,
    register_memory_config,
    reset_memory_configs,
    set_global_memory_config,
)
from common.runtime_identity import identity_scope
from agent.registry import AgentProfile, AgentRegistry, get_agent_registry, set_agent_registry


@pytest.fixture
def isolated_registry(tmp_path):
    previous = get_agent_registry()
    registry = AgentRegistry(
        [
            AgentProfile("primary", "Primary", str(tmp_path / "primary")),
            AgentProfile("research", "Research", str(tmp_path / "research")),
        ],
        default_agent_id="primary",
    )
    set_agent_registry(registry)
    clear_conversation_store_cache()
    reset_memory_configs()
    try:
        yield registry
    finally:
        reset_memory_configs()
        clear_conversation_store_cache()
        set_agent_registry(previous)



def _message(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}




def test_conversations_with_same_session_id_use_different_databases(
    isolated_registry,
):
    primary = isolated_registry.get("primary")
    research = isolated_registry.get("research")
    primary_store = get_conversation_store(primary.workspace)
    research_store = get_conversation_store(research.workspace)

    primary_store.append_messages("same-session", [_message("primary")])
    research_store.append_messages("same-session", [_message("research")])

    assert primary_store is not research_store
    assert primary_store.load_messages("same-session")[0]["content"][0]["text"] == "primary"
    assert research_store.load_messages("same-session")[0]["content"][0]["text"] == "research"
    assert Path(primary_store._db_path) == Path(primary.workspace) / "memory/long-term/index.db"
    assert Path(research_store._db_path) == Path(research.workspace) / "memory/long-term/index.db"


def test_memory_config_keeps_each_agent_index_under_its_workspace(
    isolated_registry,
):
    primary = isolated_registry.get("primary")
    research = isolated_registry.get("research")

    primary_db = MemoryConfig(workspace_root=primary.workspace).get_db_path()
    research_db = MemoryConfig(workspace_root=research.workspace).get_db_path()

    assert primary_db != research_db
    assert primary_db == Path(primary.workspace) / "memory/long-term/index.db"
    assert research_db == Path(research.workspace) / "memory/long-term/index.db"




def test_tool_manager_instance_is_per_workspace(isolated_registry):
    from agent.tools.tool_manager import ToolManager

    ToolManager.reset_instances()
    try:
        with identity_scope(agent_id="primary"):
            primary = ToolManager()
        with identity_scope(agent_id="research"):
            research = ToolManager()
        with identity_scope(agent_id="primary"):
            assert ToolManager() is primary

        assert primary is not research
        assert primary.workspace_root != research.workspace_root
    finally:
        ToolManager.reset_instances()


def test_registering_one_agents_config_does_not_move_another(isolated_registry):
    """Each Agent's initializer registers its own config. Before this was keyed
    by workspace, the last one to initialize owned where every Agent's memory
    and conversation history landed."""
    for agent_id in ("primary", "research"):
        register_memory_config(
            MemoryConfig(workspace_root=isolated_registry.get(agent_id).workspace)
        )

    for agent_id in ("primary", "research"):
        workspace = Path(isolated_registry.get(agent_id).workspace)
        with identity_scope(agent_id=agent_id):
            assert Path(get_default_memory_config().workspace_root) == workspace
            assert get_conversation_store() is get_conversation_store(str(workspace))


def test_memory_config_follows_routing_without_any_registration(isolated_registry):
    """Startup paths read the config before any Agent has initialized."""
    for agent_id in ("primary", "research"):
        with identity_scope(agent_id=agent_id):
            assert Path(get_default_memory_config().workspace_root) == Path(
                isolated_registry.get(agent_id).workspace
            )


def test_pinned_config_overrides_routing(isolated_registry):
    pinned = MemoryConfig(workspace_root=isolated_registry.get("primary").workspace)
    try:
        set_global_memory_config(pinned)
        with identity_scope(agent_id="research"):
            assert get_default_memory_config() is pinned
    finally:
        set_global_memory_config(None)
    with identity_scope(agent_id="research"):
        assert get_default_memory_config() is not pinned


def test_no_argument_conversation_store_preserves_single_agent_default(
    isolated_registry,
):
    previous = get_default_memory_config()
    default_workspace = isolated_registry.get("primary").workspace
    try:
        set_global_memory_config(MemoryConfig(workspace_root=default_workspace))
        clear_conversation_store_cache()
        default_store = get_conversation_store()
        explicit_store = get_conversation_store(default_workspace)
        assert default_store is explicit_store
    finally:
        set_global_memory_config(previous)
        clear_conversation_store_cache()
