from __future__ import annotations

import difflib
import json
import os
import shutil
import stat
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .documents import (
    MemoryDocument,
    sha256_bytes,
    validate_document_id,
    validate_namespace,
)
from .errors import (
    MemoryConflictError,
    MemoryError,
    MemoryNotFoundError,
    MemoryPermissionError,
    StorageError,
)
from .identity import Actor, MemoryPolicy, MemoryScope
from .memory_index import MemoryIndex
from .storage import FileLock, atomic_write_bytes, atomic_write_json, read_json, sha256_file, utc_now


@dataclass(frozen=True)
class MemoryChange:
    document: MemoryDocument
    expected_sha256: str | None = None
    operation: str = "modified"
    provenance: dict[str, Any] = field(default_factory=dict)


class MemoryStore:
    OPERATIONS = {"created", "modified", "deleted", "rollback", "imported", "redacted"}

    def __init__(self, root: str | Path, *, index_path: str | Path | None = None):
        supplied = Path(root).expanduser()
        if supplied.is_symlink():
            raise MemoryError(f"Memory root cannot be a symlink: {supplied}")
        self.root = supplied.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o750)
        self._index_path = (
            Path(index_path).expanduser().resolve()
            if index_path
            else self.root / "indexes" / f"memory-{os.geteuid()}.sqlite3"
        )
        self._index: MemoryIndex | None = None

    @staticmethod
    def scope_path(root: Path, scope: MemoryScope) -> Path:
        if scope.kind in {"org", "skills"}:
            return root / scope.kind
        if scope.kind in {"curated", "inbox"}:
            return root / "projects" / scope.namespace / scope.kind
        return root / "agents" / scope.namespace / "scratch"

    def _scope_root(self, scope: MemoryScope) -> Path:
        validate_namespace(scope.namespace)
        path = self.scope_path(self.root, scope)
        relative = path.relative_to(self.root)
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise MemoryError(f"Memory path contains a symlink: {current}")
        return path

    @staticmethod
    def _file_mode(actor: Actor) -> int:
        return 0o640

    def initialize(self, actor: Actor) -> list[str]:
        MemoryPolicy.require_human(actor, "Memory initialization")
        initialized = []
        for scope in (MemoryScope("org"), MemoryScope("skills")):
            self._ensure_scope(scope, actor)
            catalog_path = self._catalog_path(scope)
            if not catalog_path.exists():
                self._write_catalog(scope, self._load_catalog(scope), actor)
                initialized.append(f"{scope.kind}/{scope.namespace}")
        (self.root / "redactions").mkdir(exist_ok=True, mode=0o750)
        (self.root / "dreams").mkdir(exist_ok=True, mode=0o750)
        return initialized

    @staticmethod
    def _directory_mode(actor: Actor) -> int:
        return 0o750

    def _ensure_scope(self, scope: MemoryScope, actor: Actor) -> Path:
        root = self._scope_root(scope)
        root.mkdir(parents=True, exist_ok=True, mode=self._directory_mode(actor))
        for name in ("objects", "versions", "operations", "locks"):
            (root / name).mkdir(exist_ok=True, mode=self._directory_mode(actor))
        return root

    def _catalog_path(self, scope: MemoryScope) -> Path:
        path = self._scope_root(scope) / "catalog.json"
        if path.is_symlink():
            raise MemoryError(f"Memory catalog cannot be a symlink: {path}")
        return path

    def _load_catalog(self, scope: MemoryScope) -> dict[str, Any]:
        path = self._catalog_path(scope)
        if not path.exists():
            return {
                "schema_version": 1,
                "scope": scope.kind,
                "namespace": scope.namespace,
                "documents": {},
            }
        catalog = read_json(path)
        if (
            not isinstance(catalog, dict)
            or catalog.get("scope") != scope.kind
            or catalog.get("namespace") != scope.namespace
            or not isinstance(catalog.get("documents"), dict)
        ):
            raise MemoryError(f"Invalid memory catalog: {path}")
        return catalog

    def _write_catalog(self, scope: MemoryScope, catalog: dict[str, Any], actor: Actor) -> None:
        atomic_write_json(self._catalog_path(scope), catalog, mode=self._file_mode(actor))

    @staticmethod
    def _entry(scope: MemoryScope, document_id: str, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "scope": scope.kind,
            "namespace": scope.namespace,
            "document_id": document_id,
            **entry,
        }

    def _object_path(self, scope: MemoryScope, sha256: str) -> Path:
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
            raise MemoryError("Invalid content SHA-256")
        path = self._scope_root(scope) / "objects" / sha256[:2] / f"{sha256}.md"
        if path.is_symlink():
            raise MemoryError(f"Memory object cannot be a symlink: {path}")
        return path

    def _version_path(self, scope: MemoryScope, document_id: str, version_id: str) -> Path:
        validate_document_id(document_id)
        if not version_id.startswith("v") or not version_id[1:].isdigit():
            raise MemoryError("Invalid memory version id")
        path = self._scope_root(scope) / "versions" / document_id / f"{version_id}.json"
        if path.is_symlink():
            raise MemoryError(f"Memory version cannot be a symlink: {path}")
        return path

    def _redaction_path(self, scope: MemoryScope, document_id: str) -> Path:
        return (
            self.root
            / "redactions"
            / f"{scope.kind}-{scope.namespace}-{document_id}.json"
        )

    def _write_object(self, scope: MemoryScope, document: MemoryDocument, actor: Actor) -> str:
        data = document.to_bytes()
        digest = sha256_bytes(data)
        path = self._object_path(scope, digest)
        if path.exists():
            if sha256_file(path) != digest:
                raise MemoryError(f"Content-addressed object collision or corruption: {path}")
            return digest
        atomic_write_bytes(path, data, mode=self._file_mode(actor))
        return digest

    def _read_object(self, scope: MemoryScope, digest: str) -> MemoryDocument:
        path = self._object_path(scope, digest)
        try:
            if sha256_file(path) != digest:
                raise MemoryError(f"Memory object hash mismatch: {path}")
            return MemoryDocument.from_bytes(path.read_bytes())
        except OSError as exc:
            raise MemoryNotFoundError(f"Memory object is unavailable: {path}") from exc

    def _write_version(
        self,
        scope: MemoryScope,
        record: dict[str, Any],
        actor: Actor,
    ) -> None:
        path = self._version_path(scope, record["document_id"], record["version_id"])
        if path.exists():
            if read_json(path) != record:
                raise MemoryError(f"Immutable version already exists with different data: {path}")
            return
        atomic_write_json(path, record, mode=self._file_mode(actor))

    def _read_version_record(
        self, scope: MemoryScope, document_id: str, version_id: str
    ) -> dict[str, Any]:
        path = self._version_path(scope, document_id, version_id)
        try:
            record = read_json(path)
        except StorageError as exc:
            raise MemoryNotFoundError(f"Memory version not found: {path}") from exc
        if record.get("document_id") != document_id or record.get("version_id") != version_id:
            raise MemoryError(f"Memory version identity mismatch: {path}")
        return record

    @staticmethod
    def _request_fingerprint(
        scope: MemoryScope,
        actor: Actor,
        changes: list[MemoryChange],
        provenance: dict[str, Any],
    ) -> str:
        value = {
            "scope": scope.to_dict(),
            "actor": actor.to_dict(),
            "provenance": provenance,
            "changes": [
                {
                    "document_id": change.document.document_id,
                    "sha256": change.document.sha256(),
                    "expected_sha256": change.expected_sha256,
                    "operation": change.operation,
                    "provenance": change.provenance,
                }
                for change in changes
            ],
        }
        return sha256_bytes(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        )

    def _operation_path(self, scope: MemoryScope, mutation_id: str) -> Path:
        if not uuid.UUID(mutation_id):
            raise MemoryError("Invalid mutation id")
        path = self._scope_root(scope) / "operations" / f"{mutation_id}.json"
        if path.is_symlink():
            raise MemoryError(f"Memory operation cannot be a symlink: {path}")
        return path

    @staticmethod
    def _operation_snapshot(operation: dict[str, Any]) -> dict[str, Any]:
        snapshot = {
            key: value
            for key, value in operation.items()
            if key not in {"_prepared", "changes"}
        }
        snapshot["changes"] = [
            {
                key: value
                for key, value in change.items()
                if key not in {"document", "version_record"}
            }
            for change in operation["changes"]
        ]
        return snapshot

    def _checkpoint(self, name: str, operation: dict[str, Any]) -> None:
        """Fault-injection seam used by recovery tests."""

    def _repair_audit(self, scope: MemoryScope, actor: Actor) -> None:
        path = self._scope_root(scope) / "audit.jsonl"
        if not path.exists():
            return
        lines = path.read_bytes().splitlines(keepends=True)
        good = []
        for index, line in enumerate(lines):
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                if index != len(lines) - 1:
                    raise MemoryError(f"Corrupt memory audit log before final line: {path}") from exc
                atomic_write_bytes(path, b"".join(good), mode=self._file_mode(actor))
                return
            good.append(line if line.endswith(b"\n") else line + b"\n")

    def _audit_contains(self, scope: MemoryScope, mutation_id: str, actor: Actor) -> bool:
        self._repair_audit(scope, actor)
        path = self._scope_root(scope) / "audit.jsonl"
        if not path.exists():
            return False
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise MemoryError(f"Corrupt memory audit log: {path}") from exc
                if event.get("mutation_id") == mutation_id:
                    return True
        return False

    def _append_audit(
        self,
        scope: MemoryScope,
        operation: dict[str, Any],
        actor: Actor,
    ) -> None:
        if self._audit_contains(scope, operation["mutation_id"], actor):
            return
        path = self._scope_root(scope) / "audit.jsonl"
        previous_hash = None
        if path.exists():
            lines = path.read_bytes().splitlines()
            if lines:
                previous_hash = sha256_bytes(lines[-1])
        event = {
            "timestamp": utc_now(),
            "mutation_id": operation["mutation_id"],
            "scope": scope.kind,
            "namespace": scope.namespace,
            "actor": operation["actor"],
            "changes": [
                {
                    "document_id": change["document_id"],
                    "version_id": change["version_id"],
                    "sha256": change["sha256"],
                    "parent_sha256": change["parent_sha256"],
                    "operation": change["operation"],
                }
                for change in operation["changes"]
            ],
            "prev_sha256": previous_hash,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            try:
                os.chmod(path, self._file_mode(actor))
            except OSError:
                pass
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _reconcile_pending(
        self, scope: MemoryScope, catalog: dict[str, Any], actor: Actor
    ) -> None:
        operations = self._scope_root(scope) / "operations"
        for path in sorted(operations.glob("*.json")):
            operation = read_json(path)
            if operation.get("status") != "pending":
                continue
            versions = []
            applied = True
            for change in operation["changes"]:
                current = catalog["documents"].get(change["document_id"])
                if not current or int(current["version_id"][1:]) < int(change["version_id"][1:]):
                    applied = False
                    break
                if (
                    current["version_id"] == change["version_id"]
                    and current.get("sha256") not in {change["sha256"], None}
                ):
                    raise MemoryError("Catalog/version conflict during pending recovery")
                try:
                    versions.append(
                        self._read_version_record(
                            scope, change["document_id"], change["version_id"]
                        )
                    )
                except MemoryNotFoundError:
                    applied = False
                    break
            if not applied:
                continue
            self._append_audit(scope, operation, actor)
            operation["status"] = "committed"
            operation["committed_at"] = utc_now()
            operation["versions"] = versions
            atomic_write_json(
                path, self._operation_snapshot(operation), mode=self._file_mode(actor)
            )

    def commit(
        self,
        scope: MemoryScope,
        changes: list[MemoryChange],
        actor: Actor,
        *,
        provenance: dict[str, Any] | None = None,
        mutation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        MemoryPolicy.require_write(actor, scope)
        if not 1 <= len(changes) <= 100:
            raise MemoryError("A catalog mutation must contain 1–100 changes")
        if len({change.document.document_id for change in changes}) != len(changes):
            raise MemoryError("A catalog mutation cannot contain duplicate document ids")
        provenance = provenance or {}
        mutation_id = mutation_id or str(uuid.uuid4())
        uuid.UUID(mutation_id)
        fingerprint = self._request_fingerprint(scope, actor, changes, provenance)
        self._ensure_scope(scope, actor)
        operation_path = self._operation_path(scope, mutation_id)
        if operation_path.exists():
            existing = read_json(operation_path)
            if existing.get("request_sha256") != fingerprint:
                raise MemoryConflictError("Mutation id was already used for a different request")
            if existing.get("status") == "committed":
                return list(existing["versions"])
            if existing.get("status") in {"conflicted", "rejected"}:
                raise MemoryConflictError(f"Mutation is {existing['status']}: {mutation_id}")

        lock_path = self._scope_root(scope) / "locks" / "catalog.lock"
        with FileLock(lock_path, mode=0o660):
            catalog = self._load_catalog(scope)
            self._reconcile_pending(scope, catalog, actor)
            if operation_path.exists():
                operation = read_json(operation_path)
                if operation.get("request_sha256") != fingerprint:
                    raise MemoryConflictError(
                        "Mutation id was already used for a different request"
                    )
                if operation.get("status") == "committed":
                    return list(operation["versions"])
                if operation.get("status") in {"conflicted", "rejected"}:
                    raise MemoryConflictError(f"Mutation is {operation['status']}: {mutation_id}")
            else:
                prepared = []
                for change in changes:
                    if change.operation not in self.OPERATIONS:
                        raise MemoryError(f"Unknown memory operation: {change.operation}")
                    if change.operation in {"deleted", "rollback", "imported", "redacted"}:
                        MemoryPolicy.require_human(actor, f"Memory {change.operation}")
                    document_id = change.document.document_id
                    if (
                        change.operation != "redacted"
                        and self._redaction_path(scope, document_id).exists()
                    ):
                        raise MemoryConflictError(
                            f"Memory is redacted or redaction is pending: {document_id}"
                        )
                    if change.operation == "redacted" and not self._redaction_path(
                        scope, document_id
                    ).exists():
                        raise MemoryPermissionError(
                            "Redacted tombstones require the authenticated redaction workflow"
                        )
                    current = catalog["documents"].get(document_id)
                    if current and current.get("redacted") and change.operation != "redacted":
                        raise MemoryConflictError(f"Memory is redacted: {document_id}")
                    current_hash = current.get("sha256") if current else None
                    if change.operation == "created" and current and not current.get("deleted"):
                        raise MemoryConflictError(f"Memory already exists: {document_id}")
                    if current_hash != change.expected_sha256:
                        raise MemoryConflictError(
                            f"Memory precondition failed for {document_id}: expected "
                            f"{change.expected_sha256}, current {current_hash}"
                        )
                    previous_number = int(current["version_id"][1:]) if current else 0
                    metadata = dict(change.document.metadata)
                    if actor.kind == "agent":
                        metadata["review_status"] = "unreviewed"
                    document = MemoryDocument(metadata=metadata, body=change.document.body)
                    prepared.append(
                        {
                            "document_id": document_id,
                            "version_id": f"v{previous_number + 1:06d}",
                            "sha256": document.sha256(),
                            "parent_sha256": current_hash,
                            "operation": change.operation,
                            "document": document,
                            "provenance": change.provenance,
                        }
                    )
                operation = {
                    "schema_version": 1,
                    "mutation_id": mutation_id,
                    "request_sha256": fingerprint,
                    "status": "pending",
                    "created_at": utc_now(),
                    "scope": scope.to_dict(),
                    "actor": actor.to_dict(),
                    "provenance": provenance,
                    "changes": [
                        {key: value for key, value in change.items() if key != "document"}
                        for change in prepared
                    ],
                }
                # Keep canonical documents out of JSON operation metadata.
                operation["_prepared"] = prepared
                atomic_write_json(
                    operation_path,
                    self._operation_snapshot(operation),
                    mode=self._file_mode(actor),
                )

            by_id = {change.document.document_id: change for change in changes}
            for recorded in operation["changes"]:
                document = by_id[recorded["document_id"]].document
                if actor.kind == "agent":
                    metadata = dict(document.metadata)
                    metadata["review_status"] = "unreviewed"
                    document = MemoryDocument(metadata=metadata, body=document.body)
                recorded["document"] = document

            for recorded in operation["changes"]:
                current = catalog["documents"].get(recorded["document_id"])
                if current and current.get("version_id") == recorded["version_id"]:
                    if current.get("sha256") != recorded["sha256"]:
                        raise MemoryError("Catalog contains a conflicting version assignment")
                    continue
                current_hash = current.get("sha256") if current else None
                if current_hash != recorded["parent_sha256"]:
                    operation["status"] = "conflicted"
                    atomic_write_json(
                        operation_path,
                        self._operation_snapshot(operation),
                        mode=self._file_mode(actor),
                    )
                    raise MemoryConflictError(
                        f"Catalog changed while mutation was pending: {recorded['document_id']}"
                    )

            for recorded in operation["changes"]:
                self._write_object(scope, recorded["document"], actor)
                version_record = {
                    "schema_version": 1,
                    "version_id": recorded["version_id"],
                    "document_id": recorded["document_id"],
                    "scope": scope.kind,
                    "namespace": scope.namespace,
                    "operation": recorded["operation"],
                    "sha256": recorded["sha256"],
                    "parent_sha256": recorded["parent_sha256"],
                    "created_at": operation["created_at"],
                    "actor": operation["actor"],
                    "mutation_id": mutation_id,
                    "provenance": {
                        **provenance,
                        **recorded["provenance"],
                    },
                }
                self._write_version(scope, version_record, actor)
                catalog["documents"][recorded["document_id"]] = {
                    "version_id": recorded["version_id"],
                    "sha256": recorded["sha256"],
                    "deleted": recorded["operation"] in {"deleted", "redacted"},
                    "redacted": recorded["operation"] == "redacted",
                }
                recorded["version_record"] = version_record

            self._checkpoint("before_catalog", operation)
            self._write_catalog(scope, catalog, actor)
            self._checkpoint("after_catalog", operation)
            self._append_audit(scope, operation, actor)
            versions = [recorded["version_record"] for recorded in operation["changes"]]
            operation["status"] = "committed"
            operation["committed_at"] = utc_now()
            operation["versions"] = versions
            atomic_write_json(
                operation_path,
                self._operation_snapshot(operation),
                mode=self._file_mode(actor),
            )
            self._checkpoint("committed", operation)
            return versions

    def put(
        self,
        scope: MemoryScope,
        document: MemoryDocument,
        actor: Actor,
        *,
        expected_sha256: str | None = None,
        operation: str = "modified",
        provenance: dict[str, Any] | None = None,
        mutation_id: str | None = None,
    ) -> dict[str, Any]:
        return self.commit(
            scope,
            [
                MemoryChange(
                    document=document,
                    expected_sha256=expected_sha256,
                    operation=operation,
                )
            ],
            actor,
            provenance=provenance,
            mutation_id=mutation_id,
        )[0]

    def read(
        self, scope: MemoryScope, document_id: str, actor: Actor
    ) -> tuple[MemoryDocument, dict[str, Any]]:
        MemoryPolicy.require_read(actor, scope)
        validate_document_id(document_id)
        catalog = self._load_catalog(scope)
        entry = catalog["documents"].get(document_id)
        if not entry:
            raise MemoryNotFoundError(f"Memory not found: {scope.kind}/{document_id}")
        if self._redaction_path(scope, document_id).exists():
            raise MemoryPermissionError(f"Memory is redacted or redaction is pending: {document_id}")
        if entry.get("redacted"):
            raise MemoryPermissionError(f"Memory has been redacted: {document_id}")
        if entry.get("deleted"):
            raise MemoryNotFoundError(f"Memory not found: {scope.kind}/{document_id}")
        record = self._read_version_record(scope, document_id, entry["version_id"])
        return self._read_object(scope, entry["sha256"]), record

    def read_version(
        self, scope: MemoryScope, document_id: str, version_id: str, actor: Actor
    ) -> tuple[MemoryDocument, dict[str, Any]]:
        MemoryPolicy.require_read(actor, scope)
        validate_document_id(document_id)
        if self._redaction_path(scope, document_id).exists():
            raise MemoryPermissionError(f"Memory is redacted or redaction is pending: {document_id}")
        record = self._read_version_record(scope, document_id, version_id)
        if record.get("payload_redacted"):
            raise MemoryPermissionError(f"Memory version has been redacted: {version_id}")
        return self._read_object(scope, record["sha256"]), record

    def history(
        self, scope: MemoryScope, document_id: str, actor: Actor
    ) -> list[dict[str, Any]]:
        MemoryPolicy.require_read(actor, scope)
        validate_document_id(document_id)
        directory = self._scope_root(scope) / "versions" / document_id
        if not directory.exists():
            return []
        return [
            read_json(path)
            for path in sorted(directory.glob("v*.json"))
        ]

    def diff(
        self,
        scope: MemoryScope,
        document_id: str,
        actor: Actor,
        *,
        from_version: str,
        to_version: str | None = None,
    ) -> str:
        source, _ = self.read_version(scope, document_id, from_version, actor)
        if to_version:
            target, _ = self.read_version(scope, document_id, to_version, actor)
        else:
            target, _ = self.read(scope, document_id, actor)
        return "".join(
            difflib.unified_diff(
                source.body.splitlines(keepends=True),
                target.body.splitlines(keepends=True),
                fromfile=f"{document_id}/{from_version}",
                tofile=f"{document_id}/{to_version or 'head'}",
            )
        )

    def rollback(
        self,
        scope: MemoryScope,
        document_id: str,
        version_id: str,
        actor: Actor,
        *,
        expected_sha256: str,
        reason: str = "",
    ) -> dict[str, Any]:
        MemoryPolicy.require_human(actor, "Memory rollback")
        document, _ = self.read_version(scope, document_id, version_id, actor)
        return self.put(
            scope,
            document,
            actor,
            expected_sha256=expected_sha256,
            operation="rollback",
            provenance={"rollback_to": version_id, "reason": reason},
        )

    def delete(
        self,
        scope: MemoryScope,
        document_id: str,
        actor: Actor,
        *,
        expected_sha256: str,
        reason: str = "",
    ) -> dict[str, Any]:
        document, _ = self.read(scope, document_id, actor)
        tombstone = MemoryDocument(metadata=dict(document.metadata), body="")
        return self.put(
            scope,
            tombstone,
            actor,
            expected_sha256=expected_sha256,
            operation="deleted",
            provenance={"reason": reason},
        )

    def redact(
        self,
        scope: MemoryScope,
        document_id: str,
        actor: Actor,
        *,
        reason: str,
    ) -> dict[str, Any]:
        MemoryPolicy.require_human(actor, "Memory redaction")
        validate_document_id(document_id)
        marker_path = self._redaction_path(scope, document_id)
        catalog = self._load_catalog(scope)
        entry = catalog["documents"].get(document_id)
        if not entry:
            raise MemoryNotFoundError(f"Memory not found: {document_id}")
        if marker_path.exists():
            marker = read_json(marker_path)
        else:
            document = self._read_object(scope, entry["sha256"])
            marker = {
                "schema_version": 1,
                "redaction_id": str(uuid.uuid4()),
                "scope": scope.kind,
                "namespace": scope.namespace,
                "document_id": document_id,
                "created_at": utc_now(),
                "actor": actor.to_dict(),
                "reason": reason,
            }
            marker_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            atomic_write_json(marker_path, marker, mode=0o640)
        if not entry.get("redacted"):
            document = self._read_object(scope, entry["sha256"])
            tombstone = MemoryDocument(metadata=dict(document.metadata), body="")
            self.put(
                scope,
                tombstone,
                actor,
                expected_sha256=entry["sha256"],
                operation="redacted",
                provenance={"redaction_id": marker["redaction_id"], "reason": reason},
            )
        # Once the marker exists, readers fail closed even if cleanup is
        # interrupted. The same catalog lock blocks resurrection and deletion
        # races while version metadata and payloads are reconciled.
        with FileLock(self._scope_root(scope) / "locks" / "catalog.lock", mode=0o660):
            catalog = self._load_catalog(scope)
            entry = catalog["documents"][document_id]
            affected_hashes = set()
            for path in sorted((self._scope_root(scope) / "versions" / document_id).glob("v*.json")):
                record = read_json(path)
                affected_hashes.add(record["sha256"])
                record["payload_redacted"] = True
                record["redaction_id"] = marker["redaction_id"]
                atomic_write_json(path, record, mode=self._file_mode(actor))
            entry["redacted"] = True
            entry["deleted"] = True
            entry["sha256"] = None
            self._write_catalog(scope, catalog, actor)
            referenced = set()
            for path in (self._scope_root(scope) / "versions").glob("*/*.json"):
                record = read_json(path)
                if not record.get("payload_redacted") and record.get("sha256"):
                    referenced.add(record["sha256"])
            for digest in affected_hashes - referenced:
                self._object_path(scope, digest).unlink(missing_ok=True)
        return marker

    def _discover_scopes(self) -> list[MemoryScope]:
        result = []
        for kind in ("org", "skills"):
            if (self.root / kind / "catalog.json").is_file():
                result.append(MemoryScope(kind))
        projects = self.root / "projects"
        if projects.is_dir():
            for project in sorted(projects.iterdir()):
                for kind in ("curated", "inbox"):
                    if (project / kind / "catalog.json").is_file():
                        result.append(MemoryScope(kind, project.name))
        agents = self.root / "agents"
        if agents.is_dir():
            for agent in sorted(agents.iterdir()):
                if (agent / "scratch" / "catalog.json").is_file():
                    result.append(MemoryScope("scratch", agent.name))
        return result

    def _sync_index(
        self, index: MemoryIndex, scope: MemoryScope, catalog: dict[str, Any]
    ) -> None:
        entries = [
            self._entry(scope, document_id, entry)
            for document_id, entry in sorted(catalog["documents"].items())
        ]
        fingerprint = MemoryIndex.fingerprint(entries)
        if index.scope_fingerprint(scope.kind, scope.namespace) == fingerprint:
            return
        documents = []
        for entry in entries:
            if entry.get("deleted") or entry.get("redacted"):
                continue
            document = self._read_object(scope, entry["sha256"])
            documents.append(
                {
                    **entry,
                    "title": document.metadata["title"],
                    "summary": document.metadata["summary"],
                    "kind": document.metadata["kind"],
                    "classification": document.metadata["classification"],
                    "tags": document.metadata.get("tags", []),
                    "body": document.body,
                }
            )
        index.replace_scope(scope.kind, scope.namespace, fingerprint, documents)

    def search(
        self,
        actor: Actor,
        query: str = "",
        *,
        scope: MemoryScope | None = None,
        kind: str | None = None,
        tags: Iterable[str] = (),
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise MemoryError("Search limit must be between 1 and 100")
        if self._index is None:
            self._index = MemoryIndex(self._index_path)
        scopes = [scope] if scope else self._discover_scopes()
        allowed = []
        for candidate in scopes:
            if scope is not None:
                MemoryPolicy.require_read(actor, candidate)
            elif not MemoryPolicy.can_read(actor, candidate):
                continue
            catalog = self._load_catalog(candidate)
            self._sync_index(self._index, candidate, catalog)
            allowed.append(candidate)
        required_tags = set(tags)
        results = []
        for item in self._index.search(query, limit=1000):
            candidate = MemoryScope(item["scope"], item["namespace"])
            if candidate not in allowed:
                continue
            if kind and item["kind"] != kind:
                continue
            if not required_tags.issubset(set(item["tags"])):
                continue
            results.append(item)
            if len(results) >= limit:
                break
        return results

    def verify(self, *, raise_on_error: bool = True) -> list[str]:
        errors = []
        for scope in self._discover_scopes():
            try:
                catalog = self._load_catalog(scope)
                for document_id, entry in catalog["documents"].items():
                    if entry.get("redacted"):
                        continue
                    try:
                        document = self._read_object(scope, entry["sha256"])
                        if document.document_id != document_id:
                            raise MemoryError("Document id does not match catalog")
                        record = self._read_version_record(
                            scope, document_id, entry["version_id"]
                        )
                        if record["sha256"] != entry["sha256"]:
                            raise MemoryError("Version hash does not match catalog")
                    except (MemoryError, KeyError) as exc:
                        errors.append(f"{scope.kind}/{scope.namespace}/{document_id}: {exc}")
                audit = self._scope_root(scope) / "audit.jsonl"
                if audit.exists():
                    previous = None
                    for number, line in enumerate(audit.read_bytes().splitlines(), 1):
                        event = json.loads(line)
                        if event.get("prev_sha256") != previous:
                            raise MemoryError(f"Audit chain mismatch at line {number}")
                        previous = sha256_bytes(line)
            except (MemoryError, json.JSONDecodeError, StorageError) as exc:
                errors.append(f"{scope.kind}/{scope.namespace}: {exc}")
        if errors and raise_on_error:
            raise MemoryError("Memory verification failed:\n" + "\n".join(errors))
        return errors

    def export(self, actor: Actor, destination: str | Path) -> dict[str, Any]:
        MemoryPolicy.require_human(actor, "Memory export")
        target = Path(destination).expanduser()
        if target.exists() and (
            target.is_symlink() or not target.is_dir() or any(target.iterdir())
        ):
            raise MemoryError("Export destination must be absent or empty")
        staging = target.with_name(f".{target.name}.staging-{uuid.uuid4().hex}")
        staging.mkdir(parents=True, mode=0o700)
        manifest = {"schema_version": 1, "created_at": utc_now(), "documents": []}
        try:
            for scope in self._discover_scopes():
                catalog = self._load_catalog(scope)
                for document_id, entry in sorted(catalog["documents"].items()):
                    if entry.get("deleted") or entry.get("redacted"):
                        continue
                    document = self._read_object(scope, entry["sha256"])
                    relative = Path(scope.kind) / scope.namespace / f"{document_id}.md"
                    output = staging / relative
                    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    atomic_write_bytes(output, document.to_bytes(), mode=0o600)
                    manifest["documents"].append(
                        {
                            "path": relative.as_posix(),
                            "scope": scope.kind,
                            "namespace": scope.namespace,
                            "document_id": document_id,
                            "sha256": entry["sha256"],
                            "version_id": entry["version_id"],
                        }
                    )
            if len(manifest["documents"]) > 10_000:
                raise MemoryError("Export contains too many documents")
            atomic_write_json(staging / "manifest.json", manifest, mode=0o600)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.rmdir()
            os.replace(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return manifest

    @staticmethod
    def _read_import_entry(root: Path, relative: Path) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(root, directory_flags)
        try:
            for part in relative.parts[:-1]:
                next_descriptor = os.open(part, directory_flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
            file_descriptor = os.open(relative.name, flags, dir_fd=descriptor)
            try:
                info = os.fstat(file_descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_size > 100_000:
                    raise MemoryError("Import entries must be bounded regular files")
                chunks = []
                remaining = 100_001
                while remaining:
                    chunk = os.read(file_descriptor, min(65536, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                return b"".join(chunks)
            finally:
                os.close(file_descriptor)
        finally:
            os.close(descriptor)

    def import_(
        self,
        actor: Actor,
        source: str | Path,
        *,
        expected: dict[str, str | None] | None = None,
    ) -> list[dict[str, Any]]:
        MemoryPolicy.require_human(actor, "Memory import")
        supplied = Path(source).expanduser()
        if supplied.is_symlink():
            raise MemoryError("Import root cannot be a symlink")
        root = supplied.resolve()
        manifest_bytes = self._read_import_entry(root, Path("manifest.json"))
        try:
            manifest = json.loads(manifest_bytes)
        except json.JSONDecodeError as exc:
            raise MemoryError("Invalid import manifest JSON") from exc
        manifest_sha256 = sha256_bytes(manifest_bytes)
        documents = manifest.get("documents", [])
        if not isinstance(documents, list) or len(documents) > 10_000:
            raise MemoryError("Invalid or excessive import manifest")
        expected = expected or {}
        grouped: dict[MemoryScope, list[MemoryChange]] = {}
        for item in documents:
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
                raise MemoryError("Unsafe import path")
            data = self._read_import_entry(root, relative)
            if sha256_bytes(data) != item["sha256"]:
                raise MemoryError(f"Import hash mismatch: {relative}")
            document = MemoryDocument.from_bytes(data)
            if document.document_id != item["document_id"]:
                raise MemoryError("Import document identity mismatch")
            scope = MemoryScope(item["scope"], item["namespace"])
            MemoryPolicy.require_write(actor, scope)
            key = f"{scope.kind}/{scope.namespace}/{document.document_id}"
            current = self._load_catalog(scope)["documents"].get(document.document_id)
            current_hash = current.get("sha256") if current else None
            if current is not None and key not in expected:
                raise MemoryConflictError(
                    f"Import requires an explicit expected hash for existing memory: {key}"
                )
            required = expected.get(key)
            if required != current_hash:
                raise MemoryConflictError(f"Import would overwrite a newer head: {key}")
            grouped.setdefault(scope, []).append(
                MemoryChange(
                    document=document,
                    expected_sha256=current_hash,
                    operation="imported",
                    provenance={"imported_version": item["version_id"]},
                )
            )
        versions = []
        for scope, changes in grouped.items():
            for start in range(0, len(changes), 100):
                versions.extend(
                    self.commit(
                        scope,
                        changes[start : start + 100],
                        actor,
                        provenance={"source_manifest_sha256": manifest_sha256},
                    )
                )
        return versions


class SkillStore:
    def __init__(self, memory: MemoryStore):
        self.memory = memory
        self.scope = MemoryScope("skills")

    def search(self, actor: Actor, query: str = "", *, limit: int = 20) -> list[dict[str, Any]]:
        return self.memory.search(actor, query, scope=self.scope, kind="skill", limit=limit)

    def read(self, skill_id: str, actor: Actor) -> tuple[MemoryDocument, dict[str, Any]]:
        return self.memory.read(self.scope, skill_id, actor)
