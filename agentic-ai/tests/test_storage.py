import json
import tempfile
import unittest
from pathlib import Path

from agentic_ai.config import Config
from agentic_ai.errors import StorageError
from agentic_ai.storage import FileLock, RunStore, atomic_write_json, read_json


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state = Path(self.temporary.name)
        self.store = RunStore.create(self.state, "Build something", Config.default().to_dict(), "run-test")

    def tearDown(self):
        self.temporary.cleanup()

    def test_atomic_round_trip_and_run_snapshot(self):
        path = self.store.run_dir / "artifacts" / "note.json"
        atomic_write_json(path, {"message": "hello"})
        self.assertEqual(read_json(path), {"message": "hello"})
        run = self.store.load_run()
        self.assertEqual(run["status"], "created")
        self.store.update_run(status="planning")
        self.assertEqual(self.store.load_run()["status"], "planning")

    def test_file_record_and_hash_validation(self):
        path = self.store.artifacts_dir / "note.md"
        path.write_text("first", encoding="utf-8")
        record = self.store.file_record("artifacts/note.md")
        self.assertTrue(self.store.validate_file_record(record))
        path.write_text("changed", encoding="utf-8")
        self.assertFalse(self.store.validate_file_record(record))

    def test_path_escape_is_rejected(self):
        with self.assertRaises(StorageError):
            self.store.resolve_run_path("workspace/../../outside")
        (self.store.run_dir / "outside").mkdir()
        link = self.store.workspace_dir / "link"
        link.symlink_to(self.store.run_dir / "outside", target_is_directory=True)
        with self.assertRaises(StorageError):
            self.store.resolve_run_path("workspace/link/file.txt")

    def test_executor_lock_excludes_competitor(self):
        with self.store.executor_lock():
            with self.assertRaises(StorageError):
                with FileLock(self.store.executor_lock_path, blocking=False):
                    pass

    def test_repair_only_truncated_final_event(self):
        self.store.events_path.write_text('{"valid": 1}\n{"broken":', encoding="utf-8")
        self.assertTrue(self.store.repair_event_log())
        lines = self.store.events_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(lines[0]), {"valid": 1})
        self.assertEqual(json.loads(lines[-1])["type"], "audit_log_repaired")


if __name__ == "__main__":
    unittest.main()
