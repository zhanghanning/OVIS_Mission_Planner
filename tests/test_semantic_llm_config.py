from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.core.config import get_settings
from app.services.semantic_llm_service import _invoke_deepseek, semantic_llm_provider_status


class SemanticLlmConfigTest(unittest.TestCase):
    def test_deepseek_key_auto_enables_provider(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "sk-deepseek-test",
            },
            clear=True,
        ):
            settings = get_settings()

        self.assertTrue(settings.semantic_llm_enabled)
        self.assertEqual(settings.semantic_llm_provider, "deepseek")
        self.assertEqual(settings.deepseek_api_base_url, "https://api.deepseek.com")
        self.assertEqual(settings.deepseek_api_model, "deepseek-v4-flash")
        self.assertEqual(settings.semantic_llm_base_url, "https://api.deepseek.com")
        self.assertEqual(settings.semantic_llm_model, "deepseek-v4-flash")
        self.assertEqual(settings.semantic_llm_api_key, "sk-deepseek-test")

    def test_default_deepseek_values_do_not_enable_provider_without_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = get_settings()

        self.assertFalse(settings.semantic_llm_enabled)
        self.assertEqual(settings.semantic_llm_provider, "disabled")
        self.assertEqual(settings.deepseek_api_base_url, "https://api.deepseek.com")
        self.assertEqual(settings.deepseek_api_model, "deepseek-v4-flash")

    def test_provider_status_reports_deepseek_configuration(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "sk-deepseek-test",
            },
            clear=True,
        ):
            status = semantic_llm_provider_status()

        self.assertTrue(status["enabled"])
        self.assertEqual(status["provider"], "deepseek")
        self.assertIn("deepseek", status["supported_providers"])
        self.assertTrue(status["deepseek"]["configured"])
        self.assertTrue(status["deepseek"]["enabled_by_current_provider"])
        self.assertEqual(status["deepseek"]["base_url"], "https://api.deepseek.com")
        self.assertEqual(status["deepseek"]["model"], "deepseek-v4-flash")
        self.assertTrue(status["openai_compatible"]["configured"])

    def test_deepseek_request_uses_json_mode(self) -> None:
        captured = {}

        class _MockResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"selected_target_set_ids":["category::teaching_building"],"selected_nav_point_ids":[],"reason":"ok"}'
                            }
                        }
                    ]
                }

        def _fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return _MockResponse()

        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "sk-deepseek-test",
            },
            clear=True,
        ):
            with patch("app.services.semantic_llm_service.requests.post", side_effect=_fake_post):
                result = _invoke_deepseek("system prompt", "user prompt")

        self.assertEqual(result["selected_target_set_ids"], ["category::teaching_building"])
        self.assertEqual(captured["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer sk-deepseek-test")
        self.assertEqual(captured["json"]["model"], "deepseek-v4-flash")
        self.assertEqual(captured["json"]["response_format"], {"type": "json_object"})
        self.assertEqual(captured["json"]["thinking"], {"type": "disabled"})
        self.assertFalse(captured["json"]["stream"])


if __name__ == "__main__":
    unittest.main()
