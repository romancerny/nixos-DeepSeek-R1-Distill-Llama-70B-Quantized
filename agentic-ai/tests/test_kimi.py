from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentic_ai.backends import ModelBackends
from agentic_ai.config import Config, KimiConfig, OllamaConfig, RoleConfig
from agentic_ai.errors import KimiError
from agentic_ai.kimi import KimiClient
from agentic_ai.ollama import OllamaClient
from agentic_ai.residency import ResidencyManager
from agentic_ai.storage import RunStore
from fake_ollama import FakeOllamaServer


class KimiHandler(BaseHTTPRequestHandler):
    statuses = []
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        self.__class__.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "user_agent": self.headers.get("User-Agent"),
                "payload": payload,
            }
        )
        status = self.__class__.statuses.pop(0) if self.__class__.statuses else 200
        self.send_response(status)
        if status != 200:
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": f"status {status}"}}).encode())
            return
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        events = [
            {"choices": [{"delta": {"reasoning_content": "Check."}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "{\"type\":\"final\",\"summary\":\"ok\",\"outputs\":[]}"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 12, "completion_tokens": 5}},
        ]
        for event in events:
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *args):
        pass


class KimiClientTests(unittest.TestCase):
    def setUp(self):
        KimiHandler.statuses = []
        KimiHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), KimiHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = KimiConfig(
            enabled=True,
            base_url=f"http://127.0.0.1:{self.server.server_port}",
            request_timeout_seconds=2,
            transport_retries=2,
            approved=True,
        )
        self.environment = mock.patch.dict(os.environ, {"KIMI_API_KEY": "test-secret"}, clear=False)
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_streaming_protocol_usage_and_client_identity(self):
        client = KimiClient(self.config)
        result = client.chat(
            "k3.1-pro",
            [{"role": "user", "content": "public test"}],
            RoleConfig("k3.1-pro", num_predict=100),
        )
        self.assertIn("<think>", result.text)
        self.assertIn('"type":"final"', result.text)
        self.assertEqual(result.prompt_eval_count, 12)
        self.assertEqual(result.eval_count, 5)
        request = KimiHandler.requests[0]
        self.assertEqual(request["path"], "/chat/completions")
        self.assertEqual(request["authorization"], "Bearer test-secret")
        self.assertEqual(request["user_agent"], "agentic-ai/0.2.0")
        self.assertEqual(request["payload"]["model"], "k3.1-pro")
        self.assertNotIn("temperature", request["payload"])

    def test_missing_credential_fails_before_network(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(KimiError) as caught:
                KimiClient(self.config).chat(
                    "k3.1-pro", [], RoleConfig("k3.1-pro")
                )
        self.assertEqual(caught.exception.category, "authentication")
        self.assertEqual(KimiHandler.requests, [])

    def test_authentication_failure_does_not_retry(self):
        KimiHandler.statuses = [401]
        with self.assertRaises(KimiError) as caught:
            KimiClient(self.config).chat("k3.1-pro", [], RoleConfig("k3.1-pro"))
        self.assertEqual(caught.exception.category, "authentication")
        self.assertEqual(len(KimiHandler.requests), 1)

    def test_rate_limit_has_bounded_retry(self):
        KimiHandler.statuses = [429, 200]
        result = KimiClient(self.config).chat(
            "k3.1-pro", [], RoleConfig("k3.1-pro")
        )
        self.assertIn("final", result.text)
        self.assertEqual(len(KimiHandler.requests), 2)


class HostedResidencyTests(unittest.TestCase):
    def test_local_hosted_local_transition_preserves_local_exclusivity(self):
        fake = FakeOllamaServer().start()
        temporary = tempfile.TemporaryDirectory()
        server = ThreadingHTTPServer(("127.0.0.1", 0), KimiHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        KimiHandler.statuses = []
        KimiHandler.requests = []
        try:
            ollama = OllamaConfig(
                base_url=fake.url,
                load_timeout_seconds=2,
                request_timeout_seconds=2,
                dedicated_ollama=True,
                transport_retries=0,
            )
            kimi = KimiConfig(
                enabled=True,
                base_url=f"http://127.0.0.1:{server.server_port}",
                request_timeout_seconds=2,
                transport_retries=0,
                approved=True,
            )
            config = Config(ollama=ollama, kimi=kimi)
            store = RunStore.create(temporary.name, "test", config.to_dict(), "run-hosted")
            backends = ModelBackends(
                config,
                ollama_client=OllamaClient(ollama),
                kimi_client=KimiClient(kimi),
            )
            manager = ResidencyManager(backends, store, config, poll_interval=0.01)
            with mock.patch.dict(os.environ, {"KIMI_API_KEY": "test-secret"}):
                manager.activate(
                    "qwen2.5-coder:32b",
                    assignments=[],
                    required_models=["qwen2.5-coder:32b"],
                    wave_id=1,
                    reason="local first",
                )
                self.assertEqual(fake.loaded, ["qwen2.5-coder:32b"])
                switch = manager.activate(
                    "k3.1-pro",
                    assignments=[],
                    required_models=["k3.1-pro"],
                    wave_id=2,
                    reason="hosted second",
                )
                self.assertTrue(switch["load_verification"]["hosted"])
                self.assertEqual(fake.loaded, [])
                result = manager.chat(
                    "k3.1-pro",
                    [{"role": "user", "content": "public"}],
                    RoleConfig("k3.1-pro"),
                )
                self.assertIn("final", result.text)
                manager.activate(
                    "qwen2.5-coder:32b",
                    assignments=[],
                    required_models=["qwen2.5-coder:32b"],
                    wave_id=3,
                    reason="local again",
                )
                self.assertEqual(fake.loaded, ["qwen2.5-coder:32b"])
                self.assertEqual(fake.max_resident, 1)
                self.assertEqual(store.load_run()["metrics"]["hosted_calls"], 1)
        finally:
            fake.stop()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
