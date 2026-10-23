import tempfile
import unittest

from agentic_ai.config import OllamaConfig
from agentic_ai.ollama import OllamaClient
from agentic_ai.runner import ProjectRunner
from agentic_ai.storage import RunStore
from fake_ollama import FakeOllamaServer, ollama_only_config
from test_end_to_end import WorkflowResponder


class FlakyResponder:
    def __init__(self):
        self.inner = WorkflowResponder()
        self.fail_once = True

    def __call__(self, model, messages):
        task_id = self.inner.task_id(messages)
        if task_id == "research-logic" and self.fail_once:
            self.fail_once = False
            raise RuntimeError("simulated inference transport failure")
        return self.inner(model, messages)


class ResumeTests(unittest.TestCase):
    def _config(self, url):
        return ollama_only_config(
            OllamaConfig(
                base_url=url,
                load_timeout_seconds=2,
                request_timeout_seconds=3,
                dedicated_ollama=True,
                offload_on_exit=True,
                transport_retries=0,
            )
        )

    def test_pause_after_plan_then_resume_without_replanning(self):
        with tempfile.TemporaryDirectory() as temporary:
            responder = WorkflowResponder()
            with FakeOllamaServer(responder) as fake:
                config = self._config(fake.url)
                store = RunStore.create(temporary, "Build a calculator", config.to_dict(), "run-pause")
                first = ProjectRunner(store, config, poll_interval=0.01).execute(stop_after_plan=True)
                self.assertEqual(first["status"], "paused_after_plan")
                self.assertEqual(first["plan_revision"], 1)
                self.assertEqual(responder.task_sequence, [])
                second = ProjectRunner(store, config, poll_interval=0.01).execute()
                self.assertEqual(second["status"], "succeeded", second.get("error"))
                planner_calls = [
                    call for call in fake.calls
                    if any("USER GOAL:" in message.get("content", "") for message in call["messages"])
                ]
                self.assertEqual(len(planner_calls), 1)
                self.assertEqual(fake.loaded, [])

    def test_transport_interruption_resumes_without_repeating_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            responder = FlakyResponder()
            with FakeOllamaServer(responder) as fake:
                config = self._config(fake.url)
                store = RunStore.create(temporary, "Build a calculator", config.to_dict(), "run-resume")
                first = ProjectRunner(store, config, poll_interval=0.01).execute()
                self.assertEqual(first["status"], "interrupted", first.get("error"))
                self.assertEqual(first["plan_revision"], 1)
                self.assertTrue((store.attempt_dir("research-logic", 1, 1) / "result.json").is_file())

                second = ProjectRunner(store, config, poll_interval=0.01).execute()
                self.assertEqual(second["status"], "succeeded", second.get("error"))
                planner_calls = [
                    call for call in fake.calls
                    if any("USER GOAL:" in message.get("content", "") for message in call["messages"])
                ]
                self.assertEqual(len(planner_calls), 1)
                self.assertEqual(responder.inner.counts["research-logic"], 2)
                self.assertEqual(fake.loaded, [])
                self.assertEqual(fake.violations, [])


if __name__ == "__main__":
    unittest.main()
