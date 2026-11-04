from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .errors import LlamaCppError, StorageError
from .storage import atomic_write_json, read_json, utc_now


class ProcessRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    @staticmethod
    def process_start_ticks(pid: int) -> str:
        try:
            raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            # The command name is parenthesized and may contain spaces.
            fields = raw[raw.rfind(")") + 2 :].split()
            state = fields[0]
            if state == "Z":
                raise LlamaCppError(f"Process {pid} is a zombie")
            start_ticks = fields[19]
            status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
            uid_line = next(line for line in status.splitlines() if line.startswith("Uid:"))
            uid = int(uid_line.split()[1])
            return f"{uid}:{start_ticks}"
        except (OSError, IndexError, StopIteration, ValueError) as exc:
            raise LlamaCppError(f"Cannot verify process {pid}: {exc}") from exc

    def capture(self, process: subprocess.Popen, argv: list[str], model_name: str) -> dict[str, Any]:
        identity = self.process_start_ticks(process.pid)
        uid, start_ticks = identity.split(":", 1)
        record = {
            "schema_version": 1,
            "pid": process.pid,
            "uid": int(uid),
            "start_ticks": start_ticks,
            "model_name": model_name,
            "argv": argv,
            "created_at": utc_now(),
        }
        atomic_write_json(self.path, record, mode=0o600)
        return record

    def load_valid(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            record = read_json(self.path)
            pid = int(record["pid"])
            identity = self.process_start_ticks(pid)
            expected = f"{record['uid']}:{record['start_ticks']}"
            if identity != expected or int(record["uid"]) != os.geteuid():
                raise LlamaCppError("Managed process identity does not match its registry")
            command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            arguments = [part.decode("utf-8") for part in command if part]
            if arguments[1:] != record["argv"][1:]:
                raise LlamaCppError("Managed process argv does not match its registry")
            return record
        except (KeyError, ValueError, TypeError, StorageError, OSError, LlamaCppError):
            # Never signal a process when identity cannot be proven. The stale
            # registry itself is safe to remove; the process is left untouched.
            self.path.unlink(missing_ok=True)
            return None

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class ExistingProcess:
    """Minimal Popen-compatible handle for a verified orphaned process."""

    def __init__(self, pid: int, expected_identity: str):
        self.pid = pid
        self.expected_identity = expected_identity
        self.returncode = None

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        try:
            if ProcessRegistry.process_start_ticks(self.pid) != self.expected_identity:
                self.returncode = -1
                return self.returncode
            return None
        except LlamaCppError:
            self.returncode = -1
            return self.returncode

    def terminate(self) -> None:
        if self.poll() is None:
            os.kill(self.pid, 15)

    def kill(self) -> None:
        if self.poll() is None:
            os.kill(self.pid, 9)

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.pid, timeout)
            time.sleep(0.05)
        return self.returncode
