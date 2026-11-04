from __future__ import annotations

import json
import contextlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agentic_ai.backends import ModelBackends
from agentic_ai.cli import main
from agentic_ai.config import DreamConfig, ExecutionConfig, MemoryConfig, OllamaConfig
from agentic_ai.documents import MemoryDocument
from agentic_ai.dreaming import DreamRunner
from agentic_ai.errors import MemoryConflictError, MemoryNotFoundError
from agentic_ai.identity import Actor, MemoryScope
from agentic_ai.memory import MemoryStore
from agentic_ai.ollama import OllamaClient
from agentic_ai.storage import RunStore, read_json
from agentic_ai.transcripts import TranscriptBuilder
from fake_ollama import FakeOllamaServer, ollama_only_config


HUMAN = Actor(kind="human", os_user="roman")
CURATED = MemoryScope("curated", "demo")


def curated_document(body="Always run the unit tests."):
    return MemoryDocument(
        {
            "id": "reliability",
            "title": "Reliability convention",
            "kind": "guidance",
            "summary": "How the business verifies work",
            "classification": "private",
            "tags": ["reliability"],
            "review_status": "curated",
        },
        body,
    )


class DreamResponder:
    def __init__(self, run_ids=("run-one", "run-two")):
        self.run_ids = run_ids
        self.calls = {}
        self.fail_curator_once = False
        self.curator_artifact_written = False

    def __call__(self, model, messages):
        prompt = messages[-1]["content"]
        if "dream-analysis-" in prompt and '"id": "dream-curator"' not in prompt:
            task_id = "dream-analysis-000" if "dream-analysis-000" in prompt else "dream-analysis-001"
            shard = 0 if task_id.endswith("000") else 1
            run_id = self.run_ids[min(shard, len(self.run_ids) - 1)]
            self.calls[task_id] = self.calls.get(task_id, 0) + 1
            if self.calls[task_id] == 1:
                findings = {
                    "findings": [
                        {
                            "pattern_key": "missing-test-verification",
                            "summary": "Runs claimed completion without test evidence",
                            "evidence": [
                                {
                                    "run_id": run_id,
                                    "source_path": "attempts/research/attempt-0001/turn-0001/request.json",
                                }
                            ],
                            "suggested_action": "Require deterministic test evidence",
                        }
                    ]
                }
                return {
                    "type": "tool_call",
                    "call_id": f"write-{task_id}",
                    "tool": "write_artifact",
                    "arguments": {
                        "path": f"findings-{shard:03d}.json",
                        "content": json.dumps(findings),
                    },
                }
            return {
                "type": "final",
                "summary": "Findings recorded",
                "outputs": [f"artifacts/findings-{shard:03d}.json"],
            }
        if "dream-curator" in prompt:
            self.calls["curator"] = self.calls.get("curator", 0) + 1
            if self.fail_curator_once and self.calls["curator"] == 1:
                self.fail_curator_once = False
                raise RuntimeError("simulated curator interruption")
            if not self.curator_artifact_written:
                self.curator_artifact_written = True
                proposal = {
                    "proposals": [
                        {
                            "pattern_key": "missing-test-verification",
                            "operation": "modified",
                            "target_scope": "curated",
                            "document_id": "reliability",
                            "content": curated_document(
                                "Always run the unit tests and record their evidence before completion."
                            ).to_bytes().decode(),
                            "rationale": "Both source runs omitted deterministic verification",
                        }
                    ]
                }
                return {
                    "type": "tool_call",
                    "call_id": "write-curator",
                    "tool": "write_artifact",
                    "arguments": {
                        "path": "proposals.json",
                        "content": json.dumps(proposal),
                    },
                }
            return {
                "type": "final",
                "summary": "Proposal staged",
                "outputs": ["artifacts/proposals.json"],
            }
        raise AssertionError("Unexpected dream task")


class DreamRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.responder = DreamResponder()
        self.fake = FakeOllamaServer(self.responder).start()
        base = ollama_only_config(
            OllamaConfig(
                base_url=self.fake.url,
                load_timeout_seconds=2,
                request_timeout_seconds=2,
                dedicated_ollama=True,
                transport_retries=0,
            )
        )
        self.config = replace(
            base,
            memory=MemoryConfig(
                enabled=True,
                root=str(self.root / "memory"),
                project_id="demo",
                classification="private",
                dreaming_enabled=True,
                run_roots=(str(self.root / "source-state"),),
            ),
            dream=DreamConfig(
                subject_model="deepseek-r1:70b",
                curator_model="deepseek-r1:70b",
                max_shards=2,
            ),
            execution=ExecutionConfig(
                lock_path=str(self.root / "global.lock"),
                process_registry_path=str(self.root / "process.json"),
            ),
        )
        with mock.patch("agentic_ai.identity.current_username", return_value="roman"):
            self.memory = MemoryStore(self.config.memory.root)
            self.original = self.memory.put(
                CURATED, curated_document(), HUMAN, operation="created"
            )
        self.create_transcript("run-one")
        self.create_transcript("run-two")
        self.backends = ModelBackends(
            self.config, ollama_client=OllamaClient(self.config.ollama)
        )

    def tearDown(self):
        self.fake.stop()
        self.temporary.cleanup()

    def create_transcript(self, run_id):
        store = RunStore.create(
            self.root / "source-state",
            "A completed project run",
            self.config.to_dict(),
            run_id,
        )
        attempt = store.attempt_dir("research", 1, 1)
        attempt.mkdir(parents=True, exist_ok=True)
        (attempt / "request.json").write_text(
            json.dumps({"task": "claim completion", "run_id": run_id}), encoding="utf-8"
        )
        (attempt / "response.raw.txt").write_text(
            '{"type":"final","summary":"done without tests","outputs":[]}', encoding="utf-8"
        )
        store.append_event("task_completed", task_id="research", summary="No test evidence")
        store.update_run(status="succeeded")
        TranscriptBuilder(self.config).finalize(store)

    def runner(self):
        return DreamRunner(
            self.config,
            client=self.backends,
            poll_interval=0.01,
        )

    def test_complete_dream_review_and_atomic_human_promotion(self):
        runner = self.runner()
        job = runner.create_job()
        job = runner.execute(job["job_id"])
        self.assertEqual(job["phase"], "awaiting_review")
        self.assertEqual(len(job["proposal_ids"]), 1)
        proposal = runner.load_proposal(job["proposal_ids"][0])
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(proposal["statistics"]["distinct_runs"], 2)
        self.assertIn("+Always run the unit tests and record", runner.review())
        current, version = self.memory.read(CURATED, "reliability", HUMAN)
        self.assertEqual(current.body, "Always run the unit tests.\n")
        self.assertEqual(version["version_id"], "v000001")

        with mock.patch("agentic_ai.identity.current_username", return_value="roman"):
            decision = runner.approve(proposal["proposal_id"], HUMAN)
            repeated = runner.approve(proposal["proposal_id"], HUMAN)
        self.assertEqual(decision["status"], "approved")
        self.assertEqual(repeated, decision)
        promoted, version = self.memory.read(CURATED, "reliability", HUMAN)
        self.assertIn("record their evidence", promoted.body)
        self.assertEqual(version["version_id"], "v000002")
        self.assertEqual(version["provenance"]["dream_job_id"], job["job_id"])
        self.assertEqual(self.memory.verify(), [])
        self.assertEqual(self.fake.violations, [])

    def test_interrupted_curator_resumes_without_repeating_subjects(self):
        self.responder.fail_curator_once = True
        runner = self.runner()
        job = runner.create_job()
        with self.assertRaises(Exception):
            runner.execute(job["job_id"])
        self.assertEqual(runner.load_job(job["job_id"])["phase"], "interrupted")
        subject_calls = {
            key: value for key, value in self.responder.calls.items() if key.startswith("dream-analysis")
        }
        job = runner.execute(job["job_id"])
        self.assertEqual(job["phase"], "awaiting_review")
        for task_id, calls in subject_calls.items():
            self.assertEqual(self.responder.calls[task_id], calls)

    def test_stale_proposal_cannot_overwrite_newer_human_memory(self):
        runner = self.runner()
        job = runner.create_job()
        job = runner.execute(job["job_id"])
        proposal_id = job["proposal_ids"][0]
        with mock.patch("agentic_ai.identity.current_username", return_value="roman"):
            self.memory.put(
                CURATED,
                curated_document("A newer human decision."),
                HUMAN,
                expected_sha256=self.original["sha256"],
            )
            with self.assertRaises(MemoryConflictError):
                runner.approve(proposal_id, HUMAN)
        current, _ = self.memory.read(CURATED, "reliability", HUMAN)
        self.assertEqual(current.body, "A newer human decision.\n")

    def test_approval_crash_is_idempotent_on_retry(self):
        runner = self.runner()
        job = runner.create_job()
        job = runner.execute(job["job_id"])
        proposal_id = job["proposal_ids"][0]
        original_commit = runner.memory.commit

        def commit_then_crash(*args, **kwargs):
            result = original_commit(*args, **kwargs)
            raise RuntimeError("crash after approval commit")

        with mock.patch("agentic_ai.identity.current_username", return_value="roman"):
            runner.memory.commit = commit_then_crash
            with self.assertRaisesRegex(RuntimeError, "crash after"):
                runner.approve(proposal_id, HUMAN)
            runner.memory.commit = original_commit
            decision = runner.approve(proposal_id, HUMAN)
        self.assertEqual(decision["status"], "approved")
        self.assertEqual(len(self.memory.history(CURATED, "reliability", HUMAN)), 2)

    def test_insufficient_prevalence_is_rejected_before_review(self):
        (self.root / "source-state" / "runs" / "run-two" / "transcripts" / "manifest.json").write_text(
            json.dumps({"redacted": True}), encoding="utf-8"
        )
        runner = self.runner()
        job = runner.create_job()
        job = runner.execute(job["job_id"])
        proposal = runner.load_proposal(job["proposal_ids"][0])
        self.assertEqual(proposal["status"], "rejected_validation")
        self.assertIn("prevalence", " ".join(proposal["reasons"]))
        with mock.patch("agentic_ai.identity.current_username", return_value="roman"):
            with self.assertRaises(MemoryConflictError):
                runner.approve(proposal["proposal_id"], HUMAN)

    def test_no_matching_transcripts_fails_before_model_calls(self):
        config = replace(
            self.config,
            memory=replace(self.config.memory, project_id="other"),
        )
        runner = DreamRunner(config)
        with self.assertRaises(MemoryNotFoundError):
            runner.create_job()
        self.assertEqual(self.fake.calls, [])
    def test_cli_list_and_run_metrics(self):
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps(self.config.to_dict()), encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["dream", "list", "--config", str(config_path)]), 0)
        self.assertEqual(json.loads(output.getvalue()), [])

        state = self.root / "metrics-state"
        baseline = RunStore.create(state, "baseline", self.config.to_dict(), "baseline")
        candidate = RunStore.create(state, "candidate", self.config.to_dict(), "candidate")
        baseline.update_run(status="succeeded")
        candidate.update_run(status="succeeded")
        baseline.update_run(lambda run: run["metrics"].update({"model_calls": 5, "tool_calls": 4}))
        candidate.update_run(lambda run: run["metrics"].update({"model_calls": 3, "tool_calls": 2}))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(
                main(["metrics", "baseline", "candidate", "--state-dir", str(state)]),
                0,
            )
        comparison = json.loads(output.getvalue())
        self.assertEqual(comparison["delta"]["model_calls"], -2)
        self.assertIn("do not prove", comparison["note"])
    def test_revoked_transcript_stops_execution_and_approval(self):
        runner = self.runner()
        job = runner.create_job()
        with mock.patch("agentic_ai.identity.current_username", return_value="roman"):
            TranscriptBuilder.redact(
                self.root / "source-state",
                "run-one",
                reason="Revoke before dreaming",
                actor=HUMAN,
            )
        calls_before = len(self.fake.calls)
        with self.assertRaises(Exception):
            runner.execute(job["job_id"])
        self.assertEqual(len(self.fake.calls), calls_before)

        self.create_transcript("run-three")
        self.responder.run_ids = ("run-two", "run-three")
        job = runner.create_job()
        job = runner.execute(job["job_id"])
        with mock.patch("agentic_ai.identity.current_username", return_value="roman"):
            TranscriptBuilder.redact(
                self.root / "source-state",
                "run-three",
                reason="Revoke before approval",
                actor=HUMAN,
            )
            with self.assertRaises(Exception):
                runner.approve(job["proposal_ids"][0], HUMAN)

    def test_changed_completed_artifact_is_requeued(self):
        runner = self.runner()
        job = runner.create_job()
        job = runner.execute(job["job_id"])
        job["phase"] = "interrupted"
        runner._save_job(job)
        store = RunStore.open(job["state_dir"], job["job_id"])
        (store.artifacts_dir / "findings-000.json").unlink()
        self.responder.calls["dream-analysis-000"] = 0
        job = runner.execute(job["job_id"])
        self.assertEqual(job["phase"], "awaiting_review")
        self.assertEqual(store.load_run()["task_states"]["dream-analysis-000"]["attempt"], 2)

    def test_snapshot_filters_other_classifications_and_evidence_tampering(self):
        public_config = replace(
            self.config,
            memory=replace(self.config.memory, classification="public"),
        )
        with mock.patch("agentic_ai.identity.current_username", return_value="roman"):
            self.memory.put(
                CURATED,
                curated_document("Private memory must not enter public dreams"),
                HUMAN,
                expected_sha256=self.original["sha256"],
            )
        snapshot = DreamRunner(public_config)._memory_snapshot()
        self.assertEqual(snapshot, [])

        runner = self.runner()
        job = runner.create_job()
        job = runner.execute(job["job_id"])
        proposal_id = job["proposal_ids"][0]
        path = self.root / "memory" / "dreams" / "proposals" / f"{proposal_id}.json"
        proposal = read_json(path)
        proposal["evidence"] = []
        path.write_text(json.dumps(proposal), encoding="utf-8")
        with mock.patch("agentic_ai.identity.current_username", return_value="roman"):
            with self.assertRaises(MemoryConflictError):
                runner.approve(proposal_id, HUMAN)


if __name__ == "__main__":
    unittest.main()
