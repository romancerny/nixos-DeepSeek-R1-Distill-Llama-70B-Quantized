from __future__ import annotations

import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentic_ai.documents import MemoryDocument
from agentic_ai.errors import (
    IdentityError,
    MemoryConflictError,
    MemoryError,
    MemoryNotFoundError,
    MemoryPermissionError,
)
from agentic_ai.identity import Actor, MemoryScope, require_current_user
from agentic_ai.memory import MemoryChange, MemoryStore, SkillStore


HUMAN = Actor(kind="human", os_user="roman", display_name="Test Human")
AGENT = Actor(kind="agent", os_user="ai-agent", agent_id="agent-a", projects=("demo",))
OTHER_AGENT = Actor(kind="agent", os_user="ai-agent", agent_id="agent-b", projects=("demo",))
ORG = MemoryScope("org")
SKILLS = MemoryScope("skills")
CURATED = MemoryScope("curated", "demo")
INBOX = MemoryScope("inbox", "demo")
SCRATCH = MemoryScope("scratch", "agent-a")


def document(doc_id: str = "lesson", body: str = "Use deterministic checks.", **overrides):
    metadata = {
        "id": doc_id,
        "title": overrides.pop("title", doc_id.replace("-", " ").title()),
        "kind": overrides.pop("kind", "lesson"),
        "summary": overrides.pop("summary", "A concise searchable summary"),
        "classification": overrides.pop("classification", "private"),
        "tags": overrides.pop("tags", ["testing"]),
        "review_status": overrides.pop("review_status", "curated"),
        **overrides,
    }
    return MemoryDocument(metadata=metadata, body=body)


def concurrent_update(root: str, body: str, expected: str, queue) -> None:
    try:
        store = MemoryStore(root)
        with mock.patch("agentic_ai.identity.current_username", return_value="ai-agent"):
            result = store.put(
            SCRATCH,
            document(body=body, review_status="unreviewed"),
            AGENT,
            expected_sha256=expected,
        )
        queue.put(("ok", result["version_id"]))
    except Exception as exc:  # multiprocessing assertion transport
        queue.put((exc.__class__.__name__, str(exc)))


class FaultMemoryStore(MemoryStore):
    fail_at = None

    def _checkpoint(self, name, operation):
        if name == self.fail_at:
            raise RuntimeError(f"injected {name}")


