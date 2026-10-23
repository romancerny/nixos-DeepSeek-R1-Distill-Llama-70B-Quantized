from __future__ import annotations

import signal
import traceback
from typing import Any

from .agent import AgentRuntime
from .backends import ModelBackends
from .config import Config
from .context import compact_json
from .errors import (
    AgenticError,
    OllamaError,
    PlanValidationError,
    ResidencyError,
    RunInterrupted,
)
from .evaluation import Evaluator
from .ollama import OllamaClient
from .plan import Plan, Task
from .planner import Planner
from .reporting import generate_report
from .residency import ResidencyManager
from .scheduler import Scheduler
from .storage import RunStore, atomic_write_json, read_json, utc_now


class ProjectRunner:
    def __init__(
        self,
        store: RunStore,
        config: Config,
        *,
        client: OllamaClient | ModelBackends | None = None,
        poll_interval: float = 0.2,
    ):
        self.store = store
        self.config = config
        if client is None:
            self.client = ModelBackends(config)
        elif isinstance(client, ModelBackends):
            self.client = client
        else:
            # A bare OllamaClient (used by tests) serves the Ollama models.
            self.client = ModelBackends(config, ollama_client=client)
        self.residency = ResidencyManager(
            self.client, store, config, poll_interval=poll_interval
        )
        self.agent = AgentRuntime(store, config, self.residency)
        self.planner = Planner(store, config, self.residency)
        self.scheduler = Scheduler(
            store, config, self.residency, self.agent, stop_check=self._check_stop
        )
        self.evaluator = Evaluator(store, config)
        self._stop_requested = False
        self._previous_handlers: dict[int, Any] = {}

    def _check_stop(self) -> None:
        if self._stop_requested:
            raise RunInterrupted("Stop requested; state is durable and the run can be resumed")

    def _handle_signal(self, signum, frame) -> None:
        self._stop_requested = True

    def _install_handlers(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handle_signal)

    def _restore_handlers(self) -> None:
        for signum, handler in self._previous_handlers.items():
            signal.signal(signum, handler)
        self._previous_handlers.clear()

    def _bootstrap(self) -> Plan:
        run = self.store.load_run()
        wave_id = int(run.get("current_wave", 0)) + 1
        model = self.config.model_for_role("planner")
        assignments = [
            {"task_id": "bootstrap-plan", "role": "planner", "model": model, "attempt": 1}
        ]
        wave = {
            "schema_version": 1,
            "wave_id": wave_id,
            "status": "opening",
            "opened_at": utc_now(),
            "closed_at": None,
            "active_model": model,
            "required_models": [model],
            "required_model_count": 1,
            "resident_model_limit": 1,
            "assignments": assignments,
            "steps": 0,
            "close_reason": None,
        }
        atomic_write_json(self.store.wave_path(wave_id), wave)
        run["current_wave"] = wave_id
        run["status"] = "planning"
        self.store.save_run(run)
        calls_before = run.get("metrics", {}).get("model_calls", 0)
        try:
            self.residency.activate(
                model,
                assignments=assignments,
                required_models=[model],
                wave_id=wave_id,
                reason="bootstrap executable project planning",
            )
            wave["status"] = "active"
            atomic_write_json(self.store.wave_path(wave_id), wave)
            plan = self.planner.create_plan(self.store.load_run()["goal"])
            wave["steps"] = (
                self.store.load_run().get("metrics", {}).get("model_calls", 0)
                - calls_before
            )
            wave["status"] = "closed"
            wave["close_reason"] = "valid plan persisted"
            wave["closed_at"] = utc_now()
            atomic_write_json(self.store.wave_path(wave_id), wave)
            return plan
        except Exception as exc:
            wave["status"] = "interrupted"
            wave["close_reason"] = str(exc)
            wave["closed_at"] = utc_now()
            atomic_write_json(self.store.wave_path(wave_id), wave)
            raise

    def _load_plan(self) -> Plan:
        revision = self.store.load_run()["plan_revision"]
        return Plan.from_dict(read_json(self.store.plan_path(revision)), self.config)

    def _validate_completed_outputs(self, plan: Plan) -> None:
        run = self.store.load_run()
        states = run.setdefault("task_states", {})
        changed = False
        for task in plan.tasks:
            state = states.get(task.id, {})
            if state.get("status") != "succeeded":
                continue
            records = state.get("outputs", [])
            if any(not self.store.validate_file_record(record) for record in records):
                state.update(
                    {
                        "status": "pending",
                        "error": "A completed output changed or disappeared; task requeued",
                        "summary": None,
                        "outputs": [],
                    }
                )
                changed = True
        if changed:
            self.store.save_run(run)

    def _all_summaries(self, plan: Plan) -> dict[str, Any]:
        states = self.store.load_run().get("task_states", {})
        return {
            task.id: {
                "status": states.get(task.id, {}).get("status"),
                "summary": states.get(task.id, {}).get("summary"),
                "outputs": states.get(task.id, {}).get("outputs", []),
                "error": states.get(task.id, {}).get("error"),
            }
            for task in plan.tasks
        }

    def _review(
        self, plan: Plan, evaluation: dict[str, Any], cycle: int
    ) -> dict[str, Any]:
        task_id = f"review-cycle-{cycle}"
        state = self.store.load_run().get("task_states", {}).get(task_id, {})
        if state.get("status") == "succeeded":
            return state.get("final", {"verdict": "fail", "summary": "Missing review final"})
        if state.get("status") == "failed":
            return {"verdict": "fail", "summary": state.get("error") or "Reviewer failed"}
        task = Task(
            id=task_id,
            kind="review",
            role="reviewer",
            model=self.config.model_for_role("reviewer"),
            instruction=(
                "Review the complete project against the original goal and unchanged acceptance "
                "criteria. Inspect the specification, implementation, tests, and evaluation evidence. "
                "Return a pass verdict only if deterministic and substantive requirements are met."
            ),
            depends_on=[item.id for item in plan.tasks],
            max_turns=self.config.roles["reviewer"].max_turns,
        )
        feedback = (
            "Latest deterministic evaluation and external runtime feedback:\n"
            + compact_json(evaluation, self.config.limits.max_tool_result_chars)
        )
        status = self.scheduler.execute_special(
            plan, task, feedback=feedback, summaries=self._all_summaries(plan)
        )
        if status != "succeeded":
            state = self.store.load_run().get("task_states", {}).get(task_id, {})
            return {"verdict": "fail", "summary": state.get("error") or "Reviewer failed"}
        final = self.store.load_run()["task_states"][task_id].get("final", {})
        return final

    def _reflect(
        self,
        plan: Plan,
        evaluation: dict[str, Any],
        review: dict[str, Any],
        cycle: int,
    ) -> Plan:
        last_error = ""
        for retry in range(self.config.limits.max_protocol_retries + 2):
            suffix = "" if retry == 0 else f"-retry-{retry}"
            task_id = f"reflect-cycle-{cycle}{suffix}"
            task = Task(
                id=task_id,
                kind="repair",
                role="reflector",
                model=self.config.model_for_role("reflector"),
                instruction=(
                    "Create concrete repair tasks for the identified root causes. Reference only "
                    "existing plan task ids as dependencies. If a repair writes a file owned by an "
                    "earlier task, depend on that earlier task. Add QA repair/retest tasks as needed."
                ),
                depends_on=[item.id for item in plan.tasks],
                max_turns=self.config.roles["reflector"].max_turns,
            )
            feedback = (
                "Reflection evidence. Produce a valid repair_patch; do not change acceptance criteria.\n"
                + compact_json(
                    {"evaluation": evaluation, "review": review, "previous_patch_error": last_error},
                    self.config.limits.max_tool_result_chars,
                )
            )
            status = self.scheduler.execute_special(
                plan, task, feedback=feedback, summaries=self._all_summaries(plan)
            )
            if status != "succeeded":
                state = self.store.load_run()["task_states"].get(task_id, {})
                last_error = state.get("error") or "Reflector task failed"
                continue
            final = self.store.load_run()["task_states"][task_id]["final"]
            try:
                repaired = plan.with_repairs(final["repair_patch"], self.config)
            except (PlanValidationError, KeyError) as exc:
                last_error = str(exc)
                self.store.append_event(
                    "repair_patch_rejected", task_id=task_id, error=last_error
                )
                continue
            atomic_write_json(self.store.plan_path(repaired.revision), repaired.to_dict())

            def mutate(run: dict[str, Any]) -> None:
                run["plan_revision"] = repaired.revision
                states = run.setdefault("task_states", {})
                existing_ids = {item.id for item in plan.tasks}
                for item in repaired.tasks:
                    if item.id not in existing_ids:
                        states[item.id] = {
                            "status": "pending",
                            "attempt": 0,
                            "turns": 0,
                            "summary": None,
                            "outputs": [],
                            "error": None,
                        }

            self.store.update_run(mutate)
            self.store.append_event(
                "repair_plan_created",
                revision=repaired.revision,
                root_cause=repaired.root_cause,
                new_tasks=[item.id for item in repaired.tasks if item.id not in {old.id for old in plan.tasks}],
            )
            return repaired
        raise PlanValidationError(f"Reflection could not produce a valid repair plan: {last_error}")

    def _workflow(self, plan: Plan) -> dict[str, Any]:
        while True:
            self._check_stop()
            execution_passed = self.scheduler.execute_plan(plan)
            run = self.store.load_run()
            evaluation_id = int(run.get("evaluation_count", 0)) + 1
            run["evaluation_count"] = evaluation_id
            self.store.save_run(run)
            evaluation = self.evaluator.evaluate(
                plan, evaluation_id, execution_passed=execution_passed
            )
            cycle = int(self.store.load_run().get("repair_cycle", 0))
            if not execution_passed:
                self.store.update_run(
                    status="failed",
                    error="One or more plan tasks failed; see task states and evaluation evidence",
                )
                return self.store.load_run()
            review = self._review(plan, evaluation, cycle)
            review_passed = review.get("verdict") == "pass"
            if evaluation["passed"] and review_passed:
                self.store.update_run(status="succeeded", error=None)
                self.store.append_event("run_succeeded", evaluation_id=evaluation_id)
                return self.store.load_run()
            if cycle >= self.config.limits.max_repair_cycles:
                self.store.update_run(
                    status="failed",
                    error={
                        "message": "Acceptance/review still failing after bounded repair cycles",
                        "evaluation_id": evaluation_id,
                        "review": review,
                    },
                )
                return self.store.load_run()
            cycle += 1
            self.store.update_run(repair_cycle=cycle)
            plan = self._reflect(plan, evaluation, review, cycle)

    def execute(self, *, stop_after_plan: bool = False) -> dict[str, Any]:
        with self.store.executor_lock(), self.store.run_lock():
            run = self.store.load_run()
            if run["status"] in {"succeeded", "failed"}:
                return run
            self._stop_requested = False
            self._install_handlers()
            try:
                self.store.repair_event_log()
                if run.get("plan_revision", 0) == 0:
                    plan = self._bootstrap()
                    if stop_after_plan:
                        self.store.update_run(status="paused_after_plan", stop_after_plan=True)
                        return self.store.load_run()
                else:
                    plan = self._load_plan()
                    self._validate_completed_outputs(plan)
                self.store.update_run(status="running", stop_after_plan=False, error=None)
                return self._workflow(plan)
            except RunInterrupted as exc:
                self.store.update_run(status="interrupted", error=str(exc))
                return self.store.load_run()
            except (OllamaError, ResidencyError, OSError) as exc:
                self.store.update_run(
                    status="interrupted",
                    error={
                        "type": exc.__class__.__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                )
                self.store.append_event("run_operational_interruption", error=str(exc))
                return self.store.load_run()
            except Exception as exc:
                self.store.update_run(
                    status="failed",
                    error={
                        "type": exc.__class__.__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                )
                self.store.append_event("run_operational_failure", error=str(exc))
                return self.store.load_run()
            finally:
                try:
                    if self.config.ollama.offload_on_exit:
                        self.residency.offload_all(reason="runner exit")
                except Exception as exc:
                    current = self.store.load_run()
                    if current["status"] == "succeeded":
                        self.store.update_run(
                            status="failed", error=f"Final model offload failed: {exc}"
                        )
                    else:
                        self.store.append_event("final_offload_failed", error=str(exc))
                self._restore_handlers()
                generate_report(self.store)
