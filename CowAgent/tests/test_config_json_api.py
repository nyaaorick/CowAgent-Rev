# encoding:utf-8
import json
import os
import sys
import types
import unittest
from unittest.mock import mock_open, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import web


def _no_response_headers():
    import channel.web.web_channel as web_channel
    return patch.object(web_channel.web, "header", lambda *args, **kwargs: None)


class TestConfigJsonHandler(unittest.TestCase):

    def test_get_config_json_default(self):
        from channel.web.web_channel import ConfigJsonHandler

        with patch("channel.web.web_channel._require_auth", lambda: None), \
             patch("channel.web.web_channel.web.input", return_value=types.SimpleNamespace(file="config.json")), \
             _no_response_headers():
            raw = ConfigJsonHandler().GET()
            result = json.loads(raw)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["file"], "config.json")
        self.assertIn("content", result)
        self.assertTrue(len(result["content"]) > 0)
        files = [f["id"] for f in result.get("files", [])]
        self.assertIn("config.json", files)
        self.assertIn("prompts.json", files)

    def test_get_prompts_json(self):
        from channel.web.web_channel import ConfigJsonHandler

        with patch("channel.web.web_channel._require_auth", lambda: None), \
             patch("channel.web.web_channel.web.input", return_value=types.SimpleNamespace(file="prompts.json")), \
             _no_response_headers():
            raw = ConfigJsonHandler().GET()
            result = json.loads(raw)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["file"], "prompts.json")
        self.assertIn("content", result)
        parsed = json.loads(result["content"])
        self.assertIn("$schema_version", parsed)

    def test_get_disallowed_file_rejected(self):
        from channel.web.web_channel import ConfigJsonHandler

        for bad_file in ["../../etc/passwd", "secret.py", "app.py", "../config.py"]:
            with patch("channel.web.web_channel._require_auth", lambda: None), \
                 patch("channel.web.web_channel.web.input", return_value=types.SimpleNamespace(file=bad_file)), \
                 _no_response_headers():
                raw = ConfigJsonHandler().GET()
                result = json.loads(raw)

            self.assertEqual(result["status"], "error")
            self.assertIn("disallowed", result["message"].lower())

    def test_post_disallowed_file_rejected(self):
        from channel.web.web_channel import ConfigJsonHandler

        payload = {"file": "malicious.py", "content": "{}"}
        with patch("channel.web.web_channel._require_auth", lambda: None), \
             patch("channel.web.web_channel.web.data", return_value=json.dumps(payload).encode("utf-8")), \
             _no_response_headers():
            raw = ConfigJsonHandler().POST()
            result = json.loads(raw)

        self.assertEqual(result["status"], "error")

    def test_post_invalid_json_syntax(self):
        from channel.web.web_channel import ConfigJsonHandler

        payload = {"file": "config.json", "content": "{ broken: json, invalid }"}
        with patch("channel.web.web_channel._require_auth", lambda: None), \
             patch("channel.web.web_channel.web.data", return_value=json.dumps(payload).encode("utf-8")), \
             _no_response_headers():
            raw = ConfigJsonHandler().POST()
            result = json.loads(raw)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result.get("code"), "json_parse_error")

    def test_post_non_dict_json_rejected(self):
        from channel.web.web_channel import ConfigJsonHandler

        payload = {"file": "config.json", "content": '["item1", "item2"]'
        }
        with patch("channel.web.web_channel._require_auth", lambda: None), \
             patch("channel.web.web_channel.web.data", return_value=json.dumps(payload).encode("utf-8")), \
             _no_response_headers():
            raw = ConfigJsonHandler().POST()
            result = json.loads(raw)

        self.assertEqual(result["status"], "error")
        self.assertIn("Object", result["message"])

    def test_post_config_json_success_and_sync(self):
        from channel.web.web_channel import ConfigJsonHandler
        from config import Config

        local_config = Config({"model": "gpt-4o", "bot_type": "openai"})
        new_data = {"model": "glm-5.2", "bot_type": "zhipu", "cow_lang": "zh"}
        payload = {"file": "config.json", "content": json.dumps(new_data)}

        mock_bridge = MagicMock()
        with patch("channel.web.web_channel._require_auth", lambda: None), \
             patch("channel.web.web_channel.web.data", return_value=json.dumps(payload).encode("utf-8")), \
             patch("channel.web.web_channel.conf", return_value=local_config), \
             patch('builtins.open', mock_open()) as m_open, \
             patch("channel.web.web_channel.i18n.resolve_language") as m_lang, \
             patch("bridge.bridge.Bridge", return_value=mock_bridge), \
             _no_response_headers():
            raw = ConfigJsonHandler().POST()
            result = json.loads(raw)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["file"], "config.json")
        self.assertEqual(local_config["model"], "glm-5.2")
        self.assertEqual(local_config["bot_type"], "zhipu")
        m_lang.assert_called_with("zh")
        mock_bridge.reset_bot.assert_called_once()
        m_open.assert_called()

    def test_post_prompts_json_success_and_reload(self):
        from channel.web.web_channel import ConfigJsonHandler

        new_prompts = {"$schema_version": "1.0", "custom_rule": "test"}
        payload = {"file": "prompts.json", "content": json.dumps(new_prompts)}

        mock_pm = MagicMock()
        with patch("channel.web.web_channel._require_auth", lambda: None), \
             patch("channel.web.web_channel.web.data", return_value=json.dumps(payload).encode("utf-8")), \
             patch("agent.prompt.manager.PromptManager.get_instance", return_value=mock_pm), \
             patch('builtins.open', mock_open()) as m_open, \
             _no_response_headers():
            raw = ConfigJsonHandler().POST()
            result = json.loads(raw)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["file"], "prompts.json")
        mock_pm.reload.assert_called_with(force=True)
        m_open.assert_called()


if __name__ == '__main__':
    unittest.main()
