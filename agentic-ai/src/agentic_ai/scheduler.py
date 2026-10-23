from __future__ import annotations

from typing import Any, Callable

from .agent import AgentRuntime
from .config import Config
from .errors import AgenticError
from .plan import Plan, Task, task_order
from .residency import ResidencyManager
from .storage import RunStore, atomic_write_json, utc_now


class Scheduler:
    def __init__(
        self,
        store: RunStore,
        config: Config,
        residency: ResidencyManager,
        agent: AgentRuntime,
        *,
        stop_check: Callable[[], None] | None = None,
    ):
        self.store = store
        self.config = config
        self.residency = residency
        self.agent = agent
        self.stop_check = stop_check or (lambda: None)

    def _state(self, task_id: str) -> dict[str, Any]:
        return self.store.load_run().get("task_states", {}).get(
            task_id, {"status": "pending", "attempt": 0}
        )

    def _dependencies_succeeded(self, task: Task, run: dict[str, Any]) -> bool:
        states = run.get("task_states", {})
        return all(
            states.get(dependency, {}).get("status") == "succeeded"
            for dependency in task.depends_on
        )

    def _eligible(self, plan: Plan, model: str | None = None) -> list[Task]:
        run = self.store.load_run()
        states = run.get("task_states", {})
        tasks = []
        for task in plan.tasks:
            if model is not None and task.model != model:
                continue
            status = states.get(task.id, {}).get("status", "pending")
            if status in {"pending", "running"} and self._dependencies_succeeded(task, run):
                tasks.append(task)
        return task_order(tasks, plan.ranks)

    def _mark_blocked(self, plan: Plan) -> None:
        run = self.store.load_run()
        states = run.setdefault("task_states", {})
        changed = False
        for task in task_order(plan.tasks, plan.ranks):
            state = states.get(task.id, {})
            if state.get("status", "pending") != "pending":
                continue
            dependencies = [states.get(dep, {}).get("status") for dep in task.depends_on]
            if any(status in {"failed", "blocked"} for status in dependencies):
                state.update({"status": "blocked", "error": "A dependency failed or was blocked"})
                states[task.id] = state
                changed = True
        if changed:
            self.store.save_run(run)

    def _dependency_summaries(self, task: Task) -> dict[str, Any]:
        run = self.store.load_run()
        states = run.get("task_states", {})
        return {
            dependency: {
                "status": states.get(dependency, {}).get("status"),
                "summary": states.get(dependency, {}).get("summary"),
                "outputs": states.get(dependency, {}).get("outputs", []),
            }
            for dependency in task.depends_on
        }

    def _assignment(self, task: Task) -> dict[str, Any]:
        state = self._state(task.id)
        return {
            "task_id": task.id,
            "role": task.role,
            "model": task.model,
            "attempt": state.get("attempt", 0),
        }

    def _start_if_needed(
        self,
        task: Task,
        plan: Plan,
        *,
        feedback: str | None,
        dependency_summaries: dict[str, Any] | None,
    ) -> None:
        status = self._state(task.id).get("status", "pending")
        if status == "pending":
            self.agent.start(
                task,
                plan,
                dependency_summaries=dependency_summaries or self._dependency_summaries(task),
                feedback=feedback,
            )
        elif status == "running":
            self.agent.recover(task)
        else:
            raise AgenticError(f"Cannot start task {task.id} with status {status}")

    def _execute_wave(
        self,
        plan: Plan,
        model: str,
        candidates: list[Task],
        *,
        dynamic: bool,
        feedback: dict[str, str] | None = None,
        special_summaries: dict[str, Any] | None = None,
    ) -> None:
        if not candidates:
            return
        feedback = feedback or {}
        for task in candidates:
            self._start_if_needed(
                task,
                plan,
                feedback=feedback.get(task.id),
                dependency_summaries=(special_summaries if special_summaries is not None else None),
            )
        run = self.store.load_run()
        wave_id = int(run.get("current_wave", 0)) + 1
        if wave_id > self.config.limits.max_waves:
            raise AgenticError("Run exceeded max_waves")
        assignments = [self._assignment(task) for task in candidates]
        wave = {
            "schema_version": 1,
            "wave_id": wave_id,
            "status": "opening",
            "opened_at": utc_now(),
            "closed_at": None,
            "active_model": model,
            "required_models": plan.required_models,
            "required_model_count": len(plan.required_models),
            "resident_model_limit": 1,
            "assignments": assignments,
            "steps": 0,
            "close_reason": None,
        }
        atomic_write_json(self.store.wave_path(wave_id), wave)
        run["current_wave"] = wave_id
        run["status"] = "running"
        self.store.save_run(run)
        try:
            self.residency.activate(
                model,
                assignments=assignments,
                required_models=plan.required_models,
                wave_id=wave_id,
                reason="topological ready-set scheduling",
            )
            wave["status"] = "active"
            atomic_write_json(self.store.wave_path(wave_id), wave)
            queue = list(candidates)
            active_ids = {task.id for task in candidates}
            while queue:
                self.stop_check()
                task = queue.pop(0)
                outcome = self.agent.step(task)
                wave["steps"] += 1
                if outcome == "running":
                    queue.append(task)
                if dynamic:
                    newly_ready = [
                        candidate
                        for candidate in self._eligible(plan, model)
                        if candidate.id not in active_ids
                    ]
                    for candidate in newly_ready:
                        self._start_if_needed(
                            candidate,
                            plan,
                            feedback=None,
                            dependency_summaries=None,
                        )
                        active_ids.add(candidate.id)
                        queue.append(candidate)
                        wave["assignments"].append(self._assignment(candidate))
                atomic_write_json(self.store.wave_path(wave_id), wave)
            wave["status"] = "closed"
            wave["close_reason"] = "resident-model ready set drained"
            wave["closed_at"] = utc_now()
            atomic_write_json(self.store.wave_path(wave_id), wave)
            self.store.append_event(
                "wave_closed", wave_id=wave_id, model=model, steps=wave["steps"]
            )
        except Exception as exc:
            wave["status"] = "interrupted"
            wave["close_reason"] = str(exc)
            wave["closed_at"] = utc_now()
            atomic_write_json(self.store.wave_path(wave_id), wave)
            raise

    def execute_plan(self, plan: Plan) -> bool:
        while True:
            self._mark_blocked(plan)
            run = self.store.load_run()
            states = run.get("task_states", {})
            if all(
                states.get(task.id, {}).get("status") == "succeeded"
                for task in plan.tasks
            ):
                return True
            eligible = self._eligible(plan)
            if not eligible:
                return False
            selected = eligible[0]
            candidates = self._eligible(plan, selected.model)
            self._execute_wave(plan, selected.model, candidates, dynamic=True)

    def execute_special(
        self,
        plan: Plan,
        task: Task,
        *,
        feedback: str,
        summaries: dict[str, Any],
    ) -> str:
        self._execute_wave(
            plan,
            task.model,
            [task],
            dynamic=False,
            feedback={task.id: feedback},
            special_summaries=summaries,
        )
        return self._state(task.id).get("status", "failed")
