import tempfile
import unittest
from pathlib import Path

from agentic_ai.config import Config, OllamaConfig
from agentic_ai.errors import ResidencyError
from agentic_ai.ollama import OllamaClient
from agentic_ai.residency import ResidencyManager
from agentic_ai.storage import RunStore, read_json
from fake_ollama import FakeOllamaServer


class ResidencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.fake = FakeOllamaServer().start()
        ollama = OllamaConfig(
            base_url=self.fake.url,
            load_timeout_seconds=2,
            request_timeout_seconds=2,
            dedicated_ollama=True,
            transport_retries=0,
        )
        self.config = Config(ollama=ollama)
        self.store = RunStore.create(
            self.temporary.name, "test", self.config.to_dict(), "run-residency"
        )
        self.client = OllamaClient(ollama)
        self.manager = ResidencyManager(
            self.client, self.store, self.config, poll_interval=0.01
        )

    def tearDown(self):
        self.fake.stop()
        self.temporary.cleanup()

    def assignments(self, task_id="task", role="coder", model="qwen2.5-coder:32b"):
        return [{"task_id": task_id, "role": role, "model": model, "attempt": 1}]

    def activate(self, model, wave=1):
        return self.manager.activate(
            model,
            assignments=self.assignments(model=model),
            required_models=["deepseek-r1:70b", "qwen2.5-coder:32b"],
            wave_id=wave,
            reason="test wave",
        )

    def test_explicit_repeated_switches_and_final_offload(self):
        first = self.activate("deepseek-r1:70b", 1)
        self.assertEqual(first["from_model"], None)
        self.assertEqual(self.fake.loaded, ["deepseek-r1:70b"])

        second = self.activate("qwen2.5-coder:32b", 2)
        self.assertEqual(second["from_model"], "deepseek-r1:70b")
        self.assertEqual(second["required_model_count"], 2)
        self.assertEqual(second["resident_model_limit"], 1)
        self.assertEqual(self.fake.loaded, ["qwen2.5-coder:32b"])
        self.assertLessEqual(self.fake.max_resident, 1)

        transitions = [event for event in self.fake.events if event["type"] in {"load", "unload"}]
        self.assertEqual(
            [(event["type"], event["model"]) for event in transitions[:3]],
            [
                ("load", "deepseek-r1:70b"),
                ("unload", "deepseek-r1:70b"),
                ("load", "qwen2.5-coder:32b"),
            ],
        )
        persisted = read_json(self.store.switch_path(2))
        self.assertTrue(persisted["load_verification"]["verified"])
        self.assertEqual(persisted["assignments"][0]["task_id"], "task")

        third = self.activate("deepseek-r1:70b", 3)
        self.assertEqual(third["from_model"], "qwen2.5-coder:32b")
        self.assertEqual(self.manager.offload_all(), [])
        self.assertEqual(self.fake.loaded, [])
        self.assertEqual(self.fake.violations, [])

    def test_chat_and_same_model_cache_reload(self):
        self.activate("qwen2.5-coder:32b")
        result = self.manager.chat(
            "qwen2.5-coder:32b",
            [{"role": "user", "content": "test"}],
            self.config.roles["coder"],
        )
        self.assertIn('"type": "final"', result.text)
        switches = self.store.load_run()["current_switch"]
        self.fake.expire("qwen2.5-coder:32b")
        self.manager.chat(
            "qwen2.5-coder:32b",
            [{"role": "user", "content": "after expiry"}],
            self.config.roles["coder"],
        )
        self.assertEqual(self.store.load_run()["current_switch"], switches)
        self.assertEqual(self.fake.loaded, ["qwen2.5-coder:32b"])
        self.assertEqual(self.store.load_run()["metrics"]["model_calls"], 2)

    def test_unexpected_external_model_is_not_unloaded_without_opt_in(self):
        config = Config(
            ollama=OllamaConfig(
                base_url=self.fake.url,
                load_timeout_seconds=1,
                dedicated_ollama=False,
                transport_retries=0,
            )
        )
        manager = ResidencyManager(
            OllamaClient(config.ollama), self.store, config, poll_interval=0.01
        )
        self.fake.set_loaded(["external-7b"])
        with self.assertRaisesRegex(ResidencyError, "external"):
            manager.activate(
                "deepseek-r1:70b",
                assignments=[],
                required_models=["deepseek-r1:70b"],
                wave_id=1,
                reason="test",
            )
        self.assertEqual(self.fake.loaded, ["external-7b"])

    def test_mid_wave_model_change_aborts_instead_of_implicit_switch(self):
        self.activate("deepseek-r1:70b")
        self.fake.set_loaded(["qwen2.5-coder:32b"])
        with self.assertRaisesRegex(ResidencyError, "during active wave"):
            self.manager.chat(
                "deepseek-r1:70b",
                [{"role": "user", "content": "test"}],
                self.config.roles["planner"],
            )


if __name__ == "__main__":
    unittest.main()
