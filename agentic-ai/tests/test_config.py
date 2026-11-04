import json
import unittest
from pathlib import Path

from agentic_ai.config import Config, load_config
from agentic_ai.documents import MemoryDocument


class ConfigurationTests(unittest.TestCase):
    def test_example_configuration_is_valid(self):
        path = Path(__file__).resolve().parents[1] / "config.example.json"
        config = load_config(path)
        self.assertEqual(config.model_for_role("planner"), "deepseek-r1-uncensored-v2:70b")
        self.assertEqual(config.model_for_role("coder"), "qwen2.5-coder:32b")
        self.assertEqual(
            config.backend_for_model("deepseek-r1-uncensored-v2:70b"), "llamacpp"
        )
        self.assertEqual(config.backend_for_model("qwen2.5-coder:32b"), "ollama")
        self.assertEqual(config.backend_for_model("deepseek-r1:70b"), "ollama")
        self.assertEqual(config.ollama.context_length, 16384)
        self.assertEqual(config.llamacpp.gpu_layers, 23)
        self.assertEqual(config.llamacpp.cache_type_k, "q8_0")
        self.assertEqual(config.llamacpp.cache_type_v, "q8_0")
        self.assertIn("compileall", config.commands["compile_all"].resolved_argv())
        self.assertFalse(config.web.enabled)
        self.assertEqual(config.web.allowed_domains, ())
        self.assertFalse(config.kimi.enabled)
        self.assertFalse(config.memory.enabled)

    def test_default_config_round_trip(self):
        original = Config.default()
        restored = Config.from_dict(json.loads(json.dumps(original.to_dict())))
        self.assertEqual(restored.to_dict(), original.to_dict())
    def test_nixos_configuration_is_local_and_private_by_default(self):
        path = Path(__file__).resolve().parents[1] / "config.nixos.example.json"
        config = load_config(path)
        self.assertTrue(config.memory.enabled)
        self.assertTrue(config.memory.dreaming_enabled)
        self.assertEqual(config.memory.classification, "private")
        self.assertFalse(config.kimi.enabled)
        self.assertFalse(config.dream.allow_hosted)
        self.assertEqual(config.execution.lock_path, "/run/agentic-ai/executor.lock")
    def test_seed_documents_are_valid(self):
        seeds = Path(__file__).resolve().parents[1] / "seeds"
        documents = [MemoryDocument.from_bytes(path.read_bytes()) for path in seeds.glob("*.md")]
        self.assertEqual(len(documents), 3)
        self.assertEqual(sum(item.metadata["kind"] == "skill" for item in documents), 2)


if __name__ == "__main__":
    unittest.main()
