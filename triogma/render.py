#!/usr/bin/env python3
"""
render.py - render a board JSON to a clean, presentation-grade PNG.

    python3 render.py board.json [out.png] [--scheme pro|hand]

Two schemes:
    pro  - modern sans, soft shadows, coloured accent rails, tinted canvas
    hand - the handwriting/excalidraw look

`boards.py` calls render_board() so the GUI and the CLI produce identical output.
"""

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")

# ---------------------------------------------------------------- schemes
SCHEMES = {
    "pro": {
        "canvas": (248, 249, 251),
        "grid": (226, 229, 234),
        "grid_pitch": 24,
        "grid_dots": False,
        "node_fill": (255, 255, 255),
        "node_stroke": (203, 210, 220),
        "text": (23, 32, 46),
        "muted": (100, 116, 139),
        "edge": (148, 163, 184),
        "title": (15, 23, 42),
        "shadow": True,
        "accent": True,
        "font": "Inter",
        "hand": False,
        "radius": 10,
        "title_size": 30,
        "node_size": 20,
        "note_size": 18,
        "pad_x": 18,
        "pad_y": 14,
        "line_h": 26,
    },
    "hand": {
        "canvas": (247, 247, 245),
        "grid": (212, 212, 208),
        "grid_pitch": 20,
        "grid_dots": True,
        "node_fill": (255, 255, 255),
        "node_stroke": (45, 45, 45),
        "text": (20, 20, 20),
        "muted": (90, 90, 90),
        "edge": (45, 45, 45),
        "title": (20, 20, 20),
        "shadow": False,
        "accent": False,
        "font": "PatrickHand",
        "hand": True,
        "radius": 6,
        "title_size": 26,
        "node_size": 20,
        "note_size": 16,
        "pad_x": 14,
        "pad_y": 10,
        "line_h": 20,
    },
}

# accent rails by node kind
ACCENTS = {
    "root": (79, 70, 229),
    "box": (37, 99, 235),
    "note": (217, 119, 6),
    "good": (22, 163, 74),
    "bad": (220, 38, 38),
}


def _fontfile(name):
    candidates = {
        "Inter": ["Inter-Regular.ttf", "Inter-Medium.ttf", "DejaVuSans.ttf"],
        "InterBold": ["Inter-SemiBold.ttf", "Inter-Bold.ttf", "DejaVuSans-Bold.ttf"],
        "PatrickHand": ["PatrickHand.ttf"],
    }[name]
    for c in candidates:
        for base in (FONT_DIR, "/usr/share/fonts/truetype/dejavu"):
            p = os.path.join(base, c)
            if os.path.exists(p):
                return p
    return None


_FCACHE = {}


def _font(name, size):
    key = (name, size)
    if key not in _FCACHE:
        path = _fontfile(name)
        try:
            _FCACHE[key] = ImageFont.truetype(path, size) if path else ImageFont.load_default()
        except OSError:
            _FCACHE[key] = ImageFont.load_default()
    return _FCACHE[key]


_MEASURE = ImageDraw.Draw(Image.new("RGB", (8, 8)))


def tw(s, font):
    return _MEASURE.textlength(s, font=font)


# ---------------------------------------------------------------- wrapping
def wrap(text, font, max_w):
    out = []
    for para in str(text).split("\n"):
        words, line = para.split(), ""
        for w in words:
            cand = f"{line} {w}".strip()
            if tw(cand, font) <= max_w or not line:
                line = cand
            else:
                out.append(line)
                line = w
        out.append(line)
    return out or [""]


# ---------------------------------------------------------------- layout
class N:
    def __init__(self, d):
        self.id = d.get("id") or d.get("label", "n")[:12]
        self.label = d.get("label", "")
        self.kind = d.get("kind", "box")
        self.color = d.get("color")  # optional custom accent
        self.x = float(d.get("x", 0))
        self.y = float(d.get("y", 0))
        self.w = float(d.get("w", 0))
        self.h = float(d.get("h", 0))
        self.children = []
        self.lines = []
        self.depth = 0


