"""Per-model routing across local and hosted inference providers."""

from __future__ import annotations

from typing import Any, Callable

from .config import Config, RoleConfig
from .errors import OllamaError
from .kimi import KimiClient
from .llamacpp import LlamaCppBackend
from .ollama import GenerationResult, OllamaClient
from .process_registry import ProcessRegistry


class ModelBackends:
    def __init__(
        self,
        config: Config,
        *,
        ollama_client: OllamaClient | None = None,
        llamacpp_backend: LlamaCppBackend | None = None,
        kimi_client: KimiClient | None = None,
    ):
        self.config = config
        self.ollama = ollama_client or OllamaClient(config.ollama)
        if llamacpp_backend is not None:
            self.llamacpp = llamacpp_backend
        elif config.llamacpp.enabled:
            self.llamacpp = LlamaCppBackend(
                config.llamacpp,
                process_registry=ProcessRegistry(config.execution.process_registry_path),
            )
        else:
            self.llamacpp = None
        if kimi_client is not None:
            self.kimi = kimi_client
        elif config.kimi.enabled:
            self.kimi = KimiClient(config.kimi)
        else:
            self.kimi = None

    def _backend_for(self, model: str):
        backend = self.config.backend_for_model(model)
        if backend == "llamacpp":
            if self.llamacpp is None:
                raise OllamaError(
                    f"Model {model} requires the llama.cpp backend, which is disabled"
                )
            return self.llamacpp
        if backend == "kimi":
            if self.kimi is None:
                raise OllamaError(f"Model {model} requires the Kimi backend, which is disabled")
            return self.kimi
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
        if self.kimi is not None:
            models.append(
                {
                    "name": self.config.kimi.model_name,
                    "model": self.config.kimi.model_name,
                    "backend": "kimi",
                    "hosted": True,
                }
            )
        return {"models": models}

    def ps(self) -> dict[str, Any]:
        # Hosted calls do not occupy local model memory and never appear here.
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
