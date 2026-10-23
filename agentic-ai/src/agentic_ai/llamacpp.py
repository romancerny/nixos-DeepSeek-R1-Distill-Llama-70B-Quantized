"""llama.cpp inference backend driven by a managed `llama-server` subprocess.

The orchestrator owns the server lifecycle so the one-resident-model
invariant holds across both inference backends: loading this model spawns
`llama-server` with the configured flags, unloading terminates it, and
residency checks observe the process state.

Chat uses the server's OpenAI-compatible `/v1/chat/completions` endpoint
with SSE streaming, mirroring OllamaClient.chat semantics (including
`<think>` wrapping of reasoning deltas and token-usage accounting).
"""

from __future__ import annotations

import http.client
import json
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator

from .config import LlamaCppConfig, RoleConfig
from .errors import LlamaCppError
from .ollama import GenerationResult


class LlamaCppBackend:
    def __init__(self, config: LlamaCppConfig, *, process_factory=None, log_dir: Path | None = None):
        self.config = config
        self.base_url = f"http://{config.host}:{config.port}"
        self._inference_lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._log_dir = log_dir
        # Test hook: returns a Popen-like object instead of spawning a server.
        self._process_factory = process_factory

    # ------------------------------------------------------------------ #
    # Process lifecycle (load/unload/ps)
    # ------------------------------------------------------------------ #

    def resolved_model_path(self) -> Path:
        return Path(self.config.model_path).expanduser()

    def server_argv(self) -> list[str]:
        cfg = self.config
        argv = [
            cfg.server_binary,
            "-m",
            str(self.resolved_model_path()),
            "-ngl",
            str(cfg.gpu_layers),
            "-c",
            str(cfg.context_length),
            "-ctk",
            cfg.cache_type_k,
            "-ctv",
            cfg.cache_type_v,
            "--host",
            cfg.host,
            "--port",
            str(cfg.port),
            "--jinja",
        ]
        argv.extend(cfg.extra_args)
        return argv

    def _spawn(self, argv: list[str], log_file) -> subprocess.Popen:
        if self._process_factory is not None:
            return self._process_factory(argv, log_file)
        return subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def is_resident(self) -> bool:
        with self._process_lock:
            return self._process is not None and self._process.poll() is None

    def ps(self) -> dict[str, Any]:
        if not self.is_resident():
            return {"models": []}
        return {
            "models": [
                {
                    "name": self.config.model_name,
                    "model": self.config.model_name,
                    "backend": "llamacpp",
                }
            ]
        }

    def _wait_healthy(self, process: subprocess.Popen, log_path: Path) -> None:
        deadline = time.monotonic() + self.config.startup_timeout_seconds
        url = self.base_url + "/health"
        while True:
            if process.poll() is not None:
                tail = self._log_tail(log_path)
                raise LlamaCppError(
                    f"llama-server exited during startup with code "
                    f"{process.returncode}: {tail}"
                )
            try:
                request = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(request, timeout=5) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError):
                pass
            if time.monotonic() >= deadline:
                tail = self._log_tail(log_path)
                raise LlamaCppError(
                    f"Timed out waiting for llama-server to become healthy: {tail}"
                )
            time.sleep(0.5)

    @staticmethod
    def _log_tail(log_path: Path, limit: int = 2000) -> str:
        try:
            return log_path.read_text(encoding="utf-8", errors="replace")[-limit:]
        except OSError:
            return "<no llama-server log available>"

    def load_model(self, model: str) -> dict[str, Any]:
        if model != self.config.model_name:
            raise LlamaCppError(f"llama.cpp backend does not serve model {model}")
        with self._process_lock:
            if self._process is not None and self._process.poll() is None:
                return {"model": model, "done": True}
            model_path = self.resolved_model_path()
            if not model_path.is_file():
                raise LlamaCppError(
                    f"GGUF model file is missing: {model_path}. Download it as the "
                    "ai-agent user (see docs/nixos-projects.md)."
                )
            if shutil.which(self.config.server_binary) is None and not Path(
                self.config.server_binary
            ).is_file():
                raise LlamaCppError(
                    f"llama.cpp server binary not found: {self.config.server_binary}"
                )
            argv = self.server_argv()
            log_dir = self._log_dir or (Path.home() / ".cache" / "agentic-ai")
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "llama-server.log"
            log_file = log_path.open("ab")
            try:
                self._process = self._spawn(argv, log_file)
            except OSError as exc:
                log_file.close()
                raise LlamaCppError(f"Cannot start llama-server: {exc}") from exc
            process = self._process
        try:
            self._wait_healthy(process, log_path)
        except Exception:
            self._terminate(process)
            with self._process_lock:
                if self._process is process:
                    self._process = None
            raise
        finally:
            log_file.close()
        return {"model": model, "done": True}

    def _terminate(self, process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                raise LlamaCppError("llama-server ignored SIGKILL")

    def unload_model(self, model: str) -> dict[str, Any]:
        with self._process_lock:
            process = self._process
            self._process = None
        if process is not None and process.poll() is None:
            self._terminate(process)
        return {"model": model, "done": True}

    # ------------------------------------------------------------------ #
    # Chat via the OpenAI-compatible endpoint
    # ------------------------------------------------------------------ #

    def _open(self, path: str, payload: dict[str, Any], timeout: int):
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "local-agentic-ai/0.1",
        }
        request = urllib.request.Request(
            self.base_url + path, data=body, headers=headers, method="POST"
        )
        last_error: Exception | None = None
        for attempt in range(self.config.transport_retries + 1):
            try:
                return urllib.request.urlopen(request, timeout=timeout)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:2000]
                exc.close()
                error = LlamaCppError(
                    f"llama-server HTTP {exc.code} for {path}: {detail or exc.reason}"
                )
                if exc.code not in {408, 429, 500, 502, 503, 504}:
                    raise error from exc
                last_error = error
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
                last_error = LlamaCppError(
                    f"Cannot reach llama-server at {self.base_url}: {exc}"
                )
            if attempt < self.config.transport_retries:
                time.sleep(0.25 * (2**attempt))
        raise LlamaCppError(str(last_error) if last_error else "llama-server request failed")

    @staticmethod
    def _sse_events(response) -> Iterator[dict[str, Any]]:
        for raw_line in response:
            try:
                line = raw_line.decode("utf-8").strip()
            except UnicodeDecodeError as exc:
                raise LlamaCppError(f"Invalid llama-server stream bytes: {raw_line[:200]!r}") from exc
            if not line or line.startswith(":"):
                continue
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if data == "[DONE]":
                return
            try:
                value = json.loads(data)
            except json.JSONDecodeError as exc:
                raise LlamaCppError(f"Invalid streamed llama-server JSON: {data[:500]!r}") from exc
            if not isinstance(value, dict):
                raise LlamaCppError("Unexpected streamed llama-server value")
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
        if model != self.config.model_name:
            raise LlamaCppError(f"llama.cpp backend does not serve model {model}")
        if not self.is_resident():
            raise LlamaCppError("llama-server is not running; load the model first")
        if not self._inference_lock.acquire(blocking=False):
            raise LlamaCppError(
                "Overlapping inference is forbidden by the one-model scheduler"
            )
        try:
            payload: dict[str, Any] = {
                "messages": messages,
                "stream": True,
                "stream_options": {"include_usage": True},
                "max_tokens": role.num_predict,
                "temperature": role.temperature,
            }
            if json_output:
                payload["response_format"] = {"type": "json_object"}
            response = self._open(
                "/v1/chat/completions", payload, self.config.request_timeout_seconds
            )
            parts: list[str] = []
            thinking_open = False
            done_reason: str | None = None
            prompt_eval_count = 0
            eval_count = 0
            started = time.monotonic_ns()

            def emit(text: str) -> None:
                if not text:
                    return
                parts.append(text)
                if on_text is not None:
                    on_text(text)

            with response:
                for value in self._sse_events(response):
                    if "error" in value:
                        error = value["error"]
                        detail = (
                            error.get("message")
                            if isinstance(error, dict)
                            else str(error)
                        )
                        raise LlamaCppError(f"llama-server chat: {detail}")
                    usage = value.get("usage")
                    if isinstance(usage, dict):
                        prompt_eval_count = usage.get("prompt_tokens") or prompt_eval_count
                        eval_count = usage.get("completion_tokens") or eval_count
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
            if done_reason is None:
                raise LlamaCppError("llama-server stream ended without a finish reason")
            return GenerationResult(
                "".join(parts),
                done_reason,
                prompt_eval_count,
                eval_count,
                time.monotonic_ns() - started,
            )
        except (http.client.IncompleteRead, http.client.HTTPException) as exc:
            raise LlamaCppError(f"llama-server stream interrupted: {exc}") from exc
        finally:
            self._inference_lock.release()
