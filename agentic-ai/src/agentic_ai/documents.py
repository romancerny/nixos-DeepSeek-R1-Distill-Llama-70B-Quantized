from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from typing import Any

from .errors import MemoryError, MemoryPermissionError


DOCUMENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
NAMESPACE = DOCUMENT_ID
CLASSIFICATIONS = {"public", "shareable", "internal", "private"}
KINDS = {"guidance", "note", "lesson", "skill", "preference", "reference"}
REVIEW_STATES = {"curated", "unreviewed", "rejected"}
MAX_DOCUMENT_BYTES = 100_000
MAX_FRONT_MATTER_BYTES = 16_384
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*"
        r"[\"']?[A-Za-z0-9_+/=-]{16,}"
    ),
)


def validate_document_id(value: str) -> str:
    if not isinstance(value, str) or not DOCUMENT_ID.fullmatch(value):
        raise MemoryError(f"Invalid document id: {value!r}")
    return value


def validate_namespace(value: str) -> str:
    if not isinstance(value, str) or not NAMESPACE.fullmatch(value):
        raise MemoryError(f"Invalid memory namespace: {value!r}")
    return value


def reject_secrets(text: str) -> None:
    for pattern in _SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            raise MemoryPermissionError(
                "Memory appears to contain a credential; rotate it if real and "
                "store credentials in a secret manager instead"
            )


def _toml_value(value: Any) -> str:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return json.dumps(value, ensure_ascii=False)
    raise MemoryError(f"Unsupported front-matter value: {value!r}")


@dataclass(frozen=True)
class MemoryDocument:
    metadata: dict[str, Any]
    body: str

    def __post_init__(self) -> None:
        validate_document_id(self.metadata.get("id"))
        for required in ("title", "kind", "summary", "classification"):
            if not isinstance(self.metadata.get(required), str) or not self.metadata[required].strip():
                raise MemoryError(f"Memory metadata requires non-empty {required}")
        if self.metadata["kind"] not in KINDS:
            raise MemoryError(f"Unknown memory kind: {self.metadata['kind']}")
        if self.metadata["classification"] not in CLASSIFICATIONS:
            raise MemoryError(f"Unknown classification: {self.metadata['classification']}")
        tags = self.metadata.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise MemoryError("Memory tags must be an array of strings")
        review = self.metadata.get("review_status", "unreviewed")
        if review not in REVIEW_STATES:
            raise MemoryError(f"Unknown review status: {review}")
        if not isinstance(self.body, str):
            raise MemoryError("Memory body must be text")
        if len(self.to_bytes()) > MAX_DOCUMENT_BYTES:
            raise MemoryError(f"Memory exceeds {MAX_DOCUMENT_BYTES} bytes")
        reject_secrets(self.body)

    @property
    def document_id(self) -> str:
        return self.metadata["id"]

    def to_bytes(self) -> bytes:
        metadata = dict(self.metadata)
        metadata.setdefault("tags", [])
        metadata.setdefault("review_status", "unreviewed")
        metadata.setdefault("schema_version", 1)
        front = "\n".join(
            f"{key} = {_toml_value(metadata[key])}" for key in sorted(metadata)
        )
        if len(front.encode("utf-8")) > MAX_FRONT_MATTER_BYTES:
            raise MemoryError("Memory front matter is too large")
        body = self.body if self.body.endswith("\n") or not self.body else self.body + "\n"
        return f"+++\n{front}\n+++\n\n{body}".encode("utf-8")

    def sha256(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()

    @classmethod
    def from_bytes(cls, data: bytes) -> "MemoryDocument":
        if len(data) > MAX_DOCUMENT_BYTES:
            raise MemoryError("Memory document is too large")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MemoryError("Memory document is not UTF-8") from exc
        if not text.startswith("+++\n"):
            raise MemoryError("Memory document must start with TOML front matter")
        end = text.find("\n+++\n", 4)
        if end < 0:
            raise MemoryError("Memory front matter is not terminated")
        front = text[4:end]
        body = text[end + 5 :]
        if body.startswith("\n"):
            body = body[1:]
        try:
            metadata = tomllib.loads(front)
        except tomllib.TOMLDecodeError as exc:
            raise MemoryError(f"Invalid memory front matter: {exc}") from exc
        return cls(metadata=metadata, body=body)

    @classmethod
    def from_text(cls, text: str) -> "MemoryDocument":
        return cls.from_bytes(text.encode("utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
