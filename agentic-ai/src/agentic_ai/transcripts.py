from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Config
from .errors import StorageError
from .identity import Actor, MemoryPolicy
from .storage import FileLock, RunStore, atomic_write_json, read_json, sha256_file, utc_now


class TranscriptBuilder:
    """Creates a canonical, permission-labelled transcript for later dreaming."""

    MAX_SOURCE_FILE_BYTES = 64_000_000

    def __init__(self, config: Config):
        self.config = config

    @staticmethod
    def _source_record(path: Path, base: Path) -> dict[str, Any]:
        size = path.stat().st_size
        if size > TranscriptBuilder.MAX_SOURCE_FILE_BYTES:
            raise StorageError(f"Transcript source exceeds safety cap: {path}")
        return {
            "path": path.relative_to(base).as_posix(),
            "sha256": sha256_file(path),
            "size_bytes": size,
        }

    def finalize(self, store: RunStore) -> dict[str, Any]:
        run = store.load_run()
        attempts = []
        source_files = []
        attempts_root = store.run_dir / "attempts"
        for path in sorted(attempts_root.glob("*/*/*/*")):
            if not path.is_file() or path.suffix not in {".json", ".txt"}:
                continue
            record = self._source_record(path, store.run_dir)
            source_files.append(record)
            attempts.append(
                {
                    **record,
                    "content": path.read_text(encoding="utf-8", errors="strict"),
                }
            )
        events = []
        if store.events_path.exists():
            for line in store.events_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    events.append(json.loads(line))
        transcript = {
            "schema_version": 1,
            "run_id": store.run_id,
            "project_id": self.config.memory.project_id,
            "memory_root": self.config.memory.root,
            "classification": self.config.memory.classification,
            "status": run["status"],
            "created_at": run["created_at"],
            "finalized_at": utc_now(),
            "run": run,
            "events": events,
            "attempts": attempts,
        }
        transcripts_dir = store.run_dir / "transcripts"
        atomic_write_json(transcripts_dir / "payload.json", transcript, mode=0o640)
        actual_digest = sha256_file(transcripts_dir / "payload.json")
        eligible = bool(
            self.config.memory.enabled
            and self.config.memory.dreaming_enabled
            and run["status"] in {"succeeded", "failed"}
        )
        manifest = {
            "schema_version": 1,
            "run_id": store.run_id,
            "project_id": self.config.memory.project_id,
            "memory_root": self.config.memory.root,
            "classification": self.config.memory.classification,
            "status": run["status"],
            "created_at": transcript["created_at"],
            "finalized_at": transcript["finalized_at"],
            "payload_path": "payload.json",
            "payload_sha256": actual_digest,
            "payload_size_bytes": (transcripts_dir / "payload.json").stat().st_size,
            "source_files": source_files,
            "complete": True,
            "dream_eligible": eligible,
            "redacted": False,
        }
        atomic_write_json(transcripts_dir / "manifest.json", manifest, mode=0o640)
        store.append_event(
            "transcript_finalized",
            payload_sha256=actual_digest,
            dream_eligible=eligible,
            attempts=len(attempts),
        )
        return manifest

    @staticmethod
    def redact(state_dir: str | Path, run_id: str, *, reason: str, actor: Actor) -> dict[str, Any]:
        MemoryPolicy.require_human(actor, "Transcript redaction")
        directory = Path(state_dir).expanduser().resolve() / "runs" / run_id / "transcripts"
        manifest = read_json(directory / "manifest.json")
        memory_root = manifest.get("memory_root")
        if not memory_root:
            raise StorageError("Transcript has no memory root for review locking")
        with FileLock(
            Path(memory_root) / "dreams" / "decisions" / "review.lock", mode=0o660
        ):
            return TranscriptBuilder._redact_locked(state_dir, run_id, reason=reason, actor=actor)

    @staticmethod
    def _redact_locked(state_dir: str | Path, run_id: str, *, reason: str, actor: Actor) -> dict[str, Any]:
        MemoryPolicy.require_human(actor, "Transcript redaction")
        directory = Path(state_dir).expanduser().resolve() / "runs" / run_id / "transcripts"
        manifest_path = directory / "manifest.json"
        manifest = read_json(manifest_path)
        if not manifest.get("redacted"):
            manifest["redacted"] = True
            manifest["dream_eligible"] = False
            manifest["redacted_at"] = utc_now()
            manifest["redaction_reason"] = reason
            manifest["redacted_by"] = actor.to_dict()
            payload_name = Path(manifest["payload_path"])
            if payload_name.is_absolute() or ".." in payload_name.parts or len(payload_name.parts) != 1:
                raise StorageError("Unsafe transcript payload path")
            (directory / payload_name).unlink(missing_ok=True)
            atomic_write_json(manifest_path, manifest, mode=0o640)
        return manifest

    @staticmethod
    def load(state_dir: str | Path, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        directory = Path(state_dir).expanduser().resolve() / "runs" / run_id / "transcripts"
        manifest = read_json(directory / "manifest.json")
        if not manifest.get("complete") or manifest.get("redacted"):
            raise StorageError(f"Transcript is not eligible: {run_id}")
        if not manifest.get("dream_eligible"):
            raise StorageError(f"Transcript does not consent to dreaming: {run_id}")
        payload_name = Path(manifest["payload_path"])
        if payload_name.is_absolute() or ".." in payload_name.parts or len(payload_name.parts) != 1:
            raise StorageError("Unsafe transcript payload path")
        payload_path = directory / payload_name
        if sha256_file(payload_path) != manifest["payload_sha256"]:
            raise StorageError(f"Transcript hash mismatch: {run_id}")
        if payload_path.stat().st_size != manifest["payload_size_bytes"]:
            raise StorageError(f"Transcript size mismatch: {run_id}")
        payload = read_json(payload_path)
        if payload.get("run_id") != run_id:
            raise StorageError("Transcript run identity mismatch")
        run_dir = directory.parent
        for record in manifest.get("source_files", []):
            relative = Path(record["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise StorageError("Unsafe transcript source path")
            source = run_dir / relative
            if sha256_file(source) != record["sha256"] or source.stat().st_size != record["size_bytes"]:
                raise StorageError(f"Transcript source changed: {record['path']}")
        return manifest, payload
