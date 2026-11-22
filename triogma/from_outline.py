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


# Type markers usable at the start of any outline line. [note] bodies absorb
# following indented lines; good/bad/root are single-line coloured boxes that
# still nest children like a plain box.
_MARKERS = {
    "[note]": "note",
    "[good]": "good",
    "[bad]": "bad",
    "[root]": "root",
}


def parse_outline(path):
    nodes, edges, stack = [], [], []
    pending, pending_indent = None, 0
    ident = 0

    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            # Expand leading tabs so tab- or space-indented outlines both work.
            raw = raw.expandtabs(2)
            if not raw.strip():
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            text = raw.strip()
            if text.startswith("#") or text.lower().startswith("title:"):
                continue

            starts_entry = text.startswith("- ") or any(
                text.startswith(mk) for mk in _MARKERS)
            # A note absorbs only its BODY: lines indented DEEPER than the marker.
            # A sibling at the same indent (indent == pending_indent) is NOT body.
            if (pending is not None and indent > pending_indent
                    and not starts_entry):
                nodes[pending]["label"] += "\n" + text
                continue
            pending = None

            while stack and indent <= stack[-1][0]:
                stack.pop()

            ident += 1
            nid = f"n{ident}"
            marker = next((mk for mk in _MARKERS if text.startswith(mk)), None)
            if marker:
                kind, label = _MARKERS[marker], text[len(marker):].strip()
                if kind == "note":
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


def read_title(src):
    with open(src, encoding="utf-8") as fh:
        for line in fh:
            if line.strip().lower().startswith("title:"):
                return line.split(":", 1)[1].strip()
    return ""


def bake_layout(board, scheme="pro"):
    """Fill in x/y (and box w/h) from the renderer's tree layout. The renderer
    re-lays-out on its own, but the browser editor reads coordinates straight from
    the JSON and does NOT auto-layout — without them it stacks nodes at the origin."""
    try:
        import render
        sch = render.SCHEMES.get(scheme, render.SCHEMES["pro"])
        positioned = {p.id: p for p in render.auto_tree_layout(board, sch)}
        for nd in board["nodes"]:
            p = positioned.get(nd["id"])
            if p is None:
                continue
            nd["x"], nd["y"] = round(p.x), round(p.y)
            if nd["kind"] != "note":  # notes are re-sized by the editor from text
                nd["w"], nd["h"] = round(p.w), round(p.h)
    except Exception as exc:  # layout is best-effort; never block the conversion
        print(f"warn   : could not bake layout coordinates ({exc})")
    return board


def build_board(src, scheme="pro", title=None):
    """Parse an outline file into a ready-to-render board dict (coordinates baked)."""
    if title is None:
        title = read_title(src)
    nodes, edges = parse_outline(src)
    # mark top-level boxes as roots for accent colouring
    has_parent = {e["to"] for e in edges}
    for n in nodes:
        if n["id"] not in has_parent and n["kind"] == "box":
            n["kind"] = "root"
    board = {
        "title": title or os.path.splitext(os.path.basename(src))[0],
        "scheme": scheme,
        "nodes": nodes,
        "edges": edges,
        "meta": {"version": 1, "app": "dsh-boards"},
    }
    return bake_layout(board, scheme)


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

    title = None
    if "--title" in sys.argv:
        i = sys.argv.index("--title")
        title = sys.argv[i + 1] if i + 1 < len(sys.argv) else None

    board = build_board(src, scheme, title)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(board, fh, indent=2)

    print(f"outline: {src}")
    print(f"nodes  : {len(board['nodes'])}  edges: {len(board['edges'])}")
    print(f"board  : {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
