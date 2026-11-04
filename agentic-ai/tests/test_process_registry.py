from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from agentic_ai.config import LlamaCppConfig
from agentic_ai.llamacpp import LlamaCppBackend
from agentic_ai.process_registry import ExistingProcess, ProcessRegistry
from agentic_ai.storage import read_json


class ProcessRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.temporary.name) / "process.json"
        self.process = subprocess.Popen(["sleep", "30"], start_new_session=True)

    def tearDown(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=5)
        self.temporary.cleanup()

    def test_verified_orphan_can_be_adopted_and_stopped(self):
        registry = ProcessRegistry(self.registry_path)
        registry.capture(self.process, ["sleep", "30"], "test-model")
        record = registry.load_valid()
        self.assertIsNotNone(record)
        adopted = ExistingProcess(
            record["pid"], f"{record['uid']}:{record['start_ticks']}"
        )
        self.assertIsNone(adopted.poll())
        backend = LlamaCppBackend(
            LlamaCppConfig(model_name="test-model"), process_registry=registry
        )
        self.assertEqual(backend.ps()["models"][0]["name"], "test-model")
        backend.unload_model("test-model")
        self.process.wait(timeout=5)
        self.assertFalse(self.registry_path.exists())

    def test_pid_identity_mismatch_never_signals_process(self):
        registry = ProcessRegistry(self.registry_path)
        registry.capture(self.process, ["sleep", "30"], "test-model")
        record = read_json(self.registry_path)
        record["start_ticks"] = str(int(record["start_ticks"]) + 1)
        self.registry_path.write_text(json.dumps(record), encoding="utf-8")
        self.assertIsNone(registry.load_valid())
        self.assertIsNone(self.process.poll())
        self.assertFalse(self.registry_path.exists())


if __name__ == "__main__":
    unittest.main()