def build_nodes(board, sch):
    nodes = [N(d) for d in board.get("nodes", [])]
    by_id = {n.id: n for n in nodes}
    edges = board.get("edges", [])

    if edges:
        for e in edges:
            src, dst = by_id.get(e.get("from")), by_id.get(e.get("to"))
            if src is not None and dst is not None:
                src.children.append(dst)

    # auto-size anything without explicit dimensions
    fnode = _font(sch["font"], sch["node_size"])
    fnote = _font(sch["font"], sch["note_size"])
    for n in nodes:
        font = fnote if n.kind == "note" else fnode
        maxw = 340 if n.kind == "note" else 420
        if not n.w:
            n.lines = wrap(n.label, font, maxw)
            widest = max((tw(l, font) for l in n.lines), default=0)
            n.w = max(90, widest + 2 * sch["pad_x"] + (10 if sch["accent"] else 0))
        else:
            n.lines = str(n.label).split("\n")
        if not n.h:
            n.h = max(46, len(n.lines) * sch["line_h"] + 2 * sch["pad_y"])
    return nodes, by_id, edges


def auto_tree_layout(board, sch):
    """Assign x/y to nodes with no explicit position, using the edge tree."""
    fnode = _font(sch["font"], sch["node_size"])
    fnote = _font(sch["font"], sch["note_size"])
    nodes, by_id, edges = build_nodes(board, sch)

    if not edges:
        return nodes

    has_parent = {e["to"] for e in edges}
    roots = [n for n in nodes if n.id not in has_parent]
    for r in roots:
        stack, d = [(r, 0)], []
        while stack:
            nd, depth = stack.pop()
            nd.depth = max(nd.depth, depth)
            for c in nd.children:
                stack.append((c, depth + 1))

    widths = {}
    for n in nodes:
        widths[n.depth] = max(widths.get(n.depth, 0), n.w)
    xs, acc = {}, 0.0
    for d in sorted(widths):
        xs[d] = acc
        acc += widths[d] + 64

    def place(n, top):
        if not n.children:
            n.x, n.y = xs[n.depth], top
            return n.h, n.y + n.h / 2
        t, mids = top, []
        for c in n.children:
            h, mid = place(c, t)
            t += h + 26
            mids.append(mid)
        mid = (mids[0] + mids[-1]) / 2
        n.x = xs[n.depth]
        n.y = mid - n.h / 2
        return t - 26 - top, mid

    cur = 110.0
    for r in roots:
        h, _ = place(r, cur)
        cur += h + 54
    return nodes


