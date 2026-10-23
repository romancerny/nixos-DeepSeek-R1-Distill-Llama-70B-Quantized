from __future__ import annotations

from typing import Any

from .config import Config
from .errors import StorageError
from .plan import Plan, Task
from .storage import RunStore, atomic_write_json, utc_now
from .tools import ToolRuntime


class Evaluator:
    def __init__(self, store: RunStore, config: Config):
        self.store = store
        self.config = config

    def evaluate(self, plan: Plan, evaluation_id: int, *, execution_passed: bool) -> dict[str, Any]:
        results = []
        for criterion in plan.acceptance:
            result: dict[str, Any] = {
                "id": criterion.id,
                "description": criterion.description,
                "type": criterion.type,
                "required": criterion.required,
            }
            if criterion.type == "file":
                try:
                    record = self.store.file_record(criterion.path or "")
                    result.update({"passed": True, "evidence": record})
                except StorageError as exc:
                    result.update({"passed": False, "error": str(exc)})
            else:
                task = Task(
                    id=f"acceptance-{evaluation_id}-{criterion.id}",
                    kind="test",
                    role="qa",
                    model=self.config.model_for_role("qa"),
                    instruction=criterion.description,
                )
                call = {
                    "type": "tool_call",
                    "call_id": f"acceptance-{evaluation_id}-{criterion.id}",
                    "tool": "run_command",
                    "arguments": {"command_id": criterion.command_id},
                }
                command_result = ToolRuntime(self.store, self.config, task).execute(call)
                result.update(command_result)
                result["passed"] = bool(command_result.get("ok"))

                def mutate(run: dict[str, Any]) -> None:
                    metrics = run.setdefault("metrics", {})
                    metrics["tool_calls"] = metrics.get("tool_calls", 0) + 1

                self.store.update_run(mutate)
            results.append(result)
        required_passed = all(
            result["passed"] for result in results if result["required"]
        )
        evaluation = {
            "schema_version": 1,
            "evaluation_id": evaluation_id,
            "timestamp": utc_now(),
            "plan_revision": plan.revision,
            "execution_passed": execution_passed,
            "passed": bool(execution_passed and required_passed),
            "results": results,
        }
        atomic_write_json(
            self.store.run_dir / "evaluations" / f"evaluation-{evaluation_id:04d}.json",
            evaluation,
        )
        self.store.append_event(
            "acceptance_evaluated",
            evaluation_id=evaluation_id,
            passed=evaluation["passed"],
            execution_passed=execution_passed,
        )
        return evaluation
