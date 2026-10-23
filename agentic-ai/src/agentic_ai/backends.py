"""Per-model routing across inference backends (Ollama and llama.cpp).

ModelBackends presents the OllamaClient-shaped surface that the residency
manager, CLI doctor/offload, and runner expect, and dispatches each call to
the backend that serves the requested model. Combined ps()/tags() snapshots
keep the one-resident-model invariant verifiable across both backends.
"""

from __future__ import annotations

from typing import Any, Callable

from .config import Config, RoleConfig
from .errors import OllamaError
from .llamacpp import LlamaCppBackend
from .ollama import GenerationResult, OllamaClient


class ModelBackends:
    def __init__(
        self,
        config: Config,
        *,
        ollama_client: OllamaClient | None = None,
        llamacpp_backend: LlamaCppBackend | None = None,
    ):
        self.config = config
        self.ollama = ollama_client or OllamaClient(config.ollama)
        if llamacpp_backend is not None:
            self.llamacpp = llamacpp_backend
        elif config.llamacpp.enabled:
            self.llamacpp = LlamaCppBackend(config.llamacpp)
        else:
            self.llamacpp = None

    def _backend_for(self, model: str):
        if self.config.backend_for_model(model) == "llamacpp":
            if self.llamacpp is None:
                raise OllamaError(
                    f"Model {model} requires the llama.cpp backend, which is disabled"
                )
            return self.llamacpp
        return self.ollama

    def tags(self) -> dict[str, Any]:
        snapshot = self.ollama.tags()
        models = list(snapshot.get("models", []))
        if self.llamacpp is not None and self.llamacpp.resolved_model_path().is_file():
            models.append(
                {
                    "name": self.config.llamacpp.model_name,
                    "model": self.config.llamacpp.model_name,
                    "backend": "llamacpp",
                }
            )
        return {"models": models}

    def ps(self) -> dict[str, Any]:
        models = list(self.ollama.ps().get("models", []))
        if self.llamacpp is not None:
            models.extend(self.llamacpp.ps().get("models", []))
        return {"models": models}

    def model_names(self, snapshot: dict[str, Any] | None = None) -> list[str]:
        value = snapshot if snapshot is not None else self.ps()
        models = value.get("models", [])
        if not isinstance(models, list):
            raise OllamaError("ps returned a non-array models field")
        names = []
        for model in models:
            if not isinstance(model, dict):
                continue
            name = model.get("name") or model.get("model")
            if isinstance(name, str) and name:
                names.append(name)
        return sorted(set(names))

    def load_model(self, model: str) -> dict[str, Any]:
        return self._backend_for(model).load_model(model)

    def unload_model(self, model: str) -> dict[str, Any]:
        return self._backend_for(model).unload_model(model)

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        role: RoleConfig,
        *,
        json_output: bool = True,
        on_text: Callable[[str], None] | None = None,
    ) -> GenerationResult:
        return self._backend_for(model).chat(
            model, messages, role, json_output=json_output, on_text=on_text
        )
