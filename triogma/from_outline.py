#!/usr/bin/env python3
"""
from_outline.py - convert an indented outline into board JSON.

    python3 from_outline.py tree.txt board.json [--scheme pro|hand] [--title "..."]

Outline rules
    ATO                     box
      Password Reset        child box
        - None Header       leaf box
        [note] free text    note box (following indented lines are its body)

After conversion open the board in the GUI (boards.py) to drag nodes, recolour
them, or add more - the JSON is the source of truth.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def parse_outline(path):
    nodes, edges, stack = [], [], []
    pending, pending_indent = None, 0
    ident = 0

    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            text = raw.strip()
            if text.startswith("#") or text.lower().startswith("title:"):
                continue

            if (pending is not None and indent >= pending_indent
                    and not text.startswith("[note]")
                    and not text.startswith("- ")):
                nodes[pending]["label"] += "\n" + text
                continue
            pending = None

            while stack and indent <= stack[-1][0]:
                stack.pop()

            ident += 1
            nid = f"n{ident}"
            if text.startswith("[note]"):
                kind, label = "note", text[len("[note]"):].strip()
                pending, pending_indent = len(nodes), indent
            elif text.startswith("- "):
                kind, label = "box", text[2:].strip()
            else:
                kind, label = "box", text

            nodes.append({"id": nid, "label": label, "kind": kind})
            if stack:
                edges.append({"from": stack[-1][1], "to": nid})
            stack.append((indent, nid))

    return nodes, edges


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return 1

    src, dst = args[0], args[1]
    scheme = "pro"
    if "--scheme" in sys.argv:
        i = sys.argv.index("--scheme")
        scheme = sys.argv[i + 1] if i + 1 < len(sys.argv) else "pro"

    title = ""
    with open(src, encoding="utf-8") as fh:
        for line in fh:
            if line.strip().lower().startswith("title:"):
                title = line.split(":", 1)[1].strip()
                break

    nodes, edges = parse_outline(src)

    # mark top-level boxes as roots for accent colouring
    has_parent = {e["to"] for e in edges}
    for n in nodes:
        if n["id"] not in has_parent:
            n["kind"] = "root" if n["kind"] == "box" else n["kind"]

    board = {
        "title": title or os.path.splitext(os.path.basename(src))[0],
        "scheme": scheme,
        "nodes": nodes,
        "edges": edges,
        "meta": {"version": 1, "app": "dsh-boards"},
    }

    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(board, fh, indent=2)

    print(f"outline: {src}")
    print(f"nodes  : {len(nodes)}  edges: {len(edges)}")
    print(f"board  : {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
