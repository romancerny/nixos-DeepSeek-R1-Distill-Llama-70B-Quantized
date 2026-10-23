import tempfile
import unittest
from pathlib import Path

from agentic_ai.config import Config
from agentic_ai.errors import PlanValidationError
from agentic_ai.plan import Plan, scopes_overlap


def plan_dict():
    return {
        "schema_version": 1,
        "revision": 1,
        "goal": "Build a reliable calculator",
        "tasks": [
            {
                "id": "research-api",
                "kind": "research",
                "role": "researcher",
                "instruction": "Research the API",
                "artifact_outputs": ["research/api.md"],
            },
            {
                "id": "spec",
                "kind": "specification",
                "role": "architect",
                "instruction": "Specify the API",
                "depends_on": ["research-api"],
                "inputs": ["artifacts/research/api.md"],
                "artifact_outputs": ["architecture_spec.md"],
            },
            {
                "id": "implement",
                "kind": "implement",
                "role": "coder",
                "instruction": "Implement the module",
                "depends_on": ["spec"],
                "inputs": ["artifacts/architecture_spec.md"],
                "write_scope": ["calculator.py"],
            },
            {
                "id": "tests",
                "kind": "test",
                "role": "qa",
                "instruction": "Write unit tests",
                "depends_on": ["spec"],
                "write_scope": ["tests/"],
            },
        ],
        "acceptance": [
            {
                "id": "tests-pass",
                "description": "Unit tests pass",
                "type": "command",
                "command_id": "unit_tests",
            },
            {
                "id": "implementation-exists",
                "description": "Implementation exists",
                "type": "file",
                "path": "workspace/calculator.py",
            },
        ],
    }


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.config = Config.default()

    def test_valid_plan_resolves_models_and_ranks(self):
        plan = Plan.from_dict(plan_dict(), self.config)
        self.assertEqual(plan.required_models, ["deepseek-r1:70b", "qwen2.5-coder:32b"])
        self.assertEqual(plan.ranks["research-api"], 0)
        self.assertEqual(plan.ranks["implement"], 2)
        self.assertEqual(plan.task("tests").model, "qwen2.5-coder:32b")

    def test_cycle_is_rejected(self):
        raw = plan_dict()
        raw["tasks"][0]["depends_on"] = ["implement"]
        with self.assertRaisesRegex(PlanValidationError, "cycle"):
            Plan.from_dict(raw, self.config)

    def test_unknown_dependency_is_rejected(self):
        raw = plan_dict()
        raw["tasks"][0]["depends_on"] = ["missing"]
        with self.assertRaisesRegex(PlanValidationError, "unknown dependency"):
            Plan.from_dict(raw, self.config)

    def test_overlapping_concurrent_scopes_are_rejected(self):
        raw = plan_dict()
        first = raw["tasks"][2]
        second = dict(first)
        second["id"] = "implement-other"
        second["depends_on"] = ["spec"]
        raw["tasks"].append(second)
        with self.assertRaisesRegex(PlanValidationError, "overlapping write scopes"):
            Plan.from_dict(raw, self.config)

    def test_dependency_allows_sequential_scope_reuse(self):
        raw = plan_dict()
        repair = dict(raw["tasks"][2])
        repair["id"] = "repair-implementation"
        repair["kind"] = "repair"
        repair["depends_on"] = ["implement"]
        raw["tasks"].append(repair)
        plan = Plan.from_dict(raw, self.config)
        self.assertIn("repair-implementation", plan.ranks)

    def test_model_override_is_rejected(self):
        raw = plan_dict()
        raw["tasks"][0]["model"] = "some-other-model"
        with self.assertRaisesRegex(PlanValidationError, "cannot override"):
            Plan.from_dict(raw, self.config)

    def test_paths_and_artifact_ownership_are_validated(self):
        raw = plan_dict()
        raw["tasks"][2]["write_scope"] = ["../outside.py"]
        with self.assertRaises(PlanValidationError):
            Plan.from_dict(raw, self.config)
        raw = plan_dict()
        raw["tasks"][1]["artifact_outputs"] = ["research/api.md"]
        with self.assertRaisesRegex(PlanValidationError, "multiple owners"):
            Plan.from_dict(raw, self.config)

    def test_repair_preserves_acceptance_and_adds_revision(self):
        plan = Plan.from_dict(plan_dict(), self.config)
        repaired = plan.with_repairs(
            {
                "root_cause": "Incorrect operator",
                "tasks": [
                    {
                        "id": "repair-calculator",
                        "kind": "repair",
                        "role": "coder",
                        "instruction": "Fix the operator",
                        "depends_on": ["implement"],
                        "write_scope": ["calculator.py"],
                    }
                ],
            },
            self.config,
        )
        self.assertEqual(repaired.revision, 2)
        self.assertEqual(repaired.acceptance[0].command_id, "unit_tests")
        self.assertEqual(repaired.root_cause, "Incorrect operator")

    def test_scope_overlap_rules(self):
        self.assertTrue(scopes_overlap("src/", "src/module.py"))
        self.assertTrue(scopes_overlap("src/a/", "src/"))
        self.assertFalse(scopes_overlap("src/a/", "src/ab/"))


if __name__ == "__main__":
    unittest.main()
