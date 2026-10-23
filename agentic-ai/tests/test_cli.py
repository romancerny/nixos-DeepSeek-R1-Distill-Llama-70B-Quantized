import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from agentic_ai.cli import main
from agentic_ai.config import Config, OllamaConfig
from agentic_ai.storage import RunStore
from fake_ollama import FakeOllamaServer
from test_end_to_end import WorkflowResponder


class CliTests(unittest.TestCase):
    def test_doctor_run_status_report_and_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            responder = WorkflowResponder()
            with FakeOllamaServer(responder) as fake:
                config = Config(
                    ollama=OllamaConfig(
                        base_url=fake.url,
                        load_timeout_seconds=2,
                        request_timeout_seconds=3,
                        dedicated_ollama=True,
                        transport_retries=0,
                    )
                )
                config_path = Path(temporary) / "config.json"
                config_path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
                state_dir = str(Path(temporary) / "state")
                with contextlib.redirect_stdout(io.StringIO()):
                    doctor = main([
                        "doctor", "--config", str(config_path), "--state-dir", state_dir, "--json"
                    ])
                self.assertEqual(doctor, 0)
                self.assertEqual(fake.loaded, [])

                with contextlib.redirect_stdout(io.StringIO()):
                    started = main([
                        "run", "--config", str(config_path), "--state-dir", state_dir,
                        "--goal", "Build a calculator through the CLI", "--run-id", "run-cli",
                        "--stop-after-plan",
                    ])
                self.assertEqual(started, 0)
                status_output = io.StringIO()
                with contextlib.redirect_stdout(status_output):
                    status = main(["status", "run-cli", "--state-dir", state_dir, "--json"])
                self.assertEqual(status, 0)
                self.assertEqual(json.loads(status_output.getvalue())["status"], "paused_after_plan")

                with contextlib.redirect_stdout(io.StringIO()):
                    resumed = main(["resume", "run-cli", "--state-dir", state_dir])
                self.assertEqual(resumed, 0)
                store = RunStore.open(state_dir, "run-cli")
                self.assertEqual(store.load_run()["status"], "succeeded")
                report_output = io.StringIO()
                with contextlib.redirect_stdout(report_output):
                    reported = main(["report", "run-cli", "--state-dir", state_dir])
                self.assertEqual(reported, 0)
                self.assertIn("Agentic run run-cli", report_output.getvalue())
                self.assertEqual(fake.loaded, [])
                self.assertEqual(fake.violations, [])


if __name__ == "__main__":
    unittest.main()
