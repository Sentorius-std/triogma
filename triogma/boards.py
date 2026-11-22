#!/usr/bin/env python3
"""
boards.py - serve the board editor on localhost with an in-browser board picker.

    python3 boards.py [--port 8770] [--boards-dir ../methodology] [--board FILE]

With no --board, it auto-discovers every outline (*.txt) in the boards directory
(default: the sibling `methodology/` folder) and lets you switch between them from
a dropdown in the web UI — no need to pre-convert anything.

Endpoints
    GET  /                 the editor
    GET  /api/boards       list of available boards [{name, title}]
    GET  /api/board?name=X current board JSON (generated from X.txt, or X.json if saved)
    POST /api/board?name=X save board JSON -> X.json
    POST /api/render       render a board -> X.png

A board named X is generated fresh from methodology/X.txt unless a methodology/X.json
exists (written when you Save), which then takes precedence so edits persist.
"""

import argparse
import json
import os
import re
import socketserver
import http.server
from urllib.parse import urlparse, parse_qs

import from_outline

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BOARDS_DIR = os.path.join(os.path.dirname(HERE), "methodology")
PORT = 8770
_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")

SB = None  # set in main()


def blank_board(title="Untitled board"):
    return {"title": title, "scheme": "pro", "nodes": [], "edges": [],
            "meta": {"version": 1, "app": "dsh-boards"}}


def _safe_name(name):
    return bool(name) and bool(_SAFE.match(name))


def list_boards():
    """Every board in the directory, by basename, titled from its outline/json."""
    out = {}
    d = SB["dir"]
    if not os.path.isdir(d):
        return []
    for fn in os.listdir(d):
        stem, ext = os.path.splitext(fn)
        if ext not in (".txt", ".json") or not _safe_name(stem):
            continue
        if stem in out:
            continue
        title = stem
        try:
            if ext == ".txt":
                title = from_outline.read_title(os.path.join(d, fn)) or stem
            else:
                with open(os.path.join(d, fn), encoding="utf-8") as fh:
                    title = (json.load(fh).get("title") or stem)
        except Exception:
            pass
        out[stem] = {"name": stem, "title": title}
    return sorted(out.values(), key=lambda b: b["title"].lower())


def load_board(name):
    """Prefer a saved X.json (keeps edits); otherwise generate from X.txt."""
    d = SB["dir"]
    jp = os.path.join(d, name + ".json")
    tp = os.path.join(d, name + ".txt")
    if os.path.exists(jp):
        with open(jp, encoding="utf-8") as fh:
            return json.load(fh)
    if os.path.exists(tp):
        return from_outline.build_board(tp)
    return blank_board(name)


def save_board(name, data):
    path = os.path.join(SB["dir"], name + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def _default_name():
    if SB.get("default"):
        return SB["default"]
    boards = list_boards()
    names = [b["name"] for b in boards]
    if "global" in names:          # the architecture overview is the natural landing
        return "global"
    return names[0] if names else None


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

    def _query_name(self, parsed):
        q = parse_qs(parsed.query)
        name = (q.get("name") or [None])[0]
        return name if (name and _safe_name(name)) else None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "ui.html"), "r", encoding="utf-8") as fh:
                self._send(200, fh.read(), "text/html; charset=utf-8")
        elif parsed.path == "/api/boards":
            self._json({"boards": list_boards(), "default": _default_name()})
        elif parsed.path == "/api/board":
            name = self._query_name(parsed) or _default_name()
            if not name:
                self._json(blank_board())
                return
            try:
                self._json(load_board(name))
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, 500)
        elif parsed.path == "/api/meta":
            self._json({"dir": SB["dir"], "port": SB["port"]})
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""

        if parsed.path == "/api/board":
            name = self._query_name(parsed)
            if not name:
                self._json({"ok": False, "error": "missing or invalid board name"}, 400)
                return
            try:
                data = json.loads(raw.decode("utf-8"))
                save_board(name, data)
                self._json({"ok": True, "name": name, "nodes": len(data.get("nodes", []))})
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)}, 400)

        elif parsed.path == "/api/render":
            try:
                import render
                payload = json.loads(raw.decode("utf-8")) if raw else {}
                board = payload.get("board") or payload or load_board(_default_name())
                name = payload.get("name")
                out = os.path.join(SB["dir"], name + ".png") if (name and _safe_name(name)) \
                    else os.path.join(HERE, "board.png")
                render.render_board(board, out)
                self._json({"ok": True, "png": out})
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)}, 500)
        else:
            self._send(404, "not found", "text/plain")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--boards-dir", default=DEFAULT_BOARDS_DIR,
                    help="directory of board outlines (*.txt) to serve")
    ap.add_argument("--board", default=None,
                    help="optional: open this board/file first (its folder becomes the boards dir)")
    args = ap.parse_args()

    global SB
    if args.board:
        bp = os.path.abspath(args.board)
        SB = {"dir": os.path.dirname(bp),
              "default": os.path.splitext(os.path.basename(bp))[0],
              "port": args.port}
    else:
        SB = {"dir": os.path.abspath(args.boards_dir), "default": None, "port": args.port}

    boards = list_boards()
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), Handler) as httpd:
        print(f"editor : http://127.0.0.1:{args.port}/")
        print(f"boards : {SB['dir']}  ({len(boards)} found)")
        for b in boards:
            print(f"         - {b['name']}  ({b['title']})")
        print("Ctrl-C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
