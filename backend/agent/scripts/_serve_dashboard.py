#!/usr/bin/env python3
"""Simple static SPA server for the Vibe-Trading dashboard."""
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse

DIST = Path("/home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/frontend/dist")

class SPAHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def do_GET(self):
        path = Path(DIST, urllib.parse.unquote(self.path.lstrip("/")))
        if path.is_file():
            return super().do_GET()
        if not self.path.startswith(("/assets/", "/static/")):
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, fmt, *args):
        if "/assets/" not in args[1] and "/@fs/" not in args[1]:
            super().log_message(fmt, *args)

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 5899), SPAHandler)
    print("dashboard static server on http://0.0.0.0:5899")
    server.serve_forever()
