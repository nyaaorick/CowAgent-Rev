"""Tests for PromptManager and unified prompts.json configuration."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from agent.prompt.manager import PromptManager, get_prompt, get_prompt_manager
from agent.prompt.builder import PromptBuilder, _build_response_language_section
from agent.prompt.workspace import (
    _get_agent_template,
    _get_user_template,
    _get_rule_template,
    _get_memory_template,
    _get_bootstrap_template,
)
from agent.subagent.templates import load_templates


class PromptManagerTest(unittest.TestCase):
    def test_global_instance_loads_prompts_json(self):
        pm = get_prompt_manager()
        self.assertIsNotNone(pm)
        # Verify schema version or known key exists
        version = pm.get("$schema_version")
        self.assertEqual(version, "1.0")

    def test_dot_path_retrieval(self):
        # Retrieve tooling header
        zh_header = get_prompt("system_prompt.tooling.zh.header")
        self.assertEqual(zh_header, "## 🔧 工具系统")

        en_header = get_prompt("system_prompt.tooling.en.header")
        self.assertEqual(en_header, "## 🔧 Tooling")

    def test_language_resolution_and_fallback(self):
        # lang="zh"
        header_zh = get_prompt("system_prompt.tooling.header", lang="zh")
        self.assertEqual(header_zh, "## 🔧 工具系统")

        # lang="en"
        header_en = get_prompt("system_prompt.tooling.header", lang="en")
        self.assertEqual(header_en, "## 🔧 Tooling")

        # Unsupported language falls back to zh
        header_fallback = get_prompt("system_prompt.tooling.header", lang="fr")
        self.assertIn(header_fallback, ["## 🔧 工具系统", "## 🔧 Tooling"])

    def test_variable_interpolation(self):
        # Variable interpolation on string and list
        instructions = get_prompt("system_prompt.skills.instructions", lang="zh", read_tool_name="test_read")
        self.assertIsInstance(instructions, list)
        found_var = any("test_read" in item for item in instructions)
        self.assertTrue(found_var, "Interpolated variable read_tool_name not found in skills instructions")

        # String interpolation
        title = get_prompt("chat_utils.title_generation.prompt", context="Hello AI")
        self.assertIn("Hello AI", title)

    def test_missing_key_fallback(self):
        val = get_prompt("non.existent.key.path", fallback="default_value")
        self.assertEqual(val, "default_value")

    def test_hot_reload_on_file_modification(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as f:
            temp_path = f.name
            json.dump({"test_key": "v1"}, f)

        try:
            pm = PromptManager(json_path=temp_path)
            self.assertEqual(pm.get("test_key"), "v1")

            # Update file and ensure mtime shifts
            time.sleep(0.05)
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump({"test_key": "v2"}, f)
            # Force mtime forward if needed
            future_mtime = os.path.getmtime(temp_path) + 2.0
            os.utime(temp_path, (future_mtime, future_mtime))

            # Set last_check to 0 to bypass 1s throttling in test
            pm._last_check = 0.0
            val = pm.get("test_key")
            self.assertEqual(val, "v2")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_corrupted_json_fallback_safety(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as f:
            temp_path = f.name
            f.write("{invalid json: broken")

        try:
            pm = PromptManager(json_path=temp_path)
            val = pm.get("any.key", fallback="safe_fallback")
            self.assertEqual(val, "safe_fallback")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


class IntegrationPromptTest(unittest.TestCase):
    def test_response_language_has_negative_constraints(self):
        # Verify negative constraints are present in Chinese response language prompt
        zh_lines = _build_response_language_section("zh")
        zh_text = "\n".join(zh_lines)
        self.assertIn("严禁在中文", zh_text)
        self.assertIn("英文问候模板", zh_text)
        self.assertIn("Hello! If you have any questions", zh_text)

        en_lines = _build_response_language_section("en")
        en_text = "\n".join(en_lines)
        self.assertIn("strictly reply in the same language", en_text)
        self.assertIn("Never reply with generic English greeting templates", en_text)

    def test_prompt_builder_runs_cleanly(self):
        builder = PromptBuilder(workspace_dir="/tmp/test_workspace", language="zh")
        prompt = builder.build()
        self.assertIsInstance(prompt, str)
        self.assertIn("工作空间", prompt)
        self.assertIn("回复语言", prompt)

    def test_workspace_templates_load_from_prompts_json(self):
        agent_md = _get_agent_template("zh")
        self.assertIn("AGENT.md", agent_md)
        self.assertIn("基本信息", agent_md)

        user_md = _get_user_template("zh")
        self.assertIn("USER.md", user_md)

        rule_md = _get_rule_template("zh")
        self.assertIn("RULE.md", rule_md)

        mem_md = _get_memory_template("zh")
        self.assertIn("MEMORY.md", mem_md)

        bootstrap_md = _get_bootstrap_template("zh")
        self.assertIn("BOOTSTRAP.md", bootstrap_md)

    def test_subagent_templates_load(self):
        templates = load_templates()
        self.assertIn("general-purpose", templates)
        self.assertIn("explore", templates)
        self.assertTrue(len(templates["general-purpose"].prompt) > 0)
        self.assertTrue(len(templates["explore"].prompt) > 0)


if __name__ == "__main__":
    unittest.main()