# ---------------------------------------------------------------- drawing
def _rounded(d, box, r, fill=None, outline=None, width=2):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def _shadow(img, box, r, spread=7, alpha=22):
    """Soft drop shadow approximated with concentric rounded rects."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    for i in range(spread, 0, -1):
        a = int(alpha * (1 - i / (spread + 1)) ** 1.6) + 3
        ld.rounded_rectangle([x0 - i, y0 - i + 2, x1 + i, y1 + i + 2],
                             radius=r + i, fill=(15, 23, 42, a))
    return Image.alpha_composite(img.convert("RGBA"), layer)


def elbow_path(d, x1, y1, x2, y2, color, width=2, radius=18):
    midx = x1 + (x2 - x1) * 0.45
    dy = y2 - y1
    if abs(dy) < 2:
        d.line([(x1, y1), (x2, y2)], fill=color, width=width)
        return
    sgn = 1 if dy > 0 else -1
    pts = [(x1, y1), (midx - radius, y1)]
    for i in range(1, 8):
        t = i / 7
        pts.append((midx - radius + radius * t, y1 + sgn * radius * t))
    pts.append((midx, y2 - sgn * radius))
    for i in range(1, 8):
        t = i / 7
        pts.append((midx + radius * t, y2 - sgn * radius + sgn * radius * t))
    pts.append((x2, y2))
    d.line(pts, fill=color, width=width, joint="curve")


def render_board(board, out_png, scheme=None):
    sch = SCHEMES.get(scheme or board.get("scheme", "pro"), SCHEMES["pro"])
    SS = 2

    nodes = auto_tree_layout(board, sch)
    if not nodes:
        Image.new("RGB", (800, 400), sch["canvas"]).save(out_png)
        return out_png, 800, 400

    fnode = _font(sch["font"], sch["node_size"])
    fnote = _font(sch["font"], sch["note_size"])
    ftitle = _font("InterBold" if not sch["hand"] else "PatrickHand",
                   sch["title_size"])

    pad = 70
    W = int(max(n.x + n.w for n in nodes) + pad)
    H = int(max(n.y + n.h for n in nodes) + pad)
    W, H = max(W, 700), max(H, 420)

    img = Image.new("RGB", (W * SS, H * SS), sch["canvas"])
    d = ImageDraw.Draw(img)

    # background grid
    pitch = sch["grid_pitch"] * SS
    if sch["grid_dots"]:
        for gy in range(0, H * SS, pitch):
            for gx in range(0, W * SS, pitch):
                d.ellipse([gx - 1.6, gy - 1.6, gx + 1.6, gy + 1.6], fill=sch["grid"])
    else:
        for gx in range(0, W * SS, pitch):
            d.line([(gx, 0), (gx, H * SS)], fill=sch["grid"], width=1)
        for gy in range(0, H * SS, pitch):
            d.line([(0, gy), (W * SS, gy)], fill=sch["grid"], width=1)

    def S(v):
        return v * SS

    # edges under nodes
    by_id = {n.id: n for n in nodes}
    for e in board.get("edges", []):
        src, dst = by_id.get(e.get("from")), by_id.get(e.get("to"))
        if not src or not dst:
            continue
        elbow_path(d, S(src.x + src.w), S(src.y + src.h / 2),
                   S(dst.x), S(dst.y + dst.h / 2),
                   sch["edge"], width=max(2, SS + (0 if sch["hand"] else 0)))

    # shadow pass
    if sch["shadow"]:
        for n in nodes:
            img = _shadow(img, (S(n.x), S(n.y), S(n.x + n.w), S(n.y + n.h)),
                          int(sch["radius"] * SS))
        d = ImageDraw.Draw(img)

    # nodes
    for n in nodes:
        x, y, w, h = S(n.x), S(n.y), S(n.w), S(n.h)
        r = int(sch["radius"] * SS)
        _rounded(d, [x, y, x + w, y + h], r, fill=sch["node_fill"],
                 outline=sch["node_stroke"], width=max(1, SS))

        if sch["accent"]:
            accent = n.color if isinstance(n.color, (list, tuple)) else None
            if accent is None:
                accent = ACCENTS.get(n.kind, ACCENTS["box"])
            rail_w = 4 * SS
            d.rounded_rectangle([x, y, x + rail_w * 2, y + h],
                                radius=int(2.5 * SS), fill=tuple(accent))

        font = fnote if n.kind == "note" else fnode
        colour = sch["muted"] if n.kind == "note" else sch["text"]
        block = len(n.lines) * sch["line_h"] * SS
        cy = y + (h - block) / 2
        left = x + S(sch["pad_x"]) + (S(12) if sch["accent"] else 0)
        for i, ln in enumerate(n.lines):
            if n.kind == "note":
                d.text((left, cy + i * sch["line_h"] * SS), ln, font=font, fill=colour)
            else:
                lw = tw(ln, font)
                avail = (x + w) - left
                d.text((left + (avail - lw) / 2, cy + i * sch["line_h"] * SS),
                       ln, font=font, fill=colour)

    if board.get("title"):
        d.text((S(34), S(26)), board["title"], font=ftitle, fill=sch["title"])
        d.line([(S(34), S(72)), (S(34) + S(60), S(72))], fill=ACCENTS["root"],
               width=max(2, 3 * SS))

    img = img.resize((W, H), Image.LANCZOS)
    img.save(out_png)
    return out_png, W, H


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    scheme = None
    for a in sys.argv[1:]:
        if a.startswith("--scheme"):
            scheme = a.split("=", 1)[1] if "=" in a else None
    if "--scheme" in sys.argv:
        i = sys.argv.index("--scheme")
        scheme = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        args = [a for a in args if a != scheme]

    if not args:
        print(__doc__)
        return 1

    src = args[0]
    out = args[1] if len(args) > 1 else os.path.splitext(src)[0] + ".png"
    with open(src, encoding="utf-8") as fh:
        board = json.load(fh)

    p, W, H = render_board(board, out, scheme)
    print(f"board : {src}")
    print(f"nodes : {len(board.get('nodes', []))}")
    print(f"canvas: {W}x{H}")
    print(f"png   : {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
