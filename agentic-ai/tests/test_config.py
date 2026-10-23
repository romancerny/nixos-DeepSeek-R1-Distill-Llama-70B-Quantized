import json
import unittest
from pathlib import Path

from agentic_ai.config import Config, load_config


class ConfigurationTests(unittest.TestCase):
    def test_example_configuration_is_valid(self):
        path = Path(__file__).resolve().parents[1] / "config.example.json"
        config = load_config(path)
        self.assertEqual(config.model_for_role("planner"), "deepseek-r1:70b")
        self.assertEqual(config.model_for_role("coder"), "qwen2.5-coder:32b")
        self.assertEqual(config.ollama.context_length, 16384)
        self.assertIn("compileall", config.commands["compile_all"].resolved_argv())
        self.assertTrue(config.web.enabled)

    def test_default_config_round_trip(self):
        original = Config.default()
        restored = Config.from_dict(json.loads(json.dumps(original.to_dict())))
        self.assertEqual(restored.to_dict(), original.to_dict())


if __name__ == "__main__":
    unittest.main()
