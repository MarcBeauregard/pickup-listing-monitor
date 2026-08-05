#!/usr/bin/env python3
"""Serveur local de démonstration du tableau et du contrôle (jamais en production)."""

from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "docs"


class PreviewHandler(SimpleHTTPRequestHandler):
    control_state = "running"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path == "/api/state":
            self.send_json({"state": type(self).control_state, "user": "preview@local"})
            return
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/control":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if body.get("action") == "pause":
            type(self).control_state = "paused"
        elif body.get("action") == "resume":
            type(self).control_state = "running"
        else:
            self.send_json({"error": "action invalide"}, status=400)
            return
        self.send_json({"state": type(self).control_state, "user": "preview@local"})

    def send_json(self, body, status=200):
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 4173), PreviewHandler)
    print("Preview: http://127.0.0.1:4173/?controlApi=http://127.0.0.1:4173", flush=True)
    server.serve_forever()

