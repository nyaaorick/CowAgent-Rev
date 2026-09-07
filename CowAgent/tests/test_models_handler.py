# encoding:utf-8
import json
import os
import sys
import types
import unittest
from unittest.mock import mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "web" not in sys.modules:
    web_stub = types.ModuleType("web")
    web_stub.HTTPError = type("HTTPError", (Exception,), {})
    web_stub.cookies = lambda: {}
    web_stub.header = lambda *args, **kwargs: None
    web_stub.data = lambda: b"{}"
    web_stub.input = lambda **kwargs: types.SimpleNamespace(**kwargs)
    web_stub.setcookie = lambda *args, **kwargs: None
    web_stub.seeother = lambda *args, **kwargs: Exception("seeother")
    web_stub.notfound = lambda *args, **kwargs: Exception("notfound")
    web_stub.badrequest = lambda *args, **kwargs: Exception("badrequest")
    web_stub.application = lambda *args, **kwargs: types.SimpleNamespace(wsgifunc=lambda: None)
    web_stub.httpserver = types.SimpleNamespace(
        LogMiddleware=type("LogMiddleware", (), {"log": lambda *args, **kwargs: None}),
        StaticMiddleware=lambda app: app,
        WSGIServer=lambda *args, **kwargs: types.SimpleNamespace(serve_forever=lambda: None),
    )
    sys.modules["web"] = web_stub


def _no_response_headers():
    """Neutralise web.header for a handler called outside a request.

    The stub above is skipped when the real web.py is already imported, which
    depends on what else ran first. Patching the name the handler resolves
    keeps these cases independent of that.
    """
    import channel.web.web_channel as web_channel

    return patch.object(web_channel.web, "header", lambda *args, **kwargs: None)


