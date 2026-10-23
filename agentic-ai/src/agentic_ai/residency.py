from __future__ import annotations

import time
from typing import Any, Callable

from .backends import ModelBackends
from .config import Config
from .errors import ResidencyError
from .ollama import GenerationResult
from .storage import RunStore, atomic_write_json, utc_now


class ResidencyManager:
    """Enforces one verified resident model at quiescent scheduling barriers."""

    def __init__(
        self,
        client: ModelBackends,
        store: RunStore,
        config: Config,
        *,
        poll_interval: float = 0.2,
    ):
        self.client = client
        self.store = store
        self.config = config
        self.poll_interval = poll_interval
        self.active_model: str | None = None
        self.owned_models = {role.model for role in config.roles.values()}

    def _names(self) -> list[str]:
        return self.client.model_names()

    def _wait(self, predicate: Callable[[], bool], description: str) -> None:
        deadline = time.monotonic() + self.config.ollama.load_timeout_seconds
        while True:
            if predicate():
                return
            if time.monotonic() >= deadline:
                raise ResidencyError(f"Timed out waiting for {description}; /api/ps={self._names()}")
            time.sleep(self.poll_interval)

    def _increment_metric(self, name: str, amount: int = 1) -> None:
        def mutate(run: dict[str, Any]) -> None:
            run.setdefault("metrics", {})[name] = run.setdefault("metrics", {}).get(name, 0) + amount

        self.store.update_run(mutate)

    def _unload(self, model: str) -> list[str]:
        self.client.unload_model(model)
        self._wait(lambda: model not in self._names(), f"unload of {model}")
        self._increment_metric("model_unloads")
        self.store.append_event("model_unloaded", model=model, resident_models=self._names())
        return self._names()

    def _load(self, model: str) -> None:
        self.client.load_model(model)
        self._wait(lambda: self._names() == [model], f"exclusive load of {model}")
        self._increment_metric("model_loads")
        self.store.append_event("model_loaded", model=model, resident_models=self._names())

    def _check_external_models(self, names: list[str], target: str) -> None:
        if self.config.ollama.dedicated_ollama:
            return
        unexpected = [
            name for name in names if name != target and name not in self.owned_models
        ]
        if unexpected:
            raise ResidencyError(
                "Unexpected external Ollama models are resident; refusing to unload them: "
                + ", ".join(unexpected)
            )

    def activate(
        self,
        model: str,
        *,
        assignments: list[dict[str, Any]],
        required_models: list[str],
        wave_id: int,
        reason: str,
    ) -> dict[str, Any] | None:
        """Switch at a quiescent barrier; return None when already exclusively loaded."""
        before_snapshot = self.client.ps()
        before = self.client.model_names(before_snapshot)
        if self.active_model == model and before == [model]:
            return None
        self._check_external_models(before, model)
        from_model = self.active_model
        if from_model is None and len(before) == 1:
            from_model = before[0]

        unload_checks: list[dict[str, Any]] = []
        for resident in before:
            if resident != model:
                remaining = self._unload(resident)
                unload_checks.append({"model": resident, "resident_models": remaining})
        self._wait(
            lambda: all(name == model for name in self._names()),
            "all non-target models to be absent",
        )
        current = self._names()
        reloaded_same_model = self.active_model == model and not current
        if model not in current:
            self._load(model)
        after_snapshot = self.client.ps()
        after = self.client.model_names(after_snapshot)
        if after != [model]:
            raise ResidencyError(f"Expected only {model} after activation, found {after}")
        previous_active = self.active_model
        self.active_model = model

        if previous_active == model and from_model == model and not unload_checks:
            self.store.append_event("model_adopted", model=model, wave_id=wave_id)
            return None
        if reloaded_same_model:
            self.store.append_event("model_reloaded", model=model, wave_id=wave_id)
            return None

        run = self.store.load_run()
        switch_id = int(run.get("current_switch", 0)) + 1
        record = {
            "schema_version": 1,
            "switch_id": switch_id,
            "timestamp": utc_now(),
            "reason": reason,
            "quiescent_wave_id": wave_id,
            "from_model": from_model,
            "to_model": model,
            "active_model": model,
            "required_models": sorted(set(required_models)),
            "required_model_count": len(set(required_models)),
            "resident_model_limit": 1,
            "assignments": assignments,
            "before_ps": before_snapshot,
            "after_ps": after_snapshot,
            "unload_verification": unload_checks,
            "load_verification": {"model": model, "resident_models": after, "verified": True},
        }
        atomic_write_json(self.store.switch_path(switch_id), record)

        def mutate(current_run: dict[str, Any]) -> None:
            current_run["current_switch"] = switch_id
            metrics = current_run.setdefault("metrics", {})
            metrics["model_switches"] = metrics.get("model_switches", 0) + 1

        self.store.update_run(mutate)
        self.store.append_event(
            "model_switch_verified",
            switch_id=switch_id,
            from_model=from_model,
            to_model=model,
            assignments=assignments,
        )
        return record

    def ensure_for_inference(self, model: str) -> None:
        if self.active_model != model:
            raise ResidencyError(
                f"Agent requested {model}, but the quiescent wave activated {self.active_model}"
            )
        names = self._names()
        if names == [model]:
            return
        if not names:
            self._load(model)
            self.store.append_event("model_reloaded_after_cache_expiry", model=model)
            return
        raise ResidencyError(
            f"Residency changed during active wave; refusing implicit switch from {names} to {model}"
        )

    def chat(self, model: str, messages: list[dict[str, str]], role, **kwargs) -> GenerationResult:
        self.ensure_for_inference(model)
        result = self.client.chat(model, messages, role, **kwargs)
        names = self._names()
        if names != [model]:
            raise ResidencyError(f"Model residency was not exclusive after inference: {names}")
        self._increment_metric("model_calls")
        if result.prompt_eval_count:
            self._increment_metric("prompt_tokens", result.prompt_eval_count)
        if result.eval_count:
            self._increment_metric("completion_tokens", result.eval_count)
        return result

    def offload_all(self, *, reason: str = "run exit") -> list[str]:
        names = self._names()
        self._check_external_models(names, target="")
        for name in names:
            self._unload(name)
        self.active_model = None
        remaining = self._names()
        self.store.append_event("final_offload", reason=reason, resident_models=remaining)
        return remaining
