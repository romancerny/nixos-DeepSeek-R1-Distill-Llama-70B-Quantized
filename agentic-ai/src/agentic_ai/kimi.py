from __future__ import annotations

import http.client
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Iterator

from . import __version__
from .config import KimiConfig, RoleConfig
from .errors import KimiError
from .ollama import GenerationResult


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


class KimiClient:
    """Small OpenAI-compatible streaming client for the Kimi Coding endpoint."""

    def __init__(self, config: KimiConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self._inference_lock = threading.Lock()
        self._opener = urllib.request.build_opener(_NoRedirect)

    def credential_available(self) -> bool:
        return bool(os.environ.get(self.config.api_key_env))

    def ps(self) -> dict[str, Any]:
        return {"models": []}

    def load_model(self, model: str) -> dict[str, Any]:
        self._require_model(model)
        return {"model": model, "provider": "kimi", "hosted": True}

    def unload_model(self, model: str) -> dict[str, Any]:
        self._require_model(model)
        return {"model": model, "provider": "kimi", "hosted": True}

    def _require_model(self, model: str) -> None:
        if not self.config.enabled or model != self.config.model_name:
            raise KimiError(f"Kimi backend does not serve model {model}", category="configuration")

    def _open(self, payload: dict[str, Any]):
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise KimiError(
                f"Kimi credential is missing from {self.config.api_key_env}",
                category="authentication",
            )
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": f"agentic-ai/{__version__}",
            },
            method="POST",
        )
        last_error: KimiError | None = None
        for attempt in range(self.config.transport_retries + 1):
            try:
                return self._opener.open(request, timeout=self.config.request_timeout_seconds)
            except urllib.error.HTTPError as exc:
                detail = exc.read(4096).decode("utf-8", errors="replace")
                exc.close()
                category = (
                    "authentication" if exc.code in {401, 403}
                    else "rate_limit" if exc.code == 429
                    else "invalid_request" if 400 <= exc.code < 500
                    else "server"
                )
                error = KimiError(
                    f"Kimi HTTP {exc.code} ({category}): {detail or exc.reason}",
                    category=category,
                )
                if exc.code not in {408, 429, 500, 502, 503, 504}:
                    raise error from exc
                last_error = error
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
                # The server may have received the request. Repeating it could
                # duplicate quota use, so surface an explicit ambiguous outcome.
                raise KimiError(
                    f"Kimi request outcome is unknown; reconcile before retrying: {exc}",
                    category="ambiguous",
                    ambiguous=True,
                ) from exc
            if attempt < self.config.transport_retries:
                time.sleep(0.25 * (2**attempt))
        raise last_error or KimiError("Kimi request failed")

    def _sse_events(self, response) -> Iterator[dict[str, Any]]:
        total = 0
        while True:
            raw_line = response.readline(1_000_001)
            if len(raw_line) > 1_000_000:
                raise KimiError("Kimi SSE line exceeds one MiB", category="protocol")
            total += len(raw_line)
            if total > self.config.max_response_bytes:
                raise KimiError("Kimi response exceeds configured byte cap", category="protocol")
            if not raw_line:
                return
            try:
                line = raw_line.decode("utf-8").strip()
            except UnicodeDecodeError as exc:
                raise KimiError("Kimi stream is not UTF-8", category="protocol") from exc
            if not line or line.startswith(":") or not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if data == "[DONE]":
                return
            try:
                value = json.loads(data)
            except json.JSONDecodeError as exc:
                raise KimiError("Kimi stream contains invalid JSON", category="protocol") from exc
            if not isinstance(value, dict):
                raise KimiError("Unexpected Kimi stream value", category="protocol")
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
        self._require_model(model)
        if not self._inference_lock.acquire(blocking=False):
            raise KimiError("Overlapping Kimi inference is forbidden", category="concurrency")
        try:
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": True,
                "stream_options": {"include_usage": True},
                "max_tokens": role.num_predict,
            }
            if json_output:
                payload["response_format"] = {"type": "json_object"}
            response = self._open(payload)
            parts: list[str] = []
            thinking_open = False
            done_reason = None
            prompt_tokens = 0
            completion_tokens = 0
            started = time.monotonic_ns()

            def emit(text: str) -> None:
                if not text:
                    return
                parts.append(text)
                if on_text is not None:
                    on_text(text)

            try:
                with response:
                    for value in self._sse_events(response):
                        if "error" in value:
                            error = value["error"]
                            detail = error.get("message") if isinstance(error, dict) else str(error)
                            raise KimiError(f"Kimi chat: {detail}", category="server")
                        usage = value.get("usage")
                        if isinstance(usage, dict):
                            prompt_tokens = usage.get("prompt_tokens") or prompt_tokens
                            completion_tokens = usage.get("completion_tokens") or completion_tokens
                        choices = value.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        thinking = delta.get("reasoning_content") or ""
                        content = delta.get("content") or ""
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
                        finish = choice.get("finish_reason")
                        if finish:
                            done_reason = finish
            except (http.client.IncompleteRead, http.client.HTTPException, TimeoutError, socket.timeout) as exc:
                raise KimiError(
                    f"Kimi stream has an ambiguous outcome: {exc}",
                    category="ambiguous",
                    ambiguous=True,
                ) from exc
            if done_reason is None:
                raise KimiError(
                    "Kimi stream ended without a finish reason; outcome is ambiguous",
                    category="ambiguous",
                    ambiguous=True,
                )
            return GenerationResult(
                "".join(parts),
                done_reason,
                prompt_tokens,
                completion_tokens,
                time.monotonic_ns() - started,
            )
        finally:
            self._inference_lock.release()
