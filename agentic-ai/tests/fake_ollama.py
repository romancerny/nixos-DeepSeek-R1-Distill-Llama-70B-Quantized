from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable


Responder = Callable[[str, list[dict[str, str]]], Any]


class FakeOllamaServer:
    """Stateful Ollama test double that rejects unsafe residency transitions."""

    def __init__(self, responder: Responder | None = None):
        self.responder = responder or (lambda model, messages: {"type": "final", "summary": "ok", "outputs": []})
        self.available_models = ["deepseek-r1:70b", "qwen2.5-coder:32b"]
        self.loaded: list[str] = []
        self.calls: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.violations: list[str] = []
        self.errors: list[str] = []
        self.max_resident = 0
        self._lock = threading.Lock()
        self._inference = False
        self._server = None
        self._thread = None

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def start(self) -> "FakeOllamaServer":
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format, *args):
                return

            def _body(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                return json.loads(raw) if raw else {}

            def _json(self, value, status=200):
                raw = json.dumps(value).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/api/tags":
                    self._json({"models": [{"name": name, "model": name} for name in fake.available_models]})
                    return
                if self.path == "/api/ps":
                    with fake._lock:
                        models = [{"name": name, "model": name, "size": 1} for name in fake.loaded]
                    self._json({"models": models})
                    return
                self._json({"error": "not found"}, 404)

            def do_POST(self):
                try:
                    payload = self._body()
                except Exception as exc:
                    self._json({"error": str(exc)}, 400)
                    return
                if self.path == "/api/generate":
                    self._generate(payload)
                    return
                if self.path == "/api/chat":
                    self._chat(payload)
                    return
                self._json({"error": "not found"}, 404)

            def _generate(self, payload):
                model = payload.get("model", "")
                if payload.get("keep_alive") == 0:
                    with fake._lock:
                        if fake._inference:
                            fake.violations.append("unload during inference")
                            self._json({"error": "cannot unload during inference"}, 409)
                            return
                        if model in fake.loaded:
                            fake.loaded.remove(model)
                        fake.events.append({"type": "unload", "model": model, "loaded": list(fake.loaded)})
                    self._json({"model": model, "done": True})
                    return
                with fake._lock:
                    if fake._inference:
                        fake.violations.append("load during inference")
                        self._json({"error": "cannot load during inference"}, 409)
                        return
                    if fake.loaded and model not in fake.loaded:
                        fake.violations.append(f"load {model} before unloading {fake.loaded}")
                        self._json({"error": "another model is still resident"}, 409)
                        return
                    if model not in fake.loaded:
                        fake.loaded.append(model)
                    fake.max_resident = max(fake.max_resident, len(fake.loaded))
                    fake.events.append({"type": "load", "model": model, "loaded": list(fake.loaded)})
                self._json({"model": model, "done": True, "response": ""})

            def _chat(self, payload):
                model = payload.get("model", "")
                with fake._lock:
                    if fake._inference:
                        fake.violations.append("overlapping inference")
                        self._json({"error": "overlapping inference"}, 409)
                        return
                    if fake.loaded != [model]:
                        fake.violations.append(f"inference for {model} while loaded={fake.loaded}")
                        self._json({"error": "requested model is not exclusively resident"}, 409)
                        return
                    fake._inference = True
                    fake.events.append({"type": "chat_start", "model": model})
                try:
                    messages = payload.get("messages", [])
                    fake.calls.append({"model": model, "messages": messages, "payload": payload})
                    scripted = fake.responder(model, messages)
                    if isinstance(scripted, dict) and "text" in scripted:
                        text = scripted["text"]
                        done_reason = scripted.get("done_reason", "stop")
                    elif isinstance(scripted, str):
                        text = scripted
                        done_reason = "stop"
                    else:
                        text = json.dumps(scripted, ensure_ascii=False)
                        done_reason = "stop"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    first = {"model": model, "message": {"role": "assistant", "content": text}, "done": False}
                    self.wfile.write((json.dumps(first) + "\n").encode("utf-8"))
                    self.wfile.flush()
                    done = {
                        "model": model,
                        "message": {"role": "assistant", "content": ""},
                        "done": True,
                        "done_reason": done_reason,
                        "prompt_eval_count": 10,
                        "eval_count": 20,
                        "total_duration": 1000,
                    }
                    self.wfile.write((json.dumps(done) + "\n").encode("utf-8"))
                    self.wfile.flush()
                    self.close_connection = True
                except Exception as exc:
                    fake.errors.append(f"chat exception: {exc}")
                    try:
                        self._json({"error": str(exc)}, 500)
                    except Exception:
                        pass
                finally:
                    with fake._lock:
                        fake._inference = False
                        fake.events.append({"type": "chat_end", "model": model})

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

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, traceback):
        self.stop()

    def expire(self, model: str):
        with self._lock:
            if model in self.loaded:
                self.loaded.remove(model)
            self.events.append({"type": "cache_expiry", "model": model})

    def set_loaded(self, models: list[str]):
        with self._lock:
            self.loaded = list(models)
            self.max_resident = max(self.max_resident, len(self.loaded))
