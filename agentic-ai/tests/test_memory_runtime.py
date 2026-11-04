from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agentic_ai.agent import AgentRuntime
from agentic_ai.cli import main
from agentic_ai.config import (
    CommandConfig,
    Config,
    KimiConfig,
    Limits,
    MemoryConfig,
    RoleConfig,
)
from agentic_ai.documents import MemoryDocument
from agentic_ai.identity import Actor, MemoryScope
from agentic_ai.memory import MemoryStore
from agentic_ai.plan import Plan
from agentic_ai.tools import ToolRuntime
from agentic_ai.transcripts import TranscriptBuilder
from agentic_ai.storage import RunStore


HUMAN = Actor(kind="human", os_user="roman")


def research_plan(config: Config):
    return Plan.from_dict(
        {
            "goal": "Learn a reliable project convention",
            "tasks": [
                {
                    "id": "research",
                    "kind": "research",
                    "role": "researcher",
                    "instruction": "Record and retrieve one lesson",
                    "artifact_outputs": ["finding.md"],
                }
            ],
            "acceptance": [
                {"id": "finding", "description": "Finding exists", "type": "file", "path": "artifacts/finding.md"}
            ],
        },
        config,
    )


def memory_document(doc_id="lesson", classification="private", kind="lesson"):
    return MemoryDocument(
        {
            "id": doc_id,
            "title": "Project lesson",
            "kind": kind,
            "summary": "A project lesson",
            "classification": classification,
            "tags": ["project"],
            "review_status": "curated",
        },
        "Always verify the result.",
    )


class MemoryRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.identity = mock.patch(
            "agentic_ai.identity.current_username", return_value="ai-agent"
        )
        self.identity.start()
        self.temporary = tempfile.TemporaryDirectory()
        self.config = Config(
            memory=MemoryConfig(
                enabled=True,
                root=str(Path(self.temporary.name) / "memory"),
                project_id="demo",
                classification="private",
                dreaming_enabled=True,
            )
        )
        self.store = RunStore.create(
            Path(self.temporary.name) / "state",
            "test",
            self.config.to_dict(),
            "run-memory",
        )
        self.plan = research_plan(self.config)
        self.task = self.plan.tasks[0]
        self.agent = AgentRuntime(self.store, self.config, mock.Mock())
        self.agent.start(self.task, self.plan)

    def tearDown(self):
        self.temporary.cleanup()
        self.identity.stop()

    def call(self, tool, arguments, call_id="call-1"):
        return ToolRuntime(self.store, self.config, self.task).execute(
            {"type": "tool_call", "call_id": call_id, "tool": tool, "arguments": arguments}
        )

    def test_inband_write_is_provenanced_idempotent_and_searchable(self):
        content = memory_document().to_bytes().decode()
        result = self.call("memory_write", {"scope": "inbox", "content": content})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["memory"]["provenance"]["run_id"], "run-memory")
        repeated = self.call("memory_write", {"scope": "inbox", "content": content})
        self.assertEqual(repeated["memory"]["version_id"], result["memory"]["version_id"])
        memory = MemoryStore(self.config.memory.root)
        self.assertEqual(len(memory.history(MemoryScope("inbox", "demo"), "lesson", HUMAN)), 1)
        found = self.call("memory_search", {"query": "verify", "scope": "inbox"})
        self.assertTrue(found["ok"], found)
        self.assertEqual(found["results"][0]["document_id"], "lesson")
        read = self.call("memory_read", {"scope": "inbox", "document_id": "lesson"})
        self.assertIn("Always verify", read["document"])
        denied = self.call("memory_write", {"scope": "curated", "content": content}, "call-2")
        self.assertFalse(denied["ok"])

    def test_hosted_model_cannot_read_private_memory(self):
        roles = dict(self.config.roles)
        roles["researcher"] = RoleConfig("k3.1-pro")
        config = replace(
            self.config,
            roles=roles,
            kimi=KimiConfig(enabled=True, approved=True),
            memory=replace(self.config.memory, classification="public"),
        )
        plan = research_plan(config)
        task = plan.tasks[0]
        store = RunStore.create(
            Path(self.temporary.name) / "hosted-state",
            "public goal",
            config.to_dict(),
            "run-hosted-memory",
        )
        memory = MemoryStore(config.memory.root)
        with mock.patch("agentic_ai.identity.current_username", return_value="roman"):
            memory.put(
                MemoryScope("curated", "demo"),
                memory_document(classification="private"),
                HUMAN,
                operation="created",
            )
        agent = AgentRuntime(store, config, mock.Mock(), approve_hosted=True)
        agent.start(task, plan)
        self.assertEqual(store.load_context(task.id)["data_classification"], "private")
        self.assertEqual(agent.step(task), "failed")
        agent.residency.chat.assert_not_called()
        denied = ToolRuntime(store, config, task).execute(
            {
                "type": "tool_call",
                "call_id": "private-read",
                "tool": "memory_read",
                "arguments": {"scope": "curated", "document_id": "lesson"},
            }
        )
        self.assertFalse(denied["ok"])

    def test_transcript_manifest_and_tamper_detection(self):
        attempt = self.store.attempt_dir("research", 1, 1)
        attempt.mkdir(parents=True, exist_ok=True)
        (attempt / "request.json").write_text('{"messages": []}', encoding="utf-8")
        (attempt / "response.raw.txt").write_text('{"type":"final"}', encoding="utf-8")
        self.store.append_event("test_tool", command="unit_tests", return_code=0)
        self.store.update_run(status="succeeded")
        manifest = TranscriptBuilder(self.config).finalize(self.store)
        self.assertTrue(manifest["dream_eligible"])
        loaded_manifest, payload = TranscriptBuilder.load(
            self.store.state_dir, self.store.run_id
        )
        self.assertEqual(loaded_manifest["payload_sha256"], manifest["payload_sha256"])
        self.assertEqual(payload["events"][-1]["type"], "test_tool")
        payload_path = self.store.run_dir / "transcripts" / "payload.json"
        payload_path.write_text("tampered", encoding="utf-8")
        with self.assertRaises(Exception):
            TranscriptBuilder.load(self.store.state_dir, self.store.run_id)

    def test_command_output_is_capped_without_blocking(self):
        config = replace(
            self.config,
            commands={
                "noisy": CommandConfig(
                    (sys.executable, "-c", "print('x' * 100000)")
                )
            },
            limits=replace(self.config.limits, max_command_output_bytes=128),
        )
        result = ToolRuntime(self.store, config, replace(self.task, role="qa")).execute(
            {
                "type": "tool_call",
                "call_id": "noisy",
                "tool": "run_command",
                "arguments": {"command_id": "noisy"},
            }
        )
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["output_truncated"])
        self.assertGreater(result["output_bytes_total"], 100000)
        self.assertLess(result["log_size_bytes"], 300)


class MemoryCliTests(unittest.TestCase):
    def test_human_init_put_search_and_verify(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = str(Path(temporary) / "memory")
            source = Path(temporary) / "lesson.md"
            source.write_bytes(memory_document().to_bytes())
            with mock.patch("agentic_ai.identity.current_username", return_value="roman"):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["memory", "init", "--root", root]), 0)
                    self.assertEqual(
                        main([
                            "memory", "put", "--root", root, "--scope", "org",
                            "--file", str(source), "--operation", "created",
                        ]),
                        0,
                    )
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(
                        main(["memory", "search", "--root", root, "--query", "verify"]),
                        0,
                    )
                self.assertEqual(json.loads(output.getvalue())[0]["document_id"], "lesson")
                self.assertEqual(main(["memory", "verify", "--root", root]), 0)


if __name__ == "__main__":
    unittest.main()
