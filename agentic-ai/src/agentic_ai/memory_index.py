from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable


class MemoryIndex:
    """Disposable per-reader SQLite index; catalogs remain authoritative."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.path.chmod(0o600)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS state (scope TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS documents ("
            "scope TEXT, namespace TEXT, document_id TEXT, title TEXT, summary TEXT, "
            "kind TEXT, classification TEXT, tags TEXT, version_id TEXT, sha256 TEXT, "
            "body TEXT, PRIMARY KEY(scope, namespace, document_id))"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS documents_kind ON documents(kind)"
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    @staticmethod
    def fingerprint(entries: Iterable[dict[str, Any]]) -> str:
        import hashlib

        canonical = json.dumps(list(entries), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def replace_scope(
        self,
        scope: str,
        namespace: str,
        fingerprint: str,
        documents: list[dict[str, Any]],
    ) -> None:
        key = f"{scope}/{namespace}"
        with self.connection:
            self.connection.execute(
                "DELETE FROM documents WHERE scope = ? AND namespace = ?", (scope, namespace)
            )
            self.connection.executemany(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        scope,
                        namespace,
                        item["document_id"],
                        item["title"],
                        item["summary"],
                        item["kind"],
                        item["classification"],
                        json.dumps(item["tags"]),
                        item["version_id"],
                        item["sha256"],
                        item["body"],
                    )
                    for item in documents
                ],
            )
            self.connection.execute(
                "INSERT INTO state(scope, fingerprint) VALUES (?, ?) "
                "ON CONFLICT(scope) DO UPDATE SET fingerprint = excluded.fingerprint",
                (key, fingerprint),
            )

    def scope_fingerprint(self, scope: str, namespace: str) -> str | None:
        row = self.connection.execute(
            "SELECT fingerprint FROM state WHERE scope = ?", (f"{scope}/{namespace}",)
        ).fetchone()
        return row[0] if row else None

    def search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        tokens = re.findall(r"[\w-]+", query.lower())
        clauses = []
        parameters: list[Any] = []
        for token in tokens[:16]:
            clauses.append("(lower(document_id) LIKE ? OR lower(title) LIKE ? OR lower(summary) LIKE ? OR lower(body) LIKE ? OR lower(tags) LIKE ?)")
            value = f"%{token}%"
            parameters.extend([value, value, value, value, value])
        where = " AND ".join(clauses) if clauses else "1 = 1"
        parameters.append(limit)
        rows = self.connection.execute(
            "SELECT scope, namespace, document_id, title, summary, kind, classification, "
            f"tags, version_id, sha256 FROM documents WHERE {where} "
            "ORDER BY scope, namespace, document_id LIMIT ?",
            parameters,
        ).fetchall()
        return [
            {
                "scope": row[0],
                "namespace": row[1],
                "document_id": row[2],
                "title": row[3],
                "summary": row[4],
                "kind": row[5],
                "classification": row[6],
                "tags": json.loads(row[7]),
                "version_id": row[8],
                "sha256": row[9],
            }
            for row in rows
        ]
