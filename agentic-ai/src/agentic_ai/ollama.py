from __future__ import annotations

import http.client
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from .config import OllamaConfig, RoleConfig
from .errors import OllamaError


@dataclass
class GenerationResult:
    text: str
    done_reason: str | None
    prompt_eval_count: int = 0
    eval_count: int = 0
    total_duration_ns: int = 0


class OllamaClient:
    def __init__(self, config: OllamaConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self._inference_lock = threading.Lock()

    def _open(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        timeout: int,
    ):
        body = None
        headers = {"Accept": "application/json", "User-Agent": "local-agentic-ai/0.1"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path, data=body, headers=headers, method=method
        )
        last_error: Exception | None = None
        for attempt in range(self.config.transport_retries + 1):
            try:
                return urllib.request.urlopen(request, timeout=timeout)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:2000]
                exc.close()
                error = OllamaError(
                    f"Ollama HTTP {exc.code} for {path}: {detail or exc.reason}"
                )
                if exc.code not in {408, 429, 500, 502, 503, 504}:
                    raise error from exc
                last_error = error
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
                last_error = OllamaError(f"Cannot reach Ollama at {self.base_url}: {exc}")
            if attempt < self.config.transport_retries:
                time.sleep(0.25 * (2**attempt))
        raise OllamaError(str(last_error) if last_error else "Ollama request failed")

    def _json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        with self._open(method, path, payload, timeout or self.config.request_timeout_seconds) as response:
            raw = response.read()
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OllamaError(f"Invalid JSON from Ollama {path}: {raw[:500]!r}") from exc
        if not isinstance(value, dict):
            raise OllamaError(f"Unexpected Ollama response from {path}")
        if "error" in value:
            raise OllamaError(f"Ollama {path}: {value['error']}")
        return value

    def tags(self) -> dict[str, Any]:
        return self._json("GET", "/api/tags", timeout=30)

    def ps(self) -> dict[str, Any]:
        return self._json("GET", "/api/ps", timeout=30)

    def model_names(self, snapshot: dict[str, Any] | None = None) -> list[str]:
        value = snapshot if snapshot is not None else self.ps()
        models = value.get("models", [])
        if not isinstance(models, list):
            raise OllamaError("Ollama /api/ps returned a non-array models field")
        names = []
        for model in models:
            if not isinstance(model, dict):
                continue
            name = model.get("name") or model.get("model")
            if isinstance(name, str) and name:
                names.append(name)
        return sorted(set(names))

    def load_model(self, model: str) -> dict[str, Any]:
        return self._json(
            "POST",
            "/api/generate",
            {
                "model": model,
                "prompt": "",
                "stream": False,
                "keep_alive": self.config.keep_alive,
                "options": {"num_ctx": self.config.context_length, "num_predict": 1},
            },
            timeout=self.config.load_timeout_seconds,
        )

    def unload_model(self, model: str) -> dict[str, Any]:
        return self._json(
            "POST",
            "/api/generate",
            {"model": model, "keep_alive": 0, "stream": False},
            timeout=self.config.load_timeout_seconds,
        )

    @staticmethod
    def _response_lines(response) -> Iterator[dict[str, Any]]:
        while True:
            try:
                line = response.readline()
            except (http.client.IncompleteRead, TimeoutError, socket.timeout) as exc:
                raise OllamaError(f"Ollama stream interrupted: {exc}") from exc
            if not line:
                return
            try:
                value = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise OllamaError(f"Invalid streamed Ollama JSON: {line[:500]!r}") from exc
            if not isinstance(value, dict):
                raise OllamaError("Unexpected streamed Ollama value")
            yield value

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        role: RoleConfig,
        *,
        json_output: bool = True,
        on_text: Callable[[str], None] | None = None,
    ) -> GenerationResult:
        if not self._inference_lock.acquire(blocking=False):
            raise OllamaError("Overlapping inference is forbidden by the one-model scheduler")
        try:
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": True,
                "keep_alive": self.config.keep_alive,
                "options": {
                    "num_ctx": self.config.context_length,
                    "num_predict": role.num_predict,
                    "temperature": role.temperature,
                },
            }
            if json_output:
                payload["format"] = "json"
            response = self._open(
                "POST", "/api/chat", payload, self.config.request_timeout_seconds
            )
            parts: list[str] = []
            thinking_open = False
            done_reason: str | None = None
            prompt_eval_count = 0
            eval_count = 0
            total_duration_ns = 0

            def emit(text: str) -> None:
                if not text:
                    return
                parts.append(text)
                if on_text is not None:
                    on_text(text)

            with response:
                for value in self._response_lines(response):
                    if "error" in value:
                        raise OllamaError(f"Ollama chat: {value['error']}")
                    message = value.get("message") or {}
                    thinking = message.get("thinking") or ""
                    content = message.get("content") or ""
                    if thinking:
                        if not thinking_open:
                            emit("<think>\n")
                            thinking_open = True
                        emit(thinking)
                    if content:
                        if thinking_open:
                            emit("\n</think>\n")
                            thinking_open = False
                        emit(content)
                    if value.get("done"):
                        done_reason = value.get("done_reason")
                        prompt_eval_count = value.get("prompt_eval_count") or 0
                        eval_count = value.get("eval_count") or 0
                        total_duration_ns = value.get("total_duration") or 0
            return GenerationResult(
                "".join(parts),
                done_reason,
                prompt_eval_count,
                eval_count,
                total_duration_ns,
            )
        finally:
            self._inference_lock.release()