class DocumentTests(unittest.TestCase):
    def test_toml_markdown_round_trip_and_secret_rejection(self):
        original = document(tags=["alpha", "beta"], body="A body with **Markdown**.")
        parsed = MemoryDocument.from_bytes(original.to_bytes())
        self.assertEqual(parsed.metadata["id"], "lesson")
        self.assertEqual(parsed.metadata["tags"], ["alpha", "beta"])
        self.assertEqual(parsed.body, "A body with **Markdown**.\n")
        self.assertEqual(parsed.sha256(), original.sha256())
        with self.assertRaises(MemoryPermissionError):
            document(body="api_key = abcdefghijklmnopqrstuvwxyz")
        with self.assertRaises(MemoryError):
            MemoryDocument.from_text("not a memory")

    def test_effective_os_identity_is_enforced(self):
        with mock.patch("agentic_ai.identity.current_username", return_value="roman"):
            require_current_user("roman")
            with self.assertRaises(IdentityError):
                Actor.agent("agent-a")
        with mock.patch("agentic_ai.identity.current_username", return_value="ai-agent"):
            Actor.agent("agent-a")
            with self.assertRaises(IdentityError):
                Actor.human()


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "memory"
        self.store = MemoryStore(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_versioned_read_search_update_rollback_and_delete(self):
        created = self.store.put(ORG, document(), HUMAN, operation="created")
        self.assertEqual(created["version_id"], "v000001")
        read, head = self.store.read(ORG, "lesson", AGENT)
        self.assertIn("deterministic", read.body)
        self.assertEqual(head["actor"]["os_user"], "roman")
        self.assertEqual(head["sha256"], created["sha256"])

        with self.assertRaises(MemoryConflictError):
            self.store.put(ORG, document(body="Lost update"), HUMAN)

        updated = self.store.put(
            ORG,
            document(body="Use deterministic checks and evidence."),
            HUMAN,
            expected_sha256=created["sha256"],
        )
        self.assertEqual(updated["version_id"], "v000002")
        self.assertEqual(len(self.store.history(ORG, "lesson", AGENT)), 2)
        results = self.store.search(AGENT, "evidence")
        self.assertEqual(results[0]["document_id"], "lesson")
        self.assertNotIn("body", results[0])

        rolled_back = self.store.rollback(
            ORG,
            "lesson",
            "v000001",
            HUMAN,
            expected_sha256=updated["sha256"],
            reason="The later wording was less precise",
        )
        self.assertEqual(rolled_back["operation"], "rollback")
        self.assertEqual(rolled_back["provenance"]["rollback_to"], "v000001")
        current, _ = self.store.read(ORG, "lesson", HUMAN)
        self.assertEqual(current.body, "Use deterministic checks.\n")

        deleted = self.store.delete(
            ORG, "lesson", HUMAN, expected_sha256=rolled_back["sha256"]
        )
        self.assertEqual(deleted["operation"], "deleted")
        with self.assertRaises(MemoryNotFoundError):
            self.store.read(ORG, "lesson", HUMAN)
        self.assertEqual(self.store.verify(), [])

    def test_scope_permissions_low_trust_inbox_and_skills(self):
        with self.assertRaises(IdentityError):
            self.store.put(ORG, document(), AGENT, operation="created")
        with mock.patch("agentic_ai.identity.current_username", return_value="ai-agent"):
            self.store.put(
                INBOX,
                document(body="A model claims this is approved."),
                AGENT,
                operation="created",
            )
            self.store.put(
                SCRATCH,
                document(body="Private working note", review_status="unreviewed"),
                AGENT,
                operation="created",
            )
        _, record = self.store.read(INBOX, "lesson", AGENT)
        self.assertEqual(record["actor"]["agent_id"], "agent-a")
        stored, _ = self.store.read(INBOX, "lesson", HUMAN)
        self.assertEqual(stored.metadata["review_status"], "unreviewed")
        with self.assertRaises(IdentityError):
            self.store.read(SCRATCH, "lesson", OTHER_AGENT)

        self.store.put(
            SKILLS,
            document(
                "memory-curation",
                kind="skill",
                summary="Review evidence before promoting memories",
                body="1. Verify citations.\n2. Inspect the diff.",
            ),
            HUMAN,
            operation="created",
        )
        skills = SkillStore(self.store)
        summaries = skills.search(AGENT, "evidence")
        self.assertEqual(summaries[0]["document_id"], "memory-curation")
        self.assertNotIn("body", summaries[0])
        skill, _ = skills.read("memory-curation", AGENT)
        self.assertIn("Verify citations", skill.body)

    def test_batch_commit_and_interrupted_catalog_commit_recovers(self):
        first = document("first", body="First version")
        second = document("second", body="Second version")
        mutation_id = "11111111-1111-4111-8111-111111111111"
        versions = self.store.commit(
            CURATED,
            [
                # Both creates have an explicit absent precondition.
                MemoryChange(first, operation="created"),
                MemoryChange(second, operation="created"),
            ],
            HUMAN,
            mutation_id=mutation_id,
        )
        self.assertEqual(len(versions), 2)
        repeated = self.store.commit(
            CURATED,
            [
                MemoryChange(first, operation="created"),
                MemoryChange(second, operation="created"),
            ],
            HUMAN,
            mutation_id=mutation_id,
        )
        self.assertEqual(repeated, versions)
        self.assertEqual(len(self.store.history(CURATED, "first", HUMAN)), 1)

        updated = document("first", body="Updated after a crash")
        update_id = "22222222-2222-4222-8222-222222222222"
        failing = FaultMemoryStore(self.root)
        failing.fail_at = "after_catalog"
        with self.assertRaisesRegex(RuntimeError, "injected after_catalog"):
            failing.put(
                CURATED,
                updated,
                HUMAN,
                expected_sha256=versions[0]["sha256"],
                mutation_id=update_id,
            )
        recovered = self.store.put(
            CURATED,
            updated,
            HUMAN,
            expected_sha256=versions[0]["sha256"],
            mutation_id=update_id,
        )
        self.assertEqual(recovered["version_id"], "v000002")
        audit_lines = (self.root / "projects" / "demo" / "curated" / "audit.jsonl").read_text().splitlines()
        matching = [line for line in audit_lines if json.loads(line)["mutation_id"] == update_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(self.store.verify(), [])

    def test_concurrent_writers_have_exactly_one_winner(self):
        with mock.patch("agentic_ai.identity.current_username", return_value="ai-agent"):
            created = self.store.put(
            SCRATCH,
            document(review_status="unreviewed"),
            AGENT,
            operation="created",
        )
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        processes = [
            context.Process(
                target=concurrent_update,
                args=(str(self.root), body, created["sha256"], queue),
            )
            for body in ("Writer A", "Writer B")
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(30)
        results = [queue.get(timeout=5) for _ in processes]
        self.assertEqual(sorted(result[0] for result in results), ["MemoryConflictError", "ok"])
        self.assertEqual(len(self.store.history(SCRATCH, "lesson", HUMAN)), 2)
        self.assertEqual(self.store.verify(), [])

    def test_redaction_removes_payload_and_preserves_accountability(self):
        created = self.store.put(ORG, document(body="Sensitive text"), HUMAN, operation="created")
        marker = self.store.redact(ORG, "lesson", HUMAN, reason="Accidental sensitive content")
        self.assertTrue(marker["redaction_id"])
        with self.assertRaises(MemoryPermissionError):
            self.store.read(ORG, "lesson", HUMAN)
        with self.assertRaises(MemoryPermissionError):
            self.store.read_version(ORG, "lesson", "v000001", HUMAN)
        history = self.store.history(ORG, "lesson", HUMAN)
        self.assertTrue(all(record["payload_redacted"] for record in history))
        self.assertFalse((self.root / "org" / "objects" / created["sha256"][:2] / f"{created['sha256']}.md").exists())
        self.assertEqual(self.store.verify(), [])

    def test_export_import_hash_verification_and_stale_precondition(self):
        self.store.put(ORG, document(), HUMAN, operation="created")
        export_root = Path(self.temporary.name) / "export"
        manifest = self.store.export(HUMAN, export_root)
        self.assertEqual(len(manifest["documents"]), 1)
        imported_root = Path(self.temporary.name) / "imported"
        imported = MemoryStore(imported_root)
        versions = imported.import_(HUMAN, export_root)
        self.assertEqual(versions[0]["operation"], "imported")
        read, _ = imported.read(ORG, "lesson", HUMAN)
        self.assertEqual(read.body, "Use deterministic checks.\n")
        with self.assertRaises(MemoryConflictError):
            imported.import_(
                HUMAN,
                export_root,
                expected={"org/global/lesson": "0" * 64},
            )

        entry_path = export_root / "org" / "global" / "lesson.md"
        entry_path.write_text("tampered", encoding="utf-8")
        with self.assertRaises(MemoryError):
            MemoryStore(Path(self.temporary.name) / "other").import_(HUMAN, export_root)

    def test_audit_tampering_is_detected(self):
        self.store.put(ORG, document(), HUMAN, operation="created")
        self.store.put(ORG, document("second"), HUMAN, operation="created")
        audit = self.root / "org" / "audit.jsonl"
        lines = audit.read_text(encoding="utf-8").splitlines()
        second = json.loads(lines[1])
        second["prev_sha256"] = "0" * 64
        lines[1] = json.dumps(second)
        audit.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertTrue(self.store.verify(raise_on_error=False))
        with self.assertRaises(MemoryError):
            self.store.verify()


if __name__ == "__main__":
    unittest.main()
