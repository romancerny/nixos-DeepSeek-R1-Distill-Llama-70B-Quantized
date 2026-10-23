from __future__ import annotations

import itertools
import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from .config import Config
from .errors import PlanValidationError, StorageError, ToolError
from .plan import Task, safe_relative_path
from .storage import RunStore, atomic_write_json, atomic_write_text
from .web import WebRuntime


class ToolRuntime:
    def __init__(self, store: RunStore, config: Config, task: Task):
        self.store = store
        self.config = config
        self.task = task
        self.web = WebRuntime(config.web)

    @staticmethod
    def _check_arguments(call: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
        arguments = call["arguments"]
        unknown = set(arguments) - allowed
        if unknown:
            raise ToolError(f"Unknown {call['tool']} arguments: {sorted(unknown)}")
        return arguments

    def execute(self, call: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._execute(call)
            result.setdefault("ok", True)
            return result
        except (ToolError, StorageError, PlanValidationError, OSError) as exc:
            return {"ok": False, "tool": call.get("tool"), "error": str(exc)}

    def _execute(self, call: dict[str, Any]) -> dict[str, Any]:
        tool = call["tool"]
        if tool == "list_files":
            return self._list_files(call)
        if tool == "read_file":
            return self._read_file(call)
        if tool == "write_file":
            self._require_role({"coder", "qa"}, tool)
            return self._write_file(call)
        if tool == "write_artifact":
            self._require_role({"researcher", "architect"}, tool)
            return self._write_artifact(call)
        if tool == "run_command":
            self._require_role({"coder", "qa"}, tool)
            return self._run_command(call)
        if tool == "fetch_url":
            self._require_role({"researcher"}, tool)
            return self._fetch_url(call)
        if tool == "web_search":
            self._require_role({"researcher"}, tool)
            return self._web_search(call)
        raise ToolError(f"Unknown tool: {tool}")

    def _require_role(self, roles: set[str], tool: str) -> None:
        if self.task.role not in roles:
            raise ToolError(f"Role {self.task.role} cannot use {tool}")

    def _workspace_path(self, value: Any) -> tuple[str, Path]:
        if not isinstance(value, str):
            raise ToolError("File path must be a string")
        relative = value[len("workspace/") :] if value.startswith("workspace/") else value
        normalized = safe_relative_path(relative)
        run_path = "workspace/" + normalized
        return run_path, self.store.resolve_run_path(run_path)

    def _artifact_path(self, value: Any) -> tuple[str, Path]:
        if not isinstance(value, str):
            raise ToolError("Artifact path must be a string")
        relative = value[len("artifacts/") :] if value.startswith("artifacts/") else value
        normalized = safe_relative_path(relative)
        run_path = "artifacts/" + normalized
        return run_path, self.store.resolve_run_path(run_path)

    def _check_scope(self, relative: str) -> None:
        for scope in self.task.write_scope:
            if scope == "./":
                return
            if scope.endswith("/"):
                if relative.startswith(scope):
                    return
            elif relative == scope:
                return
        raise ToolError(
            f"Write {relative} is outside task {self.task.id} scope {self.task.write_scope}"
        )

    def _list_files(self, call: dict[str, Any]) -> dict[str, Any]:
        arguments = self._check_arguments(call, {"path", "max_entries"})
        value = arguments.get("path", "workspace")
        if value not in {"workspace", "artifacts"} and not value.startswith(
            ("workspace/", "artifacts/")
        ):
            raise ToolError("list_files path must be within workspace or artifacts")
        base = self.store.resolve_run_path(value, must_exist=True)
        if not base.is_dir():
            raise ToolError("list_files path must be a directory")
        maximum = arguments.get("max_entries", self.config.limits.max_list_entries)
        if not isinstance(maximum, int) or not 1 <= maximum <= self.config.limits.max_list_entries:
            raise ToolError("max_entries exceeds the configured cap")
        files = []
        for path in sorted(base.rglob("*")):
            if path.is_file() and not any(
                part.startswith(".") for part in path.relative_to(self.store.run_dir).parts
            ):
                files.append(self.store.run_relative(path))
                if len(files) >= maximum:
                    break
        return {"path": value, "files": files, "truncated": len(files) >= maximum}

    def _read_file(self, call: dict[str, Any]) -> dict[str, Any]:
        arguments = self._check_arguments(call, {"path", "offset", "max_lines"})
        value = arguments.get("path")
        if not isinstance(value, str):
            raise ToolError("read_file requires path")
        path = self.store.resolve_run_path(value, must_exist=True)
        if not path.is_file():
            raise ToolError("read_file path must be a file")
        offset = arguments.get("offset", 0)
        maximum = arguments.get("max_lines", 200)
        if not isinstance(offset, int) or offset < 0:
            raise ToolError("offset must be a non-negative line number")
        if not isinstance(maximum, int) or not 1 <= maximum <= 500:
            raise ToolError("max_lines must be between 1 and 500")
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = list(itertools.islice(handle, offset, offset + maximum))
        content = "".join(lines)
        truncated = len(content) > self.config.limits.max_tool_result_chars
        if truncated:
            content = content[: self.config.limits.max_tool_result_chars]
        return {
            "path": value,
            "offset": offset,
            "content": content,
            "lines_returned": len(lines),
            "truncated": truncated or len(lines) == maximum,
        }

    def _write_file(self, call: dict[str, Any]) -> dict[str, Any]:
        arguments = self._check_arguments(call, {"path", "content"})
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolError("write_file content must be a string")
        if len(content.encode("utf-8")) > self.config.limits.max_file_bytes:
            raise ToolError("write_file content exceeds max_file_bytes")
        run_path, path = self._workspace_path(arguments.get("path"))
        relative = run_path[len("workspace/") :]
        self._check_scope(relative)
        atomic_write_text(path, content)
        return {"written": self.store.file_record(run_path)}

    def _write_artifact(self, call: dict[str, Any]) -> dict[str, Any]:
        arguments = self._check_arguments(call, {"path", "content"})
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolError("write_artifact content must be a string")
        if len(content.encode("utf-8")) > self.config.limits.max_file_bytes:
            raise ToolError("write_artifact content exceeds max_file_bytes")
        run_path, path = self._artifact_path(arguments.get("path"))
        relative = run_path[len("artifacts/") :]
        if relative not in self.task.artifact_outputs:
            raise ToolError(
                f"Artifact {relative} is not declared in artifact_outputs for {self.task.id}"
            )
        atomic_write_text(path, content)
        return {"written": self.store.file_record(run_path)}

    def _run_command(self, call: dict[str, Any]) -> dict[str, Any]:
        arguments = self._check_arguments(call, {"command_id"})
        command_id = arguments.get("command_id")
        if command_id not in self.config.commands:
            raise ToolError(f"Unknown command_id: {command_id}")
        command = self.config.commands[command_id]
        log_path = self.store.run_dir / "logs" / f"{self.task.id}-{call['call_id']}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        home = self.store.run_dir / "home"
        temporary = self.store.run_dir / "tmp"
        home.mkdir(exist_ok=True)
        temporary.mkdir(exist_ok=True)
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "TMPDIR": str(temporary),
            "LANG": "C.UTF-8",
            "PYTHONUNBUFFERED": "1",
            "NO_COLOR": "1",
        }
        timed_out = False
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                command.resolved_argv(),
                cwd=self.store.workspace_dir,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                shell=False,
                start_new_session=True,
            )
            try:
                return_code = process.wait(timeout=command.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    return_code = process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    return_code = process.wait()
        size = log_path.stat().st_size
        with log_path.open("rb") as handle:
            tail_bytes = self.config.limits.max_tool_result_chars * 4
            if size > tail_bytes:
                handle.seek(-tail_bytes, os.SEEK_END)
            output = handle.read().decode("utf-8", errors="replace")
        output = output[-self.config.limits.max_tool_result_chars :]
        return {
            "command_id": command_id,
            "argv": command.resolved_argv(),
            "return_code": return_code,
            "timed_out": timed_out,
            "ok": return_code == 0 and not timed_out,
            "log_path": log_path.relative_to(self.store.run_dir).as_posix(),
            "log_size_bytes": size,
            "output_tail": output,
        }

    def _fetch_url(self, call: dict[str, Any]) -> dict[str, Any]:
        arguments = self._check_arguments(call, {"url"})
        url = arguments.get("url")
        if not isinstance(url, str):
            raise ToolError("fetch_url requires a URL string")
        return self.web.fetch(url)

    def _web_search(self, call: dict[str, Any]) -> dict[str, Any]:
        arguments = self._check_arguments(call, {"query"})
        query = arguments.get("query")
        if not isinstance(query, str):
            raise ToolError("web_search requires a query string")
        return self.web.search(query)
