from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agentic_ai.backends import ModelBackends
from agentic_ai.config import (
    Config,
    LlamaCppConfig,
    OllamaConfig,
    RoleConfig,
)
from agentic_ai.errors import LlamaCppError
from agentic_ai.llamacpp import LlamaCppBackend
from agentic_ai.residency import ResidencyManager
from agentic_ai.storage import RunStore
from fake_ollama import FakeOllamaServer


FINAL_JSON = '{"type": "final", "summary": "done", "outputs": []}'


class FakeLlamaServer:
    """Minimal llama-server test double: /health + SSE chat completions."""

    def __init__(self):
        self.chat_payloads = []
        self._server = None
        self._thread = None

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def start(self) -> "FakeLlamaServer":
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format, *args):
                return

            def do_GET(self):
                if self.path == "/health":
                    body = b'{"status": "ok"}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self):
                if self.path != "/v1/chat/completions":
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                length = int(self.headers.get("Content-Length", "0"))
                fake.chat_payloads.append(json.loads(self.rfile.read(length) or b"{}"))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()

                def chunk(value):
                    self.wfile.write(b"data: " + json.dumps(value).encode() + b"\n\n")
                    self.wfile.flush()

                chunk({"choices": [{"delta": {"reasoning_content": "pondering "}, "finish_reason": None}]})
                chunk({"choices": [{"delta": {"reasoning_content": "hard"}, "finish_reason": None}]})
                chunk({"choices": [{"delta": {"content": FINAL_JSON}, "finish_reason": None}]})
                chunk(
                    {
                        "choices": [{"delta": {}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
                    }
                )
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                self.close_connection = True

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class LlamaCppBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.model_file = self.root / "model.gguf"
        self.model_file.write_bytes(b"fake-gguf")
        self.fake_server = FakeLlamaServer().start()
        self.processes = []
        config = LlamaCppConfig(
            enabled=True,
            model_name="deepseek-r1-uncensored-v2:70b",
            model_path=str(self.model_file),
            server_binary=sys.executable,
            port=self.fake_server.port,
            startup_timeout_seconds=10,
            request_timeout_seconds=10,
            transport_retries=0,
        )
        self.backend = LlamaCppBackend(
            config,
            process_factory=self._spawn,
            log_dir=self.root / "logs",
        )

    def tearDown(self):
        self.fake_server.stop()
        self.temporary.cleanup()

    def _spawn(self, argv, log_file):
        process = FakeProcess()
        self.processes.append(process)
        return process

    def test_server_argv_matches_required_flags(self):
        argv = self.backend.server_argv()
        self.assertEqual(argv[0], sys.executable)
        self.assertIn(str(self.model_file), argv)
        self.assertEqual(argv[argv.index("-ngl") + 1], "23")
        self.assertEqual(argv[argv.index("-c") + 1], "16384")
        self.assertEqual(argv[argv.index("-ctk") + 1], "q8_0")
        self.assertEqual(argv[argv.index("-ctv") + 1], "q8_0")
        self.assertIn("--jinja", argv)

    def test_load_chat_unload_lifecycle(self):
        self.assertEqual(self.backend.ps(), {"models": []})
        self.backend.load_model("deepseek-r1-uncensored-v2:70b")
        names = [m["name"] for m in self.backend.ps()["models"]]
        self.assertEqual(names, ["deepseek-r1-uncensored-v2:70b"])

        streamed = []
        result = self.backend.chat(
            "deepseek-r1-uncensored-v2:70b",
            [{"role": "user", "content": "hello"}],
            RoleConfig("deepseek-r1-uncensored-v2:70b"),
            on_text=streamed.append,
        )
        self.assertEqual(result.done_reason, "stop")
        self.assertEqual(result.prompt_eval_count, 10)
        self.assertEqual(result.eval_count, 20)
        self.assertIn("<think>\npondering hard\n</think>\n", result.text)
        self.assertTrue(result.text.endswith(FINAL_JSON))
        self.assertEqual("".join(streamed), result.text)
        payload = self.fake_server.chat_payloads[0]
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["max_tokens"], 4096)
        self.assertTrue(payload["stream"])

        self.backend.unload_model("deepseek-r1-uncensored-v2:70b")
        self.assertTrue(self.processes[0].terminated)
        self.assertEqual(self.backend.ps(), {"models": []})

    def test_missing_model_file_raises(self):
        self.model_file.unlink()
        with self.assertRaisesRegex(LlamaCppError, "missing"):
            self.backend.load_model("deepseek-r1-uncensored-v2:70b")

    def test_chat_requires_resident_server(self):
        with self.assertRaisesRegex(LlamaCppError, "not running"):
            self.backend.chat(
                "deepseek-r1-uncensored-v2:70b",
                [{"role": "user", "content": "hello"}],
                RoleConfig("deepseek-r1-uncensored-v2:70b"),
            )

    def test_rejects_other_models(self):
        with self.assertRaisesRegex(LlamaCppError, "does not serve"):
            self.backend.load_model("qwen2.5-coder:32b")


class CrossBackendResidencyTests(unittest.TestCase):
    def test_switch_between_llamacpp_and_ollama_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_file = root / "model.gguf"
            model_file.write_bytes(b"fake-gguf")
            fake_ollama = FakeOllamaServer().start()
            fake_llama = FakeLlamaServer().start()
            processes = []

            def spawn(argv, log_file):
                process = FakeProcess()
                processes.append(process)
                return process

            try:
                ollama = OllamaConfig(
                    base_url=fake_ollama.url,
                    load_timeout_seconds=5,
                    request_timeout_seconds=5,
                    dedicated_ollama=True,
                    transport_retries=0,
                )
                llamacpp = LlamaCppConfig(
                    enabled=True,
                    model_name="deepseek-r1-uncensored-v2:70b",
                    model_path=str(model_file),
                    server_binary=sys.executable,
                    port=fake_llama.port,
                    startup_timeout_seconds=10,
                    request_timeout_seconds=10,
                    transport_retries=0,
                )
                config = Config(ollama=ollama, llamacpp=llamacpp)
                backends = ModelBackends(
                    config,
                    llamacpp_backend=LlamaCppBackend(
                        llamacpp, process_factory=spawn, log_dir=root
                    ),
                )
                store = RunStore.create(
                    temporary, "test", config.to_dict(), "run-cross-backend"
                )
                manager = ResidencyManager(
                    backends, store, config, poll_interval=0.01
                )

                def activate(model, wave):
                    return manager.activate(
                        model,
                        assignments=[
                            {
                                "task_id": "task",
                                "role": "planner",
                                "model": model,
                                "attempt": 1,
                            }
                        ],
                        required_models=[
                            "deepseek-r1-uncensored-v2:70b",
                            "qwen2.5-coder:32b",
                        ],
                        wave_id=wave,
                        reason="test",
                    )

                activate("deepseek-r1-uncensored-v2:70b", 1)
                self.assertEqual(manager._names(), ["deepseek-r1-uncensored-v2:70b"])
                self.assertEqual(fake_ollama.loaded, [])

                generation = manager.chat(
                    "deepseek-r1-uncensored-v2:70b",
                    [{"role": "user", "content": "hello"}],
                    config.roles["planner"],
                )
                self.assertEqual(generation.done_reason, "stop")

                switch = activate("qwen2.5-coder:32b", 2)
                self.assertEqual(switch["from_model"], "deepseek-r1-uncensored-v2:70b")
                self.assertTrue(processes[0].terminated)
                self.assertEqual(fake_ollama.loaded, ["qwen2.5-coder:32b"])
                self.assertEqual(manager._names(), ["qwen2.5-coder:32b"])
                self.assertLessEqual(fake_ollama.max_resident, 1)

                self.assertEqual(manager.offload_all(), [])
                self.assertEqual(manager._names(), [])
                self.assertEqual(fake_ollama.violations, [])
            finally:
                fake_ollama.stop()
                fake_llama.stop()


if __name__ == "__main__":
    unittest.main()
