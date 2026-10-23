import tempfile
import unittest
from pathlib import Path

from agentic_ai.agent import AgentRuntime
from agentic_ai.config import Config, OllamaConfig
from agentic_ai.ollama import OllamaClient
from agentic_ai.plan import Plan
from agentic_ai.residency import ResidencyManager
from agentic_ai.storage import RunStore
from agentic_ai.tools import ToolRuntime
from fake_ollama import FakeOllamaServer


def coding_plan():
    return Plan.from_dict(
        {
            "goal": "Build a calculator",
            "tasks": [
                {
                    "id": "implement",
                    "kind": "implement",
                    "role": "coder",
                    "instruction": "Write calculator.py",
                    "write_scope": ["calculator.py"],
                }
            ],
            "acceptance": [
                {
                    "id": "compiles",
                    "description": "Source compiles",
                    "type": "command",
                    "command_id": "compile_all",
                }
            ],
        },
        Config.default(),
    )


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.config = Config.default()
        self.store = RunStore.create(
            self.temporary.name, "test", self.config.to_dict(), "run-tools"
        )
        self.task = coding_plan().tasks[0]
        self.tools = ToolRuntime(self.store, self.config, self.task)

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, tool, arguments, call_id="call-1"):
        return self.tools.execute(
            {"type": "tool_call", "call_id": call_id, "tool": tool, "arguments": arguments}
        )

    def test_scoped_write_read_and_compile(self):
        result = self.call("write_file", {"path": "calculator.py", "content": "VALUE = 42\n"})
        self.assertTrue(result["ok"])
        read = self.call("read_file", {"path": "workspace/calculator.py"}, "call-2")
        self.assertEqual(read["content"], "VALUE = 42\n")
        command = self.call("run_command", {"command_id": "compile_all"}, "call-3")
        self.assertTrue(command["ok"], command)

    def test_scope_escape_and_command_injection_are_rejected(self):
        outside = self.call("write_file", {"path": "other.py", "content": "bad"})
        self.assertFalse(outside["ok"])
        traversal = self.call("write_file", {"path": "../calculator.py", "content": "bad"})
        self.assertFalse(traversal["ok"])
        injection = self.call(
            "run_command", {"command_id": "compile_all", "args": ["; rm -rf /"]}
        )
        self.assertFalse(injection["ok"])

    def test_symlink_escape_is_rejected(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (self.store.workspace_dir / "link").symlink_to(outside, target_is_directory=True)
        scoped_task = coding_plan().tasks[0]
        scoped_task.write_scope = ["link/"]
        tools = ToolRuntime(self.store, self.config, scoped_task)
        result = tools.execute(
            {"type": "tool_call", "call_id": "x", "tool": "write_file", "arguments": {"path": "link/a.py", "content": "bad"}}
        )
        self.assertFalse(result["ok"])

    def test_web_is_disabled_by_default(self):
        researcher = coding_plan().tasks[0]
        researcher.role = "researcher"
        tools = ToolRuntime(self.store, self.config, researcher)
        result = tools.execute(
            {"type": "tool_call", "call_id": "w", "tool": "web_search", "arguments": {"query": "test"}}
        )
        self.assertFalse(result["ok"])


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.responses = []
        self.fake = FakeOllamaServer(self.respond).start()
        ollama = OllamaConfig(
            base_url=self.fake.url,
            load_timeout_seconds=2,
            request_timeout_seconds=2,
            dedicated_ollama=True,
            transport_retries=0,
        )
        self.config = Config(ollama=ollama)
        self.store = RunStore.create(
            self.temporary.name, "test", self.config.to_dict(), "run-agent"
        )
        self.manager = ResidencyManager(
            OllamaClient(ollama), self.store, self.config, poll_interval=0.01
        )
        self.plan = coding_plan()
        self.task = self.plan.tasks[0]
        self.agent = AgentRuntime(self.store, self.config, self.manager)

    def tearDown(self):
        self.fake.stop()
        self.temporary.cleanup()

    def respond(self, model, messages):
        if self.responses:
            return self.responses.pop(0)
        return {"type": "final", "summary": "done", "outputs": []}

    def activate(self):
        self.manager.activate(
            self.task.model,
            assignments=[{"task_id": self.task.id, "role": self.task.role, "model": self.task.model, "attempt": 1}],
            required_models=self.plan.required_models,
            wave_id=1,
            reason="agent test",
        )

    def test_multi_turn_write_command_and_final(self):
        self.responses = [
            {"type": "tool_call", "call_id": "write-1", "tool": "write_file", "arguments": {"path": "calculator.py", "content": "def add(a, b):\n    return a + b\n"}},
            {"type": "tool_call", "call_id": "compile-1", "tool": "run_command", "arguments": {"command_id": "compile_all"}},
            {"type": "final", "summary": "implemented and compiled", "outputs": ["workspace/calculator.py"]},
        ]
        self.activate()
        self.agent.start(self.task, self.plan)
        self.assertEqual(self.agent.step(self.task), "running")
        self.assertEqual(self.agent.step(self.task), "running")
        self.assertEqual(self.agent.step(self.task), "completed")
        self.assertIn("def add", (self.store.workspace_dir / "calculator.py").read_text())
        state = self.store.load_run()["task_states"]["implement"]
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual(state["turns"], 3)
        self.assertEqual(self.store.load_run()["metrics"]["tool_calls"], 2)

    def test_interrupted_atomic_write_is_replayed_without_inference(self):
        self.agent.start(self.task, self.plan)
        context = self.store.load_context("implement")
        call = {
            "type": "tool_call",
            "call_id": "recover-write",
            "tool": "write_file",
            "arguments": {"path": "calculator.py", "content": "RECOVERED = True\n"},
        }
        attempt_dir = self.store.attempt_dir("implement", 1, 1)
        context["pending_tool"] = {"call": call, "attempt_dir": str(attempt_dir)}
        self.store.save_context("implement", context)
        calls_before = len(self.fake.calls)
        self.assertEqual(self.agent.step(self.task), "running")
        self.assertEqual(len(self.fake.calls), calls_before)
        self.assertEqual(
            (self.store.workspace_dir / "calculator.py").read_text(), "RECOVERED = True\n"
        )

    def test_protocol_retry_exhaustion_fails_task(self):
        self.responses = ["bad one", "bad two", "bad three"]
        self.activate()
        self.agent.start(self.task, self.plan)
        self.assertEqual(self.agent.step(self.task), "running")
        self.assertEqual(self.agent.step(self.task), "running")
        self.assertEqual(self.agent.step(self.task), "failed")
        state = self.store.load_run()["task_states"]["implement"]
        self.assertEqual(state["status"], "failed")
        self.assertIn("JSON", state["error"])

    def test_malformed_json_gets_bounded_feedback_then_succeeds(self):
        self.responses = ["not json", {"type": "final", "summary": "recovered", "outputs": []}]
        self.activate()
        self.agent.start(self.task, self.plan)
        self.assertEqual(self.agent.step(self.task), "running")
        context = self.store.load_context("implement")
        self.assertEqual(context["protocol_errors"], 1)
        self.assertEqual(self.agent.step(self.task), "completed")


if __name__ == "__main__":
    unittest.main()
