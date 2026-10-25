"""Offline retirement contract: normal links and all former API paths."""
import http.client
import importlib.util
import json
from pathlib import Path
import threading
import unittest

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("archive_server", BASE / "server.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class QuietHandler(module.ArchiveHandler):
    def log_message(self, *args): pass

class ArchiveContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = module.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(5)
    def request(self, method, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        conn.request(method, path)
        response = conn.getresponse(); body = response.read()
        result = (response.status, dict(response.getheaders()), body)
        conn.close(); return result
    def test_pages_and_deep_links(self):
        for path in ("/", "/blueprint", "/blueprint/", "/fleet", "/old/deep/link"):
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertEqual(status, 200); self.assertIn(b"Archived", body)
        status, headers, _ = self.request("GET", "/schaltplan")
        self.assertEqual(status, 308); self.assertEqual(headers["Location"], "/blueprint")
    def test_all_former_api_paths_are_retired(self):
        paths = json.loads((BASE / "tests" / "former-api-paths.json").read_text(encoding="utf-8"))
        self.assertGreater(len(paths), 30)
        for path in paths:
            if path == "/api/health": continue
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertEqual(status, 410); self.assertIs(json.loads(body)["agent_execution"], False)
    def test_mutations_cannot_execute(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"):
            for path in ("/", "/api/health", "/api/routines/fire", "/api/chat", "/api/tasks"):
                with self.subTest(method=method, path=path):
                    status, _, body = self.request(method, path)
                    self.assertEqual(status, 410); self.assertIs(json.loads(body)["agent_execution"], False)
    def test_health_is_explicitly_static(self):
        status, _, body = self.request("GET", "/api/health")
        self.assertEqual(status, 200); self.assertEqual(json.loads(body)["mode"], "archived-static-demo")
        self.assertIs(json.loads(body)["agent_execution"], False)
    def test_browser_cannot_connect_or_submit(self):
        _, headers, _ = self.request("GET", "/")
        self.assertIn("connect-src 'none'", headers["Content-Security-Policy"])
        self.assertIn("form-action 'none'", headers["Content-Security-Policy"])
        js = (BASE / "public" / "archive.js").read_text(encoding="utf-8")
        for token in ("fetch(", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "/api/"):
            self.assertNotIn(token, js)
    def test_utf8_and_local_fictional_data(self):
        _, _, body = self.request("GET", "/")
        text = body.decode("utf-8")
        self.assertIn("ausschließlich", text); self.assertIn("Abläufe", text)
        self.assertIn("supplier@example.invalid", text)
        css = (BASE / "public" / "style.css").read_text(encoding="utf-8")
        self.assertNotIn("@import", css); self.assertNotIn("https://", css)
    def test_head_and_unknown_asset(self):
        status, headers, body = self.request("HEAD", "/")
        self.assertEqual(status, 200); self.assertGreater(int(headers["Content-Length"]), 1000); self.assertEqual(body, b"")
        status, _, _ = self.request("GET", "/static/not-present.js")
        self.assertEqual(status, 404)
    def test_container_only_copies_archive(self):
        docker = (BASE.parent / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("pip install", docker); self.assertNotIn("COPY . .", docker)
        self.assertIn("COPY --chown=65532:65532 archive/public", docker)
        self.assertNotIn("sentinel_fleet.web.server", (BASE.parent / "app.py").read_text(encoding="utf-8"))

if __name__ == "__main__": unittest.main(verbosity=2)
