"""Static-only SentinelFleet archive. No agents, cloud SDKs or persistent data."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent / "public"
FILES = {"/": ("index.html", "text/html"), "/blueprint": ("blueprint.html", "text/html"), "/static/style.css": ("style.css", "text/css"), "/static/app.js": ("archive.js", "text/javascript")}
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; font-src 'self'; form-action 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"

class ArchiveHandler(BaseHTTPRequestHandler):
    server_version = "SentinelFleetArchive/2026-10-25"
    def respond(self, status, body, content_type="application/json", head=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "public, max-age=300" if status == 200 else "no-store")
        self.end_headers()
        if not head: self.wfile.write(body)
    def retired(self, head=False):
        body = json.dumps({"mode": "archived-static-demo", "agent_execution": False, "detail": "Live APIs and agents are retired. Interactions in the archive use local examples only.", "archive": "/"}).encode()
        self.respond(410, body, head=head)
    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path == "/api/health":
            self.respond(200, b'{"status":"ok","mode":"archived-static-demo","agent_execution":false}', head=self.command == "HEAD")
            return
        if path.startswith(("/api/", "/ws/")) or path in ("/api", "/ws", "/openapi.json", "/docs", "/redoc"):
            self.retired(self.command == "HEAD")
            return
        if path.rstrip("/") == "/schaltplan":
            self.send_response(308); self.send_header("Location", "/blueprint"); self.send_header("Content-Length", "0"); self.end_headers(); return
        entry = FILES.get(path.rstrip("/") or "/")
        if entry is None:
            if path.startswith(("/static/", "/assets/")) or "." in path.rsplit("/", 1)[-1]:
                self.respond(404, b'{"detail":"Archive asset not found"}', head=self.command == "HEAD"); return
            entry = FILES["/"]
        name, kind = entry
        self.respond(200, (ROOT / name).read_bytes(), kind, self.command == "HEAD")
    def do_HEAD(self): self.do_GET()
    def do_POST(self): self.retired()
    def do_PUT(self): self.retired()
    def do_PATCH(self): self.retired()
    def do_DELETE(self): self.retired()
    def do_OPTIONS(self): self.retired()
    def do_TRACE(self): self.retired()
    def do_CONNECT(self): self.retired()

if __name__ == "__main__":
    ThreadingHTTPServer((os.environ.get("HOST", "0.0.0.0"), int(os.environ.get("PORT", "8080"))), ArchiveHandler).serve_forever()
