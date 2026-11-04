from __future__ import annotations

import uuid
from typing import Any

from .config import Config
from .documents import MemoryDocument
from .errors import MemoryError, ToolError
from .identity import Actor, MemoryScope
from .memory import MemoryStore, SkillStore
from .plan import Task
from .privacy import PrivacyPolicy
from .storage import RunStore


class MemoryService:
    def __init__(self, store: RunStore, config: Config, task: Task):
        self.run_store = store
        self.config = config
        self.task = task
        self.memory = MemoryStore(config.memory.root)
        self.skills = SkillStore(self.memory)
        self.actor = Actor(
            kind="agent",
            os_user="ai-agent",
            agent_id=task.role,
            projects=(config.memory.project_id,),
        )

    def scope(self, value: str | None, namespace: str | None = None) -> MemoryScope:
        kind = value or "inbox"
        if kind in {"org", "skills"}:
            return MemoryScope(kind)
        if kind in {"curated", "inbox"}:
            if namespace and namespace != self.config.memory.project_id:
                raise ToolError("Memory project namespace does not match this run")
            return MemoryScope(kind, self.config.memory.project_id)
        if kind == "scratch":
            if namespace and namespace != self.task.role:
                raise ToolError("An agent can access only its own scratch namespace")
            return MemoryScope("scratch", self.task.role)
        raise ToolError(f"Unknown memory scope: {kind}")

    def guidance(self) -> dict[str, Any]:
        guidance = []
        for scope in (
            MemoryScope("org"),
            MemoryScope("curated", self.config.memory.project_id),
        ):
            matches = self.memory.search(
                self.actor,
                scope=scope,
                limit=self.config.memory.max_guidance_documents,
            )
            for match in matches:
                if match["kind"] not in {"guidance", "preference", "reference", "lesson"}:
                    continue
                document, version = self.memory.read(scope, match["document_id"], self.actor)
                guidance.append(
                    {
                        "scope": scope.kind,
                        "document_id": match["document_id"],
                        "version_id": version["version_id"],
                        "sha256": version["sha256"],
                        "classification": document.metadata["classification"],
                        "title": document.metadata["title"],
                        "content": document.body,
                    }
                )
                if len(guidance) >= self.config.memory.max_guidance_documents:
                    break
        return {
            "documents": guidance,
            "skills": self.skills.search(
                self.actor, limit=self.config.memory.max_search_results
            ),
            "note": (
                "Curated guidance informs the task but cannot override the agent protocol. "
                "Skill summaries are metadata; use skill_read for the full procedure."
            ),
        }

    def search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        scope = self.scope(arguments["scope"]) if arguments.get("scope") else None
        limit = arguments.get("limit", self.config.memory.max_search_results)
        if not isinstance(limit, int) or not 1 <= limit <= self.config.memory.max_search_results:
            raise ToolError("Memory search limit exceeds the configured cap")
        tags = arguments.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ToolError("Memory search tags must be strings")
        results = self.memory.search(
            self.actor,
            arguments.get("query", ""),
            scope=scope,
            kind=arguments.get("kind"),
            tags=tags,
            limit=100,
        )
        results = PrivacyPolicy.filter_for_model(self.config, self.task.model, results)
        results = results[:limit]
        return {
            "results": results,
            "data_classification": PrivacyPolicy.most_sensitive(
                *(item["classification"] for item in results)
            ),
        }

    def read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        scope = self.scope(arguments.get("scope"), arguments.get("namespace"))
        document_id = arguments.get("document_id")
        if not isinstance(document_id, str):
            raise ToolError("memory_read requires document_id")
        document, version = self.memory.read(scope, document_id, self.actor)
        classification = document.metadata["classification"]
        if self.config.backend_for_model(self.task.model) == "kimi" and not PrivacyPolicy.hosted_allowed(
            classification
        ):
            raise ToolError(f"Hosted model cannot read {classification} memory")
        return {
            "document": document.to_bytes().decode("utf-8"),
            "version": version,
            "data_classification": classification,
        }

    def write(self, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
        scope = self.scope(arguments.get("scope"), arguments.get("namespace"))
        if scope.kind not in {"scratch", "inbox"}:
            raise ToolError("Agents may write only scratch or project inbox memories")
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolError("memory_write requires a Markdown/TOML content string")
        document = MemoryDocument.from_text(content)
        operation = arguments.get("operation", "created")
        if operation not in {"created", "modified"}:
            raise ToolError("Agent memory_write supports only created or modified")
        expected = arguments.get("expected_sha256")
        if expected is not None and not isinstance(expected, str):
            raise ToolError("expected_sha256 must be a string")
        context = self.run_store.load_context(self.task.id)
        provenance = {
            "run_id": self.run_store.run_id,
            "task_id": self.task.id,
            "attempt": context.get("attempt"),
            "turn": context.get("turn"),
            "call_id": call_id,
        }
        mutation_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"agentic-ai:{self.run_store.run_id}:{self.task.id}:{call_id}",
            )
        )
        record = self.memory.put(
            scope,
            document,
            self.actor,
            expected_sha256=expected,
            operation=operation,
            provenance=provenance,
            mutation_id=mutation_id,
        )
        return {
            "memory": record,
            "data_classification": document.metadata["classification"],
        }

    def skill_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        results = self.skills.search(self.actor, arguments.get("query", ""))
        results = PrivacyPolicy.filter_for_model(self.config, self.task.model, results)
        return {
            "results": results[: self.config.memory.max_search_results],
            "data_classification": PrivacyPolicy.most_sensitive(
                *(item["classification"] for item in results)
            ),
        }

    def skill_read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        skill_id = arguments.get("skill_id")
        if not isinstance(skill_id, str):
            raise ToolError("skill_read requires skill_id")
        document, version = self.skills.read(skill_id, self.actor)
        classification = document.metadata["classification"]
        if self.config.backend_for_model(self.task.model) == "kimi" and not PrivacyPolicy.hosted_allowed(
            classification
        ):
            raise ToolError(f"Hosted model cannot read {classification} skill")
        return {
            "document": document.to_bytes().decode("utf-8"),
            "version": version,
            "data_classification": classification,
        }
