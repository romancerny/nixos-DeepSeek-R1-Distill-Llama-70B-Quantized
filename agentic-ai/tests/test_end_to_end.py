import json
import tempfile
import unittest
from pathlib import Path

from agentic_ai.config import Config, OllamaConfig
from agentic_ai.ollama import OllamaClient
from agentic_ai.runner import ProjectRunner
from agentic_ai.storage import RunStore, read_json
from fake_ollama import FakeOllamaServer


PLAN = {
    "schema_version": 1,
    "revision": 1,
    "goal": "ignored; runner preserves the user brief",
    "tasks": [
        {
            "id": "research-logic",
            "kind": "research",
            "role": "researcher",
            "instruction": "Research arithmetic semantics",
            "artifact_outputs": ["research/logic.md"],
        },
        {
            "id": "research-validation",
            "kind": "research",
            "role": "researcher",
            "instruction": "Research validation criteria",
            "artifact_outputs": ["research/validation.md"],
        },
        {
            "id": "architecture-spec",
            "kind": "specification",
            "role": "architect",
            "instruction": "Write the calculator specification",
            "depends_on": ["research-logic", "research-validation"],
            "inputs": ["artifacts/research/logic.md", "artifacts/research/validation.md"],
            "artifact_outputs": ["architecture_spec.md"],
        },
        {
            "id": "implement-core",
            "kind": "implement",
            "role": "coder",
            "instruction": "Implement calculator.py",
            "depends_on": ["architecture-spec"],
            "inputs": ["artifacts/architecture_spec.md"],
            "write_scope": ["calculator.py"],
        },
        {
            "id": "implement-utils",
            "kind": "implement",
            "role": "coder",
            "instruction": "Implement utils.py",
            "depends_on": ["architecture-spec"],
            "inputs": ["artifacts/architecture_spec.md"],
            "write_scope": ["utils.py"],
        },
        {
            "id": "write-tests",
            "kind": "test",
            "role": "qa",
            "instruction": "Write specification-based unit tests",
            "depends_on": ["architecture-spec"],
            "inputs": ["artifacts/architecture_spec.md"],
            "write_scope": ["tests/"],
        },
    ],
    "acceptance": [
        {
            "id": "tests-pass",
            "description": "All generated unit tests pass",
            "type": "command",
            "command_id": "unit_tests",
            "required": True,
        },
        {
            "id": "calculator-exists",
            "description": "Calculator implementation exists",
            "type": "file",
            "path": "workspace/calculator.py",
            "required": True,
        },
    ],
}


TEST_SOURCE = """import unittest
from calculator import add
from utils import double

class GeneratedTests(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

    def test_double(self):
        self.assertEqual(double(4), 8)

if __name__ == "__main__":
    unittest.main()
"""


class WorkflowResponder:
    def __init__(self):
        self.counts = {}
        self.task_sequence = []

    @staticmethod
    def task_id(messages):
        user = messages[1]["content"]
        if '"current_task"' not in user:
            return None
        section = user.split('"current_task":', 1)[1].split(
            '"unchanged_acceptance_criteria":', 1
        )[0]
        for task_id in [
            "research-logic",
            "research-validation",
            "architecture-spec",
            "implement-core",
            "implement-utils",
            "write-tests",
            "review-cycle-0",
            "reflect-cycle-1",
            "repair-core",
            "review-cycle-1",
        ]:
            if f'"id": "{task_id}"' in section:
                return task_id
        return None

    def __call__(self, model, messages):
        task_id = self.task_id(messages)
        if task_id is None:
            return "<think>check dependencies and acceptance</think>\n" + json.dumps(PLAN)
        self.task_sequence.append(task_id)
        count = self.counts.get(task_id, 0) + 1
        self.counts[task_id] = count
        if task_id == "review-cycle-0":
            return {"type": "final", "summary": "Addition uses the wrong operator", "outputs": [], "verdict": "fail"}
        if task_id == "review-cycle-1":
            return {"type": "final", "summary": "All requirements and tests now pass", "outputs": [], "verdict": "pass"}
        if task_id == "reflect-cycle-1":
            return {
                "type": "final",
                "summary": "Create a scoped implementation repair",
                "outputs": [],
                "repair_patch": {
                    "root_cause": "calculator.add used subtraction instead of addition",
                    "tasks": [
                        {
                            "id": "repair-core",
                            "kind": "repair",
                            "role": "coder",
                            "instruction": "Correct calculator.add and rerun the tests",
                            "depends_on": ["implement-core", "write-tests"],
                            "inputs": ["artifacts/architecture_spec.md"],
                            "write_scope": ["calculator.py"],
                        }
                    ],
                },
            }
        if count == 2:
            outputs = {
                "research-logic": ["artifacts/research/logic.md"],
                "research-validation": ["artifacts/research/validation.md"],
                "architecture-spec": ["artifacts/architecture_spec.md"],
                "implement-core": ["workspace/calculator.py"],
                "implement-utils": ["workspace/utils.py"],
                "write-tests": ["workspace/tests/test_generated.py"],
                "repair-core": ["workspace/calculator.py"],
            }[task_id]
            return {"type": "final", "summary": f"Completed {task_id}", "outputs": outputs}
        if count != 1:
            raise AssertionError(f"Unexpected extra turn for {task_id}: {count}")
        if task_id == "research-logic":
            return {"type": "tool_call", "call_id": "write-logic", "tool": "write_artifact", "arguments": {"path": "research/logic.md", "content": "# Logic\nAddition must return the sum.\n"}}
        if task_id == "research-validation":
            return {"type": "tool_call", "call_id": "write-validation", "tool": "write_artifact", "arguments": {"path": "research/validation.md", "content": "# Validation\nTest known arithmetic examples.\n"}}
        if task_id == "architecture-spec":
            return {"type": "tool_call", "call_id": "write-spec", "tool": "write_artifact", "arguments": {"path": "architecture_spec.md", "content": "# Specification\n`add(a,b)` returns a+b. `double(x)` returns 2*x. Tests must cover both.\n"}}
        if task_id == "implement-core":
            return {"type": "tool_call", "call_id": "write-core", "tool": "write_file", "arguments": {"path": "calculator.py", "content": "def add(a, b):\n    return a - b  # initial scripted defect\n"}}
        if task_id == "implement-utils":
            return {"type": "tool_call", "call_id": "write-utils", "tool": "write_file", "arguments": {"path": "utils.py", "content": "def double(value):\n    return value * 2\n"}}
        if task_id == "write-tests":
            return {"type": "tool_call", "call_id": "write-tests", "tool": "write_file", "arguments": {"path": "tests/test_generated.py", "content": TEST_SOURCE}}
        if task_id == "repair-core":
            return {"type": "tool_call", "call_id": "repair-core-write", "tool": "write_file", "arguments": {"path": "calculator.py", "content": "def add(a, b):\n    return a + b\n"}}
        raise AssertionError(task_id)