class TestModelsHandler(unittest.TestCase):
    def test_config_handler_exposes_reasoning_effort_metadata(self):
        from channel.web.web_channel import ConfigHandler
        from config import Config

        local_config = Config({
            "agent": True,
            "model": "deepseek-v4-flash",
            "bot_type": "deepseek",
            "enable_thinking": True,
            "reasoning_effort": "max",
        })

        with patch("channel.web.web_channel._require_auth", lambda: None), \
                _no_response_headers():
            with patch("channel.web.web_channel.conf", return_value=local_config):
                result = json.loads(ConfigHandler().GET())

        self.assertEqual(result["reasoning_effort"], "max")
        self.assertEqual(
            [item["value"] for item in result["providers"]["deepseek"]["reasoning"]["options"]],
            ["low", "high", "xhigh", "max"],
        )
        self.assertEqual(
            [item["value"] for item in result["providers"]["deepseek"]["reasoning_by_model"]["deepseek-v4-flash"]["options"]],
            ["low", "high", "xhigh", "max"],
        )
        self.assertEqual(
            [item["value"] for item in result["providers"]["zhipu"]["reasoning"]["options"]],
            ["low", "medium", "high", "xhigh", "max"],
        )
        self.assertEqual(
            [item["value"] for item in result["providers"]["claudeAPI"]["reasoning_by_model"]["claude-opus-5"]["options"]],
            ["low", "medium", "high", "xhigh", "max"],
        )
        self.assertEqual(
            [item["value"] for item in result["providers"]["claudeAPI"]["reasoning_by_model"]["claude-sonnet-4-6"]["options"]],
            ["low", "medium", "high", "max"],
        )
        self.assertEqual(
            [item["value"] for item in result["providers"]["dashscope"]["reasoning_by_model"]["qwen3.8-max"]["options"]],
            ["low", "medium", "xhigh"],
        )
        self.assertFalse(result["providers"]["dashscope"]["reasoning_by_model"]["qwen3.7-plus"]["supported"])
        self.assertEqual(
            [item["value"] for item in result["providers"]["moonshot"]["reasoning_by_model"]["kimi-k3"]["options"]],
            ["low", "high", "max"],
        )
        self.assertTrue(result["providers"]["moonshot"]["reasoning_by_model"]["kimi-k3"]["thinking_only"])
        self.assertFalse(result["providers"]["moonshot"]["reasoning_by_model"]["kimi-k2.7-code"]["supported"])
        self.assertFalse(result["providers"]["openai"]["reasoning"]["supported"])
        self.assertFalse(result["providers"]["gemini"]["reasoning"]["supported"])

    def test_reasoning_effort_is_editable_config_key(self):
        from channel.web.web_channel import ConfigHandler

        self.assertIn("reasoning_effort", ConfigHandler.EDITABLE_KEYS)
        self.assertIn("reasoning_effort_by_model", ConfigHandler.EDITABLE_KEYS)

    def test_config_save_rejects_non_dict_reasoning_effort_by_model(self):
        from channel.web.web_channel import ConfigHandler
        from config import Config

        local_config = Config({"reasoning_effort_by_model": {"deepseek:deepseek-v4-flash": "high"}})
        file_config = {"reasoning_effort_by_model": {"deepseek:deepseek-v4-flash": "high"}}
        payload = {"updates": {"reasoning_effort_by_model": "not-a-dict"}}

        with patch("channel.web.web_channel._require_auth", lambda: None), \
             patch("channel.web.web_channel.web.header"), \
             patch("channel.web.web_channel.web.data", return_value=json.dumps(payload).encode()), \
             patch("channel.web.web_channel.conf", return_value=local_config), \
             patch("channel.web.web_channel._read_config_file_for_write", return_value=file_config), \
             patch("builtins.open", mock_open()) as m:
            result = json.loads(ConfigHandler().POST())

        self.assertEqual(result["status"], "error")
        # Nothing written: the payload was rejected before the file write.
        m.assert_not_called()
        # The in-memory config is untouched too.
        self.assertEqual(local_config.get("reasoning_effort_by_model"), {"deepseek:deepseek-v4-flash": "high"})

    def test_config_handler_hides_deepseek_effort_for_non_v4_models(self):
        from channel.web.web_channel import ConfigHandler
        from config import Config

        local_config = Config({
            "agent": True,
            "model": "deepseek-chat",
            "bot_type": "deepseek",
            "enable_thinking": True,
            "reasoning_effort": "max",
        })

        with patch("channel.web.web_channel._require_auth", lambda: None), \
                _no_response_headers():
            with patch("channel.web.web_channel.conf", return_value=local_config):
                result = json.loads(ConfigHandler().GET())

        self.assertFalse(result["providers"]["deepseek"]["reasoning"]["supported"])



    def test_chat_capability_infers_provider_when_bot_type_empty(self):
        """A config with an empty bot_type but a recognizable model should
        resolve to the right provider (mirrors the runtime bridge inference),
        so onboarding isn't wrongly re-triggered for a working setup."""
        from channel.web.web_channel import ModelsHandler

        cap = ModelsHandler._chat_capability({
            "bot_type": "",
            "use_linkai": False,
            "model": "deepseek-v4-flash",
            "deepseek_api_key": "sk-test-placeholder",
        })
        self.assertEqual(cap["current_provider"], "deepseek")
        self.assertEqual(cap["current_model"], "deepseek-v4-flash")

    def test_chat_capability_empty_bot_type_use_linkai_stays_linkai(self):
        """use_linkai must still win when bot_type is empty (unchanged behavior)."""
        from channel.web.web_channel import ModelsHandler

        cap = ModelsHandler._chat_capability({
            "bot_type": "",
            "use_linkai": True,
            "model": "deepseek-v4-flash",
        })
        self.assertEqual(cap["current_provider"], "linkai")

    def test_chat_capability_unknown_model_stays_empty(self):
        """An unrecognizable model must not be force-mapped to a provider,
        so genuinely-unconfigured setups still surface onboarding."""
        from channel.web.web_channel import ModelsHandler

        cap = ModelsHandler._chat_capability({
            "bot_type": "",
            "use_linkai": False,
            "model": "some-unknown-model",
        })
        self.assertEqual(cap["current_provider"], "")

    def test_infer_provider_from_model_is_robust(self):
        from channel.web.web_channel import ModelsHandler

        cases = {
            "deepseek-v4-flash": "deepseek",
            "gemini-3-flash": "gemini",
            "glm-5": "zhipu",
            "claude-sonnet-5": "claudeAPI",
            "kimi-k3": "moonshot",
            "doubao-seed-2-pro": "doubao",
            "mimo-v2.5-pro": "mimo",
            "qwen38-max": "dashscope",
            "ernie-5": "qianfan",
            "minimax-m3": "minimax",
            "gpt-55": "openai",
            "abab6.5": "minimax",
            "wenxin": "qianfan",
        }
        for model, expected in cases.items():
            self.assertEqual(ModelsHandler._infer_provider_from_model(model), expected, model)
        # Bad / empty input never raises and yields "".
        for bad in ("", "   ", None, 123, "totally-unknown"):
            self.assertEqual(ModelsHandler._infer_provider_from_model(bad), "")






if __name__ == "__main__":
    unittest.main()
