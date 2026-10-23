from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .errors import PlanValidationError, StorageError
from .plan import safe_run_path


_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, text)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageError(f"Cannot read JSON {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class FileLock:
    def __init__(self, path: Path, *, blocking: bool = True):
        self.path = path
        self.blocking = blocking
        self._handle = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+")
        flags = fcntl.LOCK_EX | (0 if self.blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(self._handle.fileno(), flags)
        except BlockingIOError as exc:
            self._handle.close()
            self._handle = None
            raise StorageError(f"Lock is already held: {self.path}") from exc
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


class RunStore:
    def __init__(self, state_dir: str | Path, run_id: str):
        if not _RUN_ID.fullmatch(run_id):
            raise StorageError(f"Invalid run id: {run_id!r}")
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.run_id = run_id
        self.run_dir = self.state_dir / "runs" / run_id
        self.artifacts_dir = self.run_dir / "artifacts"
        self.workspace_dir = self.run_dir / "workspace"
        self.run_path = self.run_dir / "run.json"
        self.events_path = self.run_dir / "events.jsonl"

    @staticmethod
    def new_run_id() -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"run-{timestamp}-{uuid.uuid4().hex[:8]}"

    @classmethod
    def create(
        cls, state_dir: str | Path, brief: str, config: dict[str, Any], run_id: str | None = None
    ) -> "RunStore":
        store = cls(state_dir, run_id or cls.new_run_id())
        if store.run_dir.exists():
            raise StorageError(f"Run already exists: {store.run_id}")
        store.artifacts_dir.mkdir(parents=True)
        store.workspace_dir.mkdir()
        for directory in ("contexts", "waves", "switches", "attempts", "evaluations", "logs"):
            (store.run_dir / directory).mkdir()
        atomic_write_text(store.run_dir / "brief.md", brief)
        atomic_write_json(store.run_dir / "config.json", config)
        now = utc_now()
        run = {
            "schema_version": 1,
            "run_id": store.run_id,
            "status": "created",
            "goal": brief,
            "created_at": now,
            "updated_at": now,
            "plan_revision": 0,
            "current_wave": 0,
            "current_switch": 0,
            "repair_cycle": 0,
            "stop_after_plan": False,
            "task_states": {},
            "metrics": {
                "model_calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "model_loads": 0,
                "model_unloads": 0,
                "model_switches": 0,
                "tool_calls": 0,
            },
            "error": None,
        }
        atomic_write_json(store.run_path, run)
        store.append_event("run_created", run_id=store.run_id)
        return store

    @classmethod
    def open(cls, state_dir: str | Path, run_id: str) -> "RunStore":
        store = cls(state_dir, run_id)
        if not store.run_path.is_file():
            raise StorageError(f"Run does not exist: {run_id}")
        return store

    @property
    def executor_lock_path(self) -> Path:
        return self.state_dir / "executor.lock"

    @property
    def run_lock_path(self) -> Path:
        return self.run_dir / "run.lock"

    def executor_lock(self, *, blocking: bool = True) -> FileLock:
        return FileLock(self.executor_lock_path, blocking=blocking)

    def run_lock(self, *, blocking: bool = True) -> FileLock:
        return FileLock(self.run_lock_path, blocking=blocking)

    def load_run(self) -> dict[str, Any]:
        run = read_json(self.run_path)
        if not isinstance(run, dict) or run.get("run_id") != self.run_id:
            raise StorageError(f"Invalid run snapshot: {self.run_path}")
        return run

    def save_run(self, run: dict[str, Any]) -> None:
        run["updated_at"] = utc_now()
        atomic_write_json(self.run_path, run)

    def update_run(
        self, mutator: Callable[[dict[str, Any]], None] | None = None, **updates: Any
    ) -> dict[str, Any]:
        run = self.load_run()
        if mutator is not None:
            mutator(run)
        run.update(updates)
        self.save_run(run)
        return run

    def append_event(self, event_type: str, **payload: Any) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        event = {"timestamp": utc_now(), "type": event_type, "payload": payload}
        line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def repair_event_log(self) -> bool:
        if not self.events_path.exists():
            return False
        raw = self.events_path.read_bytes()
        if not raw:
            return False
        lines = raw.splitlines(keepends=True)
        good: list[bytes] = []
        repaired = False
        for index, line in enumerate(lines):
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                if index != len(lines) - 1:
                    raise StorageError("Audit log corruption before the final line") from exc
                repaired = True
                break
            good.append(line if line.endswith(b"\n") else line + b"\n")
        if repaired:
            atomic_write_bytes(self.events_path, b"".join(good))
            self.append_event("audit_log_repaired")
        return repaired

    def context_path(self, task_id: str) -> Path:
        return self.run_dir / "contexts" / f"{task_id}.json"

    def load_context(self, task_id: str) -> dict[str, Any]:
        return read_json(self.context_path(task_id))

    def save_context(self, task_id: str, context: dict[str, Any]) -> None:
        atomic_write_json(self.context_path(task_id), context)

    def attempt_dir(self, task_id: str, attempt: int, turn: int) -> Path:
        return (
            self.run_dir
            / "attempts"
            / task_id
            / f"attempt-{attempt:04d}"
            / f"turn-{turn:04d}"
        )

    def wave_path(self, wave: int) -> Path:
        return self.run_dir / "waves" / f"{wave:04d}.json"

    def switch_path(self, switch: int) -> Path:
        return self.run_dir / "switches" / f"{switch:04d}.json"

    def plan_path(self, revision: int) -> Path:
        return self.run_dir / f"plan.v{revision:04d}.json"

    def resolve_run_path(self, value: str, *, must_exist: bool = False) -> Path:
        try:
            normalized = safe_run_path(value)
        except PlanValidationError as exc:
            raise StorageError(str(exc)) from exc
        base_name, _, _ = normalized.partition("/")
        base = (self.run_dir / base_name).resolve()
        candidate = (self.run_dir / normalized).resolve(strict=False)
        if candidate != base and base not in candidate.parents:
            raise StorageError(f"Path escapes {base_name}: {value}")
        if must_exist and not candidate.exists():
            raise StorageError(f"Path does not exist: {value}")
        return candidate

    def run_relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.run_dir.resolve()).as_posix()

    def file_record(self, value: str) -> dict[str, Any]:
        path = self.resolve_run_path(value, must_exist=True)
        if not path.is_file():
            raise StorageError(f"Not a file: {value}")
        return {
            "path": self.run_relative(path),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }

    def validate_file_record(self, record: dict[str, Any]) -> bool:
        try:
            current = self.file_record(record["path"])
        except (KeyError, StorageError):
            return False
        return current["sha256"] == record.get("sha256") and current[
            "size_bytes"
        ] == record.get("size_bytes")

    def list_files(self, directory: str) -> list[str]:
        base = self.run_dir / directory
        if not base.exists():
            return []
        result: list[str] = []
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.run_dir)
            if any(part.startswith(".") for part in relative.parts):
                continue
            result.append(relative.as_posix())
        return sorted(result)