class EndToEndTests(unittest.TestCase):
    def test_complete_multi_agent_reflection_and_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            responder = WorkflowResponder()
            with FakeOllamaServer(responder) as fake:
                ollama = OllamaConfig(
                    base_url=fake.url,
                    load_timeout_seconds=2,
                    request_timeout_seconds=3,
                    dedicated_ollama=True,
                    offload_on_exit=True,
                    transport_retries=0,
                )
                config = Config(ollama=ollama)
                store = RunStore.create(
                    temporary,
                    "Build a correct calculator with independent tests",
                    config.to_dict(),
                    "run-e2e",
                )
                runner = ProjectRunner(
                    store,
                    config,
                    client=OllamaClient(ollama),
                    poll_interval=0.01,
                )
                result = runner.execute()
                if result["status"] != "succeeded":
                    self.fail(json.dumps(result.get("error"), indent=2))

                self.assertEqual(result["plan_revision"], 2)
                self.assertEqual(result["repair_cycle"], 1)
                self.assertIn("return a + b", (store.workspace_dir / "calculator.py").read_text())
                self.assertEqual(fake.loaded, [])
                self.assertEqual(fake.violations, [])
                self.assertLessEqual(fake.max_resident, 1)

                waves = [read_json(path) for path in sorted((store.run_dir / "waves").glob("*.json"))]
                self.assertGreaterEqual(len(waves), 7)
                research_wave = waves[1]
                self.assertEqual(research_wave["active_model"], "deepseek-r1:70b")
                self.assertGreaterEqual(len(research_wave["assignments"]), 2)
                self.assertEqual(research_wave["required_model_count"], 2)
                coding_wave = waves[2]
                self.assertEqual(coding_wave["active_model"], "qwen2.5-coder:32b")
                self.assertGreaterEqual(len(coding_wave["assignments"]), 3)
                for wave in waves:
                    self.assertEqual(wave["resident_model_limit"], 1)
                    self.assertIn("required_model_count", wave)
                    self.assertTrue(wave["assignments"])

                switches = [read_json(path) for path in sorted((store.run_dir / "switches").glob("*.json"))]
                transitions = [(item["from_model"], item["to_model"]) for item in switches]
                self.assertIn(("deepseek-r1:70b", "qwen2.5-coder:32b"), transitions)
                self.assertIn(("qwen2.5-coder:32b", "deepseek-r1:70b"), transitions)
                self.assertGreaterEqual(len(switches), 5)

                research_calls = [task for task in responder.task_sequence if task.startswith("research-")]
                self.assertEqual(research_calls[:2], ["research-logic", "research-validation"])
                self.assertEqual(responder.counts["repair-core"], 2)

                evaluations = [read_json(path) for path in sorted((store.run_dir / "evaluations").glob("*.json"))]
                self.assertEqual(len(evaluations), 2)
                self.assertFalse(evaluations[0]["passed"])
                self.assertTrue(evaluations[1]["passed"])
                report = read_json(store.run_dir / "report.json")
                self.assertTrue(report["acceptance"]["passed"])
                self.assertEqual(report["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
