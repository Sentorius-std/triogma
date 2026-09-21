#!/usr/bin/env python3
"""
boards.py - serve a Figma-like board editor on localhost and render boards to PNG.

    python3 boards.py [--port 8770] [--board board.json]

Endpoints
    GET  /                the editor
    GET  /api/board       current board JSON
    POST /api/board       save board JSON (atomic)
    POST /api/render      render board -> PNG

The board JSON is the single source of truth. `render.py` reads the same file,
so the PNG and the GUI never drift apart.
"""

import argparse
import json
import os
import socketserver
import threading
import http.server

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BOARD = os.path.join(HERE, "board.json")
PORT = 8770

SB = None  # set in main()


def blank_board(title="Untitled board"):
    return {
        "title": title,
        "scheme": "pro",
        "nodes": [],
        "edges": [],
        "meta": {"version": 1, "app": "dsh-boards"},
    }


def read_board(path=None):
    path = path or SB["path"]
    if not os.path.exists(path):
        return blank_board()
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_board(data, path=None):
    path = path or SB["path"]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "dsh-boards"

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj))

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "ui.html"), "r", encoding="utf-8") as fh:
                self._send(200, fh.read(), "text/html; charset=utf-8")
        elif self.path == "/api/board":
            try:
                self._json(read_board())
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, 500)
        elif self.path == "/api/meta":
            self._json({"board": SB["path"], "port": SB["port"]})
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""

        if self.path == "/api/board":
            try:
                data = json.loads(raw.decode("utf-8"))
                write_board(data)
                self._json({"ok": True, "nodes": len(data.get("nodes", []))})
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)}, 400)

        elif self.path == "/api/render":
            try:
                import render
                board = json.loads(raw.decode("utf-8")) if raw else read_board()
                out = os.path.join(HERE, "board.png")
                render.render_board(board, out)
                self._json({"ok": True, "png": out})
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)}, 500)
        else:
            self._send(404, "not found", "text/plain")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--board", default=DEFAULT_BOARD)
    args = ap.parse_args()

    global SB
    SB = {"path": os.path.abspath(args.board), "port": args.port}

    if not os.path.exists(SB["path"]):
        write_board(blank_board())

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), Handler) as httpd:
        print(f"editor : http://127.0.0.1:{args.port}/")
        print(f"board  : {SB['path']}")
        print("Ctrl-C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
