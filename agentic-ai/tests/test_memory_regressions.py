from __future__ import annotations

import json
import multiprocessing
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentic_ai.documents import MemoryDocument
from agentic_ai.errors import IdentityError, MemoryConflictError, MemoryError, MemoryPermissionError
from agentic_ai.identity import Actor, MemoryScope
from agentic_ai.memory import MemoryStore
from agentic_ai.storage import read_json


HUMAN = Actor(kind="human", os_user="roman")
AGENT_A = Actor(kind="agent", os_user="ai-agent", agent_id="agent-a", projects=("demo",))
AGENT_B = Actor(kind="agent", os_user="ai-agent", agent_id="agent-b", projects=("demo",))
ORG = MemoryScope("org")
SCRATCH_A = MemoryScope("scratch", "agent-a")
SCRATCH_B = MemoryScope("scratch", "agent-b")


def document(doc_id="lesson", body="content", **metadata):
    return MemoryDocument(
        {
            "id": doc_id,
            "title": metadata.pop("title", "A lesson"),
            "kind": "lesson",
            "summary": "A summary",
            "classification": "private",
            "review_status": "curated",
            **metadata,
        },
        body,
    )


def same_mutation(root, body, mutation_id, queue):
    try:
        with mock.patch("agentic_ai.identity.current_username", return_value="ai-agent"):
            MemoryStore(root).put(
                SCRATCH_A,
                document(body=body, review_status="unreviewed"),
                AGENT_A,
                operation="created",
                mutation_id=mutation_id,
            )
        queue.put("ok")
    except Exception as exc:
        queue.put(exc.__class__.__name__)


class FaultRedactionStore(MemoryStore):
    def _checkpoint(self, name, operation):
        if name == "committed":
            raise RuntimeError("crash after redacted head commit")


class MemoryRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "memory"
        self.store = MemoryStore(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_forged_human_actor_cannot_write_as_agent_os_user(self):
        with mock.patch("agentic_ai.identity.current_username", return_value="ai-agent"):
            with self.assertRaises(IdentityError):
                self.store.put(ORG, document(), HUMAN, operation="created")

    def test_secret_scan_covers_front_matter(self):
        with self.assertRaises(MemoryPermissionError):
            document(title="api_key = abcdefghijklmnopqrstuvwxyz")

    def test_same_mutation_id_with_different_payload_has_one_winner(self):
        mutation_id = "33333333-3333-4333-8333-333333333333"
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        processes = [
            context.Process(target=same_mutation, args=(str(self.root), body, mutation_id, queue))
            for body in ("first", "second")
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(30)
        results = sorted(queue.get(timeout=5) for _ in processes)
        self.assertEqual(results, ["MemoryConflictError", "ok"])
        self.assertEqual(len(self.store.history(SCRATCH_A, "lesson", HUMAN)), 1)

    def test_interrupted_redaction_fails_closed_and_resumes(self):
        created = self.store.put(ORG, document(body="sensitive"), HUMAN, operation="created")
        failing = FaultRedactionStore(self.root)
        with self.assertRaisesRegex(RuntimeError, "crash"):
            failing.redact(ORG, "lesson", HUMAN, reason="test")
        with self.assertRaises(MemoryPermissionError):
            self.store.read_version(ORG, "lesson", "v000001", HUMAN)
        self.store.redact(ORG, "lesson", HUMAN, reason="test")
        self.assertFalse(
            (self.root / "org" / "objects" / created["sha256"][:2] / f"{created['sha256']}.md").exists()
        )
        with mock.patch("agentic_ai.identity.current_username", return_value="ai-agent"):
            with self.assertRaises((IdentityError, MemoryConflictError)):
                self.store.put(ORG, document(body="resurrected"), AGENT_A)

    def test_agent_cannot_forge_redacted_operation_or_traverse_history(self):
        with mock.patch("agentic_ai.identity.current_username", return_value="ai-agent"):
            with self.assertRaises(IdentityError):
                self.store.put(SCRATCH_A, document(), AGENT_A, operation="redacted")
        with self.assertRaises(MemoryError):
            self.store.history(ORG, "../../projects/demo/curated", HUMAN)
        with self.assertRaises(MemoryError):
            self.store.history(ORG, "/tmp", HUMAN)

    def test_global_search_skips_unauthorized_scopes(self):
        with mock.patch("agentic_ai.identity.current_username", return_value="ai-agent"):
            self.store.put(SCRATCH_A, document(body="agent a"), AGENT_A, operation="created")
            self.store.put(SCRATCH_B, document(body="agent b"), AGENT_B, operation="created")
        results = self.store.search(AGENT_A, "agent")
        self.assertEqual([item["namespace"] for item in results], ["agent-a"])

    def test_pending_visible_operation_is_audited_by_later_writer(self):
        created = self.store.put(ORG, document(), HUMAN, operation="created")
        # Inject after the catalog becomes visible but before its audit/terminal record.
        class AfterCatalog(MemoryStore):
            def _checkpoint(self, name, operation):
                if name == "after_catalog":
                    raise RuntimeError("stop")

        failing = AfterCatalog(self.root)
        with self.assertRaises(RuntimeError):
            failing.put(ORG, document(body="v2"), HUMAN, expected_sha256=created["sha256"])
        visible = read_json(self.root / "org" / "catalog.json")["documents"]["lesson"]["sha256"]
        second = self.store.put(ORG, document(body="v3"), HUMAN, expected_sha256=visible)
        self.assertEqual(second["version_id"], "v000003")
        audit = [json.loads(line)["mutation_id"] for line in (self.root / "org" / "audit.jsonl").read_text().splitlines()]
        self.assertEqual(len(audit), 3)
        self.assertEqual(self.store.verify(), [])

    def test_torn_final_audit_append_is_repaired(self):
        self.store.put(ORG, document(), HUMAN, operation="created")
        audit = self.root / "org" / "audit.jsonl"
        with audit.open("ab") as handle:
            handle.write(b'{"truncated"')
        self.store.put(ORG, document("second"), HUMAN, operation="created")
        self.assertEqual(self.store.verify(), [])

    def test_group_shared_modes(self):
        self.store.put(ORG, document(), HUMAN, operation="created")
        lock = self.root / "org" / "locks" / "catalog.lock"
        obj = next((self.root / "org" / "objects").glob("*/*.md"))
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o660)
        self.assertEqual(stat.S_IMODE(obj.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE((self.root / "org").stat().st_mode), 0o750)

    def test_import_symlink_stale_head_and_large_export(self):
        for index in range(101):
            self.store.put(ORG, document(f"doc-{index}"), HUMAN, operation="created")
        export = Path(self.temporary.name) / "export"
        self.store.export(HUMAN, export)
        imported = MemoryStore(Path(self.temporary.name) / "imported")
        imported.import_(HUMAN, export)
        self.assertEqual(len(imported.search(HUMAN, limit=100)), 100)
        self.assertEqual(len(imported.search(HUMAN, query="doc-100", limit=100)), 1)

        current = imported._load_catalog(ORG)["documents"]["doc-0"]["sha256"]
        imported.put(ORG, document("doc-0", body="new local"), HUMAN, expected_sha256=current)
        with self.assertRaises(MemoryConflictError):
            imported.import_(HUMAN, export)

        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (outside / "global").mkdir()
        source_entry = export / "org" / "global" / "doc-0.md"
        target_entry = outside / "global" / "doc-0.md"
        target_entry.write_bytes(source_entry.read_bytes())
        source_entry.parent.rename(outside / "original-global")
        source_entry.parent.symlink_to(outside / "global", target_is_directory=True)
        with self.assertRaises((MemoryError, OSError)):
            MemoryStore(Path(self.temporary.name) / "another").import_(HUMAN, export)


if __name__ == "__main__":
    unittest.main()
