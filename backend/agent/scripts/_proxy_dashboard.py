#!/usr/bin/env python3
"""Reverse proxy + SPA static server for the Vibe-Trading dashboard.

- /api/*  -> http://127.0.0.1:8787
- everything else -> frontend/dist (with SPA fallback to index.html)
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.parse
import mimetypes
from pathlib import Path

API_BASE = "http://127.0.0.1:8787"
DIST = Path("/home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/frontend/dist")

class DashboardHandler(BaseHTTPRequestHandler):
    def _proxy_api(self, method):
        target = API_BASE + self.path
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))) if method in ("POST", "PUT") else None
        req = urllib.request.Request(
            target,
            data=body,
            method=method,
            headers={
                k: v for k, v in self.headers.items()
                if k.lower() not in ("host", "content-length", "connection", "accept-encoding")
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in ("transfer-encoding", "content-length", "connection"):
                        self.send_header(k, v)
                content = resp.read()
                self.send_header("Content-Length", len(content))
                self.end_headers()
                self.wfile.write(content)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            body = e.read()
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

    def _serve_static(self):
        rel = urllib.parse.unquote(self.path.lstrip("/"))
        if not rel or rel.endswith("/"):
            rel = "index.html"
        target = DIST / rel
        if not target.is_file():
            # SPA fallback — but not for /api (handled above)
            if not rel.startswith(("assets/", "static/")):
                target = DIST / "index.html"
        if not target.is_file():
            self.send_response(404)
            self.end_headers()
            return
        content = target.read_bytes()
        ctype, _ = mimetypes.guess_type(str(target))
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", len(content))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._proxy_api("GET")
        else:
            self._serve_static()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._proxy_api("POST")
        else:
            self.send_response(405)
            self.end_headers()

    def do_OPTIONS(self):
        if self.path.startswith("/api/"):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
        else:
            self.send_response(204)
            self.end_headers()

    def log_message(self, fmt, *args):
        if "/assets/" not in args[0]:
            super().log_message(fmt, *args)

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 5899), DashboardHandler)
    print("dashboard proxy on http://0.0.0.0:5899 -> api 8787")
    server.serve_forever()
