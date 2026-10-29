"""Scene visuals. Each draws one frame of its animation into the visual area.

Style: flat editorial "data traces" in the avatar's palette (cream, navy, one coral
accent). Dots are people, lines are traces, coral marks the thing being decoded.
Everything is drawn at 2x and downsampled for anti-aliasing.
"""
from __future__ import annotations

import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw

from . import icons as iconset
from .config import CORAL, CREAM, NAVY
from .fonts import fit, font

VW, VH = 920, 820
S = 2  # supersampling factor
WHITE = (255, 252, 246)
NAVY_20 = (29, 42, 92, 50)
NAVY_40 = (29, 42, 92, 105)
CORAL_30 = (255, 107, 74, 80)


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def ease(x: float) -> float:
    x = clamp(x)
    return 1 - (1 - x) ** 3


def stage(p: float, start: float, length: float) -> float:
    """Eased 0..1 progress of a sub-animation that runs from start to start+length (in scene progress)."""
    return ease((p - start) / length) if length > 0 else float(p >= start)


def mix(a, b, k: float):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


class Canvas:
    def __init__(self):
        self.img = Image.new("RGBA", (VW * S, VH * S), CREAM + (0,))
        self.d = ImageDraw.Draw(self.img, "RGBA")

    def circle(self, x, y, r, fill=None, outline=None, width=0):
        self.d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=fill,
                       outline=outline, width=int(width * S))

    def line(self, pts, fill, width):
        sp = [(x * S, y * S) for x, y in pts]
        self.d.line(sp, fill=fill, width=int(width * S), joint="curve")
        r = width / 2
        for x, y in (pts[0], pts[-1]):
            self.circle(x, y, r, fill=fill)

    def rrect(self, box, r, fill=None, outline=None, width=0):
        x0, y0, x1, y1 = box
        self.d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=r * S, fill=fill,
                                 outline=outline, width=int(width * S))

    def text(self, xy, s, weight, size, fill, anchor="la"):
        self.d.text((xy[0] * S, xy[1] * S), s, font=font(weight, size * S), fill=fill, anchor=anchor)

    def text_block(self, x, y, lines, weight, size, fill, gap=1.25, anchor="la"):
        for i, ln in enumerate(lines):
            self.text((x, y + i * size * gap), ln, weight, size, fill, anchor=anchor)
        return y + len(lines) * size * gap

    def arc(self, cx, cy, r, start, end, fill, width):
        self.d.arc([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], start, end,
                   fill=fill, width=int(width * S))

    def icon(self, name: str, cx, cy, size, color, alpha: float = 1.0) -> bool:
        """Paste a Tabler icon centered at (cx, cy). Returns False if it can't be drawn."""
        if not name or alpha <= 0 or size < 4:
            return False
        q = max(1, round(alpha * 8))  # quantized so the tinted images cache well
        img = _icon(name, int(size * S) // 12 * 12 or 12, color, q)  # size steps keep the cache warm
        if img is None:
            return False
        self.img.alpha_composite(img, (int(cx * S - img.width / 2), int(cy * S - img.height / 2)))
        return True

    def finish(self) -> Image.Image:
        return self.img.reduce(S)


@lru_cache(maxsize=4096)
def _icon(name: str, px: int, color, q: int):
    img = iconset.image(name, px, tuple(color[:3]), 1.6 if px > 160 else 2.0)
    if img is None or q >= 8:
        return img
    a = img.getchannel("A").point(lambda v: v * q // 8)
    img = img.copy()
    img.putalpha(a)
    return img


def back(x: float) -> float:
    """Ease with a small overshoot, for things that pop in."""
    x = clamp(x)
    c1 = 1.70158
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


def chips(c: Canvas, labels: list[str], y: float, p: float, start: float = 0.35, accent: int = -1):
    """Row of rounded label chips, centered."""
    if not labels:
        return
    size = 34
    f = font("bold", size)
    widths = [min(f.getlength(l), 380) + 48 for l in labels]
    rows, row, w = [], [], 0
    for lab, wd in zip(labels, widths):
        if row and w + wd + 18 > VW - 40:
            rows.append(row)
            row, w = [], 0
        row.append((lab, wd))
        w += wd + 18
    rows.append(row)
    k = 0
    for ri, row in enumerate(rows):
        total = sum(wd for _, wd in row) + 18 * (len(row) - 1)
        x = (VW - total) / 2
        for lab, wd in row:
            a = stage(p, start + 0.08 * k, 0.15)
            if a > 0:
                yy = y + ri * 78 + (1 - a) * 20
                hot = k == accent
                c.rrect((x, yy, x + wd, yy + 62), 31, fill=(CORAL if hot else NAVY) + (int(255 * a),))
                c.text((x + wd / 2, yy + 31), lab, "bold", size, CREAM + (int(255 * a),), anchor="mm")
            x += wd + 18
            k += 1


# ---------------------------------------------------------------- scenes

def fingerprint(c: Canvas, cx, cy, scale, p, coral_ring=3, rings=9, seed=7):
    """The avatar motif: nested arcs whose ends stretch out to the right as data bars."""
    rnd = random.Random(seed)
    lengths = [rnd.uniform(0.35, 1.0) for _ in range(rings * 2)]
    gap = 26 * scale
    width = 13 * scale
    for i in range(rings):
        r = gap * (i + 1)
        col = CORAL if i == coral_ring else NAVY
        a = stage(p, 0.03 * (rings - i), 0.35)
        if a <= 0:
            continue
        c.arc(cx, cy, r, 90, 90 + 180 * a, col, width)
        if a >= 1:
            b = stage(p, 0.3 + 0.03 * i, 0.4)
            for j, yy in enumerate((cy - r, cy + r)):
                ln = 30 * scale + lengths[2 * i + j] * 330 * scale * b
                c.line([(cx, yy), (cx + ln, yy)], col, width)


def v_hook(c: Canvas, sc, p, ctx):
    fingerprint(c, 300, 210, 0.7, 0.3 + p)  # already half drawn on frame 0, still growing
    text = sc.big_text or sc.lines[0]
    f, lines = fit(text, "black", VW - 80, [116, 104, 92], 2)
    if len(lines) > 2:  # three lines must stay below the motif and inside the canvas
        f, lines = fit(text, "black", VW - 80, [92, 80, 68], 3)
    # The hook text is fully there on frame 0 (no fade-in) and gives a small pulse while the
    # first line is spoken, so the opening frame reads at a glance and still moves.
    pulse = 1 + 0.04 * math.sin(min(p, 0.5) * 2 * math.pi)
    size = int(f.size * pulse)
    y = 640 - (len(lines) - 1) * size * 0.6
    for k, ln in enumerate(lines):
        c.text((VW / 2, y), ln, "black", size, (CORAL if k == len(lines) - 1 and len(lines) > 1 else NAVY) + (255,),
               anchor="mm")
        y += size * 1.2


def v_paper(c: Canvas, sc, p, ctx):
    paper = ctx["paper"]
    f, lines = fit(ctx["paper_title"], "black", VW - 200, [58, 52, 46, 40], 5)
    en_size = 30
    en = fit(paper["title"], "regular", VW - 200, [30, 27], 4)[1] if ctx["lang"] != "en" else []
    authors = paper.get("authors") or []
    height = 214 + len(lines) * f.size * 1.3 + 18 + len(en) * en_size * 1.35 + (90 if authors else 0) + 50
    a = stage(p, 0.0, 0.25)
    y0 = (VH - height) / 2 + (1 - a) * 80
    c.rrect((48, y0 + 14, VW - 32, y0 + height + 14), 36, fill=NAVY_20)
    c.rrect((40, y0, VW - 40, y0 + height), 36, fill=WHITE + (int(255 * a),), outline=NAVY, width=4)
    pill = {"zh": "論文 PAPER", "pt": "NOVO ESTUDO"}.get(ctx["lang"], "NEW PAPER")
    c.rrect((90, y0 + 56, 90 + font("bold", 30).getlength(pill) + 44, y0 + 112), 28, fill=CORAL)
    c.text((112, y0 + 84), pill, "bold", 30, CREAM, anchor="lm")
    venue = f"{paper['venue']} · {paper.get('published', '')[:4]}".strip(" ·")
    c.text((90, y0 + 150), venue, "bold", 34, CORAL)
    y = c.text_block(90, y0 + 214, lines, "black", f.size, NAVY, gap=1.3)
    y = c.text_block(90, y + 18, en, "regular", en_size, NAVY_40[:3] + (200,), gap=1.35)
    if authors:
        who = ", ".join(authors[:2]) + (" et al." if len(authors) > 2 else "")
        c.text((90, y + 40), who[:60], "bold", 30, NAVY)
    # a stamp that lands on the card
    b = stage(p, 0.35, 0.12)
    if b > 0:
        cx, cy, r = VW - 150, y0 + 84, 70 + (1 - b) * 40
        c.circle(cx, cy, r, outline=CORAL + (int(230 * b),), width=6)
        c.text((cx, cy), "NOVO" if ctx["lang"] == "pt" else "NEW", "black", 36 if ctx["lang"] == "pt" else 40, CORAL + (int(230 * b),), anchor="mm")


def person(c: Canvas, x, y, r, col):
    c.circle(x, y - r * 0.55, r * 0.42, fill=col)
    c.d.pieslice([(x - r * 0.75) * S, (y - r * 0.05) * S, (x + r * 0.75) * S, (y + r * 1.4) * S],
                 180, 360, fill=col)


def v_crowd(c: Canvas, sc, p, ctx):
    rnd = random.Random(ctx["seed"])
    if sc.icons and iconset.image(sc.icons[0], 32, NAVY) is not None:
        return _icon_crowd(c, sc, p, ctx, rnd)
    cols, rows = 10, 8
    gx, gy = VW / (cols + 1), 560 / (rows + 0.5)
    hot = {i for i in range(cols * rows) if rnd.random() < 0.22}
    t = ctx["t"]
    for i in range(cols * rows):
        cx = gx * (i % cols + 1)
        cy = 70 + gy * (i // cols + 0.5)
        a = stage(p, 0.004 * i, 0.12)
        if a <= 0:
            continue
        k = stage(p, 0.45 + 0.002 * i, 0.15) if i in hot else 0
        col = mix(NAVY, CORAL, k) + (int(255 * a),)
        bob = math.sin(t * 2.2 + i) * 3 * k
        person(c, cx, cy + bob, 26 * (0.6 + 0.4 * a), col)
    chips(c, sc.labels, 640, p, accent=len(sc.labels) - 1 if len(sc.labels) > 1 else -1)


def _icon_crowd(c: Canvas, sc, p, ctx, rnd):
    """Many copies of the thing studied (cattle, phones, people...); some light up coral."""
    cols, rows = 6, 5
    gx, gy = VW / (cols + 1), 560 / (rows + 0.3)
    hot = {i for i in range(cols * rows) if rnd.random() < 0.22}
    t = ctx["t"]
    for i in range(cols * rows):
        cx = gx * (i % cols + 1) + (gx / 2 if (i // cols) % 2 else 0) - gx / 4
        cy = 80 + gy * (i // cols + 0.5)
        a = stage(p, 0.006 * i, 0.12)
        if a <= 0:
            continue
        k = stage(p, 0.45 + 0.002 * i, 0.15) if i in hot else 0
        col = CORAL if k > 0.5 else NAVY
        bob = math.sin(t * 2.2 + i) * 4 * k
        c.icon(sc.icons[0], cx, cy + bob, 100 * (0.7 + 0.3 * back(a)), col, a)
    chips(c, sc.labels, 640, p, accent=len(sc.labels) - 1 if len(sc.labels) > 1 else -1)


def v_icons(c: Canvas, sc, p, ctx):
    """2-4 concrete things or actors in the study, each a card with its icon and name."""
    labels = sc.labels or [sc.heading]
    names = (sc.icons + [""] * len(labels))[: len(labels)]
    n = len(labels)
    t = ctx["t"]
    if n <= 3:  # one row, linked by arrows: reads as a flow from left to right
        w = min(270, (VW - 60 - 40 * (n - 1)) / n)
        h = 380
        x0 = (VW - (n * w + 40 * (n - 1))) / 2
        boxes = [(x0 + i * (w + 40), (VH - h) / 2 - 20, w, h) for i in range(n)]
    else:
        w, h = 400, 330
        boxes = [(50 + (i % 2) * (w + 20), 60 + (i // 2) * (h + 30), w, h) for i in range(n)]
    for i, (x, y, bw, bh) in enumerate(boxes):
        a = stage(p, 0.05 + 0.14 * i, 0.18)
        if a <= 0:
            continue
        pop = back((p - 0.05 - 0.14 * i) / 0.18)
        hot = i == n - 1 and n > 1
        bob = math.sin(t * 1.8 + i * 1.3) * 5
        yy = y + (1 - a) * 40
        c.rrect((x + 8, yy + 12, x + bw + 8, yy + bh + 12), 32, fill=NAVY_20)
        c.rrect((x, yy, x + bw, yy + bh), 32, fill=(CORAL if hot else WHITE) + (int(255 * a),), outline=NAVY, width=4)
        size = min(bw, bh) * 0.55 * pop
        drawn = c.icon(names[i], x + bw / 2, yy + bh * 0.42 + bob, size, CREAM if hot else NAVY, a)
        if not drawn:
            c.circle(x + bw / 2, yy + bh * 0.42 + bob, size * 0.35, fill=(CREAM if hot else NAVY) + (int(255 * a),))
        f, lines = fit(labels[i], "bold", int(bw - 30), [40, 34, 30, 26], 2)
        ty = yy + bh * 0.80 - (len(lines) - 1) * f.size * 0.6
        for ln in lines:
            c.text((x + bw / 2, ty), ln, "bold", f.size, (CREAM if hot else NAVY) + (int(255 * a),), anchor="mm")
            ty += f.size * 1.2
        if n <= 3 and i < n - 1:
            b = stage(p, 0.12 + 0.14 * i, 0.12)
            if b > 0:
                ax, ay = x + bw + 6, y + bh / 2
                c.line([(ax, ay), (ax + 28 * b, ay)], NAVY, 6)
                if b >= 1:
                    c.d.polygon([((ax + 24) * S, (ay - 12) * S), ((ax + 24) * S, (ay + 12) * S),
                                 ((ax + 36) * S, ay * S)], fill=NAVY)


def v_network(c: Canvas, sc, p, ctx):
    rnd = random.Random(ctx["seed"])
    centers = [(230, 230), (690, 210), (470, 520)]
    nodes = []
    for ci, (x, y) in enumerate(centers):
        for _ in range(9):
            ang, rad = rnd.uniform(0, 2 * math.pi), rnd.uniform(30, 150)
            nodes.append((x + rad * math.cos(ang), y + rad * 0.8 * math.sin(ang), ci))
    edges = []
    for i, (x, y, ci) in enumerate(nodes):
        near = sorted(range(len(nodes)), key=lambda j: (nodes[j][0] - x) ** 2 + (nodes[j][1] - y) ** 2)
        for j in near[1:3]:
            if (j, i) not in edges:
                edges.append((i, j))
    for _ in range(4):
        i, j = rnd.randrange(len(nodes)), rnd.randrange(len(nodes))
        if nodes[i][2] != nodes[j][2]:
            edges.append((i, j))
    # spread: BFS order from node 0
    adj = {i: [] for i in range(len(nodes))}
    for i, j in edges:
        adj[i].append(j)
        adj[j].append(i)
    order, seen, queue = {}, {0}, [0]
    while queue:
        n = queue.pop(0)
        order[n] = len(order)
        for m in adj[n]:
            if m not in seen:
                seen.add(m)
                queue.append(m)
    depth_max = max(order.values()) or 1
    spread = stage(p, 0.45, 0.45)
    for k, (i, j) in enumerate(edges):
        a = stage(p, 0.05 + 0.25 * k / len(edges), 0.12)
        if a <= 0:
            continue
        x0, y0, _ = nodes[i]
        x1, y1, _ = nodes[j]
        hot = order.get(i, 99) / depth_max < spread and order.get(j, 99) / depth_max < spread
        c.line([(x0, y0), (x0 + (x1 - x0) * a, y0 + (y1 - y0) * a)], CORAL if hot else NAVY_40, 5 if hot else 4)
    for i, (x, y, _) in enumerate(nodes):
        a = stage(p, 0.01 * i, 0.12)
        if a <= 0:
            continue
        hot = order.get(i, 99) / depth_max < spread
        r = (17 if hot else 14) * a
        c.circle(x, y, r + 5, fill=CREAM)
        c.circle(x, y, r, fill=CORAL if hot else NAVY)
    chips(c, sc.labels, 690, p)


def v_pipeline(c: Canvas, sc, p, ctx):
    steps = sc.labels or [sc.heading]
    n = len(steps)
    box_h = min(150, (720 - 40 * (n - 1)) / n)
    top = (VH - (n * box_h + (n - 1) * 46)) / 2
    active = min(int(p * n * 1.05), n - 1)
    for i, label in enumerate(steps):
        a = stage(p, i / n * 0.8, 0.12)
        if a <= 0:
            continue
        y = top + i * (box_h + 46) + (1 - a) * 30
        hot = i == active
        fill = CORAL if hot else WHITE
        c.rrect((90, y, VW - 90, y + box_h), 30, fill=fill + (int(255 * a),), outline=NAVY, width=4)
        name = sc.icons[i] if i < len(sc.icons) else ""
        if not c.icon(name, 160, y + box_h / 2, min(84, box_h * 0.62), CREAM if hot else NAVY, a):
            c.circle(160, y + box_h / 2, 36, fill=NAVY if not hot else CREAM)
            c.text((160, y + box_h / 2), str(i + 1), "black", 38, CREAM if not hot else CORAL, anchor="mm")
        f, lines = fit(label, "bold", VW - 360, [48, 42, 36], 2)
        yy = y + box_h / 2 - (len(lines) - 1) * f.size * 0.62
        for ln in lines:
            c.text((230, yy), ln, "bold", f.size, CREAM if hot else NAVY, anchor="lm")
            yy += f.size * 1.25
        if i < n - 1:
            b = stage(p, (i + 0.7) / n * 0.8, 0.1)
            if b > 0:
                ax = VW / 2
                c.line([(ax, y + box_h + 6), (ax, y + box_h + 6 + 30 * b)], NAVY, 6)
                if b >= 1:
                    tip = y + box_h + 40
                    c.d.polygon([((ax - 14) * S, (tip - 12) * S), ((ax + 14) * S, (tip - 12) * S), (ax * S, (tip + 4) * S)], fill=NAVY)


def _fmt(v: float) -> str:
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


def v_bars(c: Canvas, sc, p, ctx):
    rnd = random.Random(ctx["seed"])
    labels = sc.labels
    real = bool(sc.values)
    vals = sc.values if real else [rnd.uniform(0.35, 1.0) for _ in (labels or range(6))]
    n = len(vals)
    vmax = max(abs(v) for v in vals) or 1
    hot = max(range(n), key=lambda i: abs(vals[i]))
    row = min(150, 700 / n)
    top = (VH - row * n) / 2 + 20
    for i, v in enumerate(vals):
        y = top + i * row
        a = stage(p, 0.1 + 0.08 * i, 0.4)
        col = CORAL if i == hot else NAVY
        if labels:
            lx = 80
            if i < len(sc.icons) and c.icon(sc.icons[i], 102, y - 20, 50, col, stage(p, 0.05 + 0.08 * i, 0.2)):
                lx = 140
            c.text((lx, y - 6), labels[i], "bold", 38, NAVY, anchor="ls")
        ln = 40 + (VW - 300) * abs(v) / vmax * a
        c.line([(90, y + 30), (90 + ln, y + 30)], col, 34)
        if real and a > 0.05:
            c.text((90 + ln + 34, y + 30), _fmt(v * a if a < 1 else v), "black", 40, col, anchor="lm")


def _series(sc, rnd, n=40):
    if len(sc.values) >= 3:
        return list(sc.values)
    v, out = 0.4, []
    for i in range(n):
        v += rnd.uniform(-0.05, 0.05) + (0.035 if i > n * 0.6 else 0)
        out.append(v)
    return out


def v_timeline(c: Canvas, sc, p, ctx):
    rnd = random.Random(ctx["seed"])
    ys = _series(sc, rnd)
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 1
    x0, x1, y0, y1 = 80, VW - 80, 620, 120
    pts = [(x0 + (x1 - x0) * i / (len(ys) - 1), y0 + (y1 - y0) * (v - lo) / span) for i, v in enumerate(ys)]
    c.line([(x0, y0 + 40), (x1, y0 + 40)], NAVY_40, 4)
    for gx in range(5):
        xx = x0 + (x1 - x0) * gx / 4
        c.line([(xx, y0 + 30), (xx, y0 + 50)], NAVY_40, 4)
    a = stage(p, 0.05, 0.7)
    k = max(2, int(len(pts) * a))
    shown = pts[:k]
    split = int(len(pts) * 0.6)
    c.line(shown[: min(k, split + 1)], NAVY, 10)
    if k > split:
        c.line(shown[split:], CORAL, 12)
    hx, hy = shown[-1]
    c.circle(hx, hy, 20, fill=CREAM)
    c.circle(hx, hy, 14, fill=CORAL if k > split else NAVY)
    if len(sc.labels) >= 2:
        c.text((x0, y0 + 90), sc.labels[0], "bold", 36, NAVY, anchor="la")
        c.text((x1, y0 + 90), sc.labels[-1], "bold", 36, CORAL, anchor="ra")
    elif sc.labels:
        chips(c, sc.labels, 720, p)


def v_scatter(c: Canvas, sc, p, ctx):
    rnd = random.Random(ctx["seed"])
    x0, x1, y0, y1 = 110, VW - 60, 640, 80
    c.line([(x0, y0), (x1, y0)], NAVY, 5)
    c.line([(x0, y0), (x0, y1)], NAVY, 5)
    slope = 0.75
    for i in range(70):
        u = rnd.random()
        v = clamp(0.1 + slope * u + rnd.gauss(0, 0.12), 0.02, 0.98)
        a = stage(p, 0.004 * i, 0.15)
        if a > 0:
            c.circle(x0 + 20 + (x1 - x0 - 40) * u, y0 - 20 - (y0 - y1 - 40) * v, 11 * a, fill=NAVY_40[:3] + (190,))
    b = stage(p, 0.45, 0.35)
    if b > 0:
        sx, sy = x0 + 20, y0 - 20 - (y0 - y1 - 40) * 0.1
        ex = sx + (x1 - x0 - 40) * b
        ey = sy - (y0 - y1 - 40) * slope * b
        c.line([(sx, sy), (ex, ey)], CORAL, 12)
    if sc.labels:
        c.text(((x0 + x1) / 2, y0 + 60), sc.labels[0], "bold", 36, NAVY, anchor="mm")
    if len(sc.labels) > 1:
        c.text((x0 + 20, y1 - 30), "↑ " + sc.labels[1], "bold", 36, NAVY, anchor="ls")


def v_contrast(c: Canvas, sc, p, ctx):
    labels = (sc.labels + ["A", "B"])[:2]
    real = len(sc.values) >= 2
    for side in (0, 1):
        a = stage(p, 0.05 + 0.15 * side, 0.25)
        if a <= 0:
            continue
        x = 50 + side * (VW / 2 + 5)
        w = VW / 2 - 75
        col = CORAL if side else NAVY
        y = 40 + (1 - a) * 60
        c.rrect((x, y, x + w, y + 560), 34, fill=col + (int(255 * a),))
        f, lines = fit(labels[side], "bold", int(w - 50), [44, 38, 32], 2)
        c.text_block(x + w / 2, y + 50, lines, "bold", f.size, CREAM, anchor="ma")
        if real:
            v = sc.values[side] * stage(p, 0.3, 0.35)
            f2, _ = fit(_fmt(sc.values[side]), "black", int(w - 40), [110, 90, 72, 60], 1)
            c.text((x + w / 2, y + 330), _fmt(v), "black", f2.size, CREAM, anchor="mm")
        elif side < len(sc.icons) and c.icon(sc.icons[side], x + w / 2, y + 330, 200 * back(a), CREAM, a):
            pass
        else:
            rnd = random.Random(ctx["seed"] + side)
            dens = 0.35 if side == 0 else 0.8
            for i in range(24):
                if rnd.random() < dens:
                    c.circle(x + 60 + (i % 4) * (w - 120) / 3, y + 200 + (i // 4) * 55, 16 * a, fill=CREAM)
    if sc.big_text:
        b = stage(p, 0.5, 0.2)
        f, lines = fit(sc.big_text, "black", VW - 100, [72, 60, 50], 2)
        c.text_block(VW / 2, 650 + (1 - b) * 20, lines, "black", f.size, NAVY + (int(255 * b),), anchor="ma")


def _bezier(pts, k):
    """Point at fraction k along a polyline (by length)."""
    segs = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
    d = k * sum(segs)
    for (a, b), L in zip(zip(pts, pts[1:]), segs):
        if d <= L or L == 0:
            f = d / L if L else 0
            return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        d -= L
    return pts[-1]


def v_journey(c: Canvas, sc, p, ctx):
    """Something travels from stop to stop (cattle to buyers, a post to its readers); each stop lights up."""
    labels = sc.labels or [sc.heading]
    n = len(labels)
    names = (sc.icons + [""] * n)[:n]
    xs = [140, VW - 140] if n == 2 else [140, VW / 2, VW - 140, VW / 2][:n]
    ys = [150, 560] if n == 2 else [140, 330, 520, 700][:n]
    if n >= 3:  # zig-zag down the screen
        xs = [140 if i % 2 == 0 else VW - 140 for i in range(n)]
        ys = [110 + i * (560 / (n - 1)) for i in range(n)]
    stops = list(zip(xs, ys))
    # a smooth path through the stops
    path = []
    for (x0, y0), (x1, y1) in zip(stops, stops[1:]):
        for j in range(24):
            k = j / 24
            path.append((x0 + (x1 - x0) * ease(k), y0 + (y1 - y0) * k))
    path.append(stops[-1])
    draw_k = stage(p, 0.1, 0.55)
    shown = path[: max(2, int(len(path) * draw_k))]
    for a, b in zip(shown[::2], shown[1::2]):  # dashed trail
        c.line([a, b], NAVY_40, 8)
    t = ctx["t"]
    for i, (x, y) in enumerate(stops):
        a = stage(p, 0.02 + 0.08 * i, 0.15)
        if a <= 0:
            continue
        reached = draw_k >= (i / (n - 1) if n > 1 else 0) - 1e-6 and p > 0.1
        hot = reached and i == n - 1 and n > 1
        r = 92 * back((p - 0.02 - 0.08 * i) / 0.15)
        if reached and i > 0:
            c.circle(x, y, r + 14 + 6 * math.sin(t * 4), fill=CORAL_30)
        c.circle(x, y, r, fill=(CORAL if hot else WHITE) + (int(255 * a),), outline=NAVY, width=4)
        if not c.icon(names[i], x, y, r * 1.05, CREAM if hot else NAVY, a):
            c.circle(x, y, r * 0.3, fill=(CREAM if hot else NAVY) + (int(255 * a),))
        f, lines = fit(labels[i], "bold", 300, [36, 32, 28], 2)
        lx = x + (130 if x < VW / 2 else -130)
        c.text_block(lx, y - f.size * 0.6 * len(lines), lines, "bold", f.size, NAVY + (int(255 * a),),
                     anchor="la" if x < VW / 2 else "ra")
    if 0.1 < p and draw_k < 1:  # the traveller
        x, y = shown[-1]
        c.circle(x, y, 22, fill=CORAL)
        c.circle(x, y, 34, outline=CORAL, width=4)


def v_spotlight(c: Canvas, sc, p, ctx):
    """One key thing, big and centered, with the related things orbiting it."""
    names = sc.icons or [""]
    t = ctx["t"]
    cx, cy = VW / 2, 330
    a = stage(p, 0.0, 0.2)
    for k in range(3):  # ripples
        ph = (t * 0.5 + k / 3) % 1
        c.circle(cx, cy, 170 + 190 * ph, outline=NAVY + (int(90 * (1 - ph) * a),), width=4)
    r = 170 * back(p / 0.25)
    c.circle(cx, cy, r, fill=CORAL + (int(255 * a),))
    if not c.icon(names[0], cx, cy, r * 1.1, CREAM, a):
        fingerprint(c, cx, cy, r / 160, p, coral_ring=-1)
    orbit = names[1:4]
    for i, name in enumerate(orbit):
        b = stage(p, 0.25 + 0.1 * i, 0.15)
        if b <= 0:
            continue
        ang = t * 0.6 + i * 2 * math.pi / len(orbit)
        ox, oy = cx + math.cos(ang) * 300, cy + math.sin(ang) * 230
        c.circle(ox, oy, 62 * b, fill=WHITE, outline=NAVY, width=4)
        c.icon(name, ox, oy, 70 * b, NAVY, b)
    text = sc.big_text or (sc.labels[0] if sc.labels else "")
    if text:
        b = stage(p, 0.35, 0.2)
        f, lines = fit(text, "black", VW - 100, [72, 60, 50], 2)
        c.text_block(VW / 2, 640 + (1 - b) * 20, lines, "black", f.size, NAVY + (int(255 * b),), anchor="ma")


def v_funnel(c: Canvas, sc, p, ctx):
    """Lots of raw data go in, the computer filters, a few that matter come out (coral)."""
    rnd = random.Random(ctx["seed"])
    name = sc.icons[0] if sc.icons else ""
    top, neck, bottom = 170, 470, 560
    a = stage(p, 0.0, 0.15)
    c.d.polygon([(110 * S, top * S), ((VW - 110) * S, top * S), ((VW / 2 + 60) * S, neck * S),
                 ((VW / 2 + 60) * S, bottom * S), ((VW / 2 - 60) * S, bottom * S),
                 ((VW / 2 - 60) * S, neck * S)], fill=WHITE + (int(255 * a),), outline=NAVY + (int(255 * a),), width=4 * S)
    for i in range(36):
        start = 0.05 + rnd.random() * 0.55
        k = (p - start) / 0.3
        if k <= 0:
            continue
        x0 = 140 + rnd.random() * (VW - 280)
        keep = rnd.random() < 0.18
        if k < 1:  # falling in, squeezing toward the neck
            yy = 110 + (neck - 20 - 110) * k
            xx = x0 + (VW / 2 - x0) * clamp((yy - top) / (neck - top))
            col = NAVY
        elif keep:  # out the bottom, coral
            k2 = clamp(k - 1)
            xx, yy = VW / 2 + (rnd.random() - 0.5) * 300 * k2, bottom + 40 + 120 * ease(k2)
            col = CORAL
        else:
            continue
        if not c.icon(name, xx, yy, 56, col):
            c.circle(xx, yy, 14, fill=col)
    if sc.labels:
        chips(c, sc.labels[:1], 40, p, start=0.0)
        if len(sc.labels) > 1:
            chips(c, sc.labels[-1:], 730, p, start=0.6, accent=0)


def v_takeaway(c: Canvas, sc, p, ctx):
    text = sc.big_text or sc.lines[0]
    f, lines = fit(text, "black", VW - 100, [96, 84, 72, 60], 3)
    a = stage(p, 0.0, 0.25)
    y = 380 - (len(lines) - 1) * f.size * 0.6
    for ln in lines:
        c.text((VW / 2, y + (1 - a) * 30), ln, "black", f.size, NAVY + (int(255 * a),), anchor="mm")
        y += f.size * 1.2
    b = stage(p, 0.2, 0.3)
    w = min(f.getlength(lines[-1]), VW - 100) * b
    c.line([(VW / 2 - w / 2, y - f.size * 0.45), (VW / 2 + w / 2, y - f.size * 0.45)], CORAL, 14)
    # the follow prompt lives on the fixed outro card (brand.py)


def _tag(c: Canvas, x, y, text, hot, a, icon="", size=32, max_w=360, anchor="m"):
    """A single label chip at (x, y), optionally with an icon; anchor 'l' puts its left edge at x."""
    if a <= 0 or not text:
        return
    f, lines = fit(text, "bold", max_w, [size, size - 4, size - 8], 1)
    ic = 44 if icon else 0
    w = f.getlength(lines[0]) + 44 + ic
    x0 = x - w / 2 if anchor == "m" else x
    fg = CREAM + (int(255 * a),)
    c.rrect((x0, y - 30, x0 + w, y + 30), 30, fill=(CORAL if hot else NAVY) + (int(255 * a),))
    if icon and not c.icon(icon, x0 + 22 + ic / 2 - 2, y, 36, CREAM, a):
        x0 -= ic / 2  # no icon after all: re-center the text
    c.text((x0 + 22 + ic, y), lines[0], "bold", f.size, fg, anchor="lm")


def _share(sc, default: float) -> tuple[float, bool]:
    """The scene's one value as a 0..1 share (37 or 0.37 both mean 37%), and whether it is real."""
    if sc.values:
        v = abs(sc.values[0])
        return clamp(v / 100 if v > 1 else v), True
    return default, False


def _caption(c: Canvas, sc, y, p, start):
    if sc.labels:
        b = stage(p, start, 0.2)
        f, lines = fit(sc.labels[0], "bold", VW - 120, [44, 38, 32], 1)
        c.text((VW / 2, y + (1 - b) * 16), lines[0], "bold", f.size, NAVY + (int(255 * b),), anchor="mm")


def v_waffle(c: Canvas, sc, p, ctx):
    """A share of a group: 100 people (or things), and the share that did it fills in coral."""
    share, real = _share(sc, 0.3)
    name = sc.icons[0] if sc.icons else ""
    if name in ("user", "users") or (name and iconset.image(name, 32, NAVY) is None):
        name = ""  # people read better as the filled figures
    n_hot = round(share * 100)
    cell = 52
    x0, y0 = (VW - cell * 10) / 2 + cell / 2, 40 + cell / 2
    fill = stage(p, 0.3, 0.4)
    for i in range(100):
        r, col = divmod(i, 10)
        cx, cy = x0 + col * cell, y0 + r * cell
        a = stage(p, 0.0025 * i, 0.1)
        if a <= 0:
            continue
        hot = 99 - i < n_hot * fill  # fills from the bottom row up
        if name:
            c.icon(name, cx, cy, 48 * (0.7 + 0.3 * back(a)), CORAL if hot else NAVY, a * (1 if hot else 0.4))
        else:
            person(c, cx, cy + 6, 21 * (0.6 + 0.4 * a), (CORAL if hot else NAVY) + (int(255 * a * (1 if hot else 0.3)),))
    b = stage(p, 0.3, 0.1)
    if real and b > 0:
        c.text((VW / 2, 640), f"{round(share * 100 * fill)}%", "black", 110, CORAL + (int(255 * b),), anchor="mm")
    elif sc.big_text and b > 0:
        f, lines = fit(sc.big_text, "black", VW - 100, [80, 68, 56], 1)
        c.text((VW / 2, 640), lines[0], "black", f.size, CORAL + (int(255 * b),), anchor="mm")
    _caption(c, sc, 745, p, 0.45)


def v_gauge(c: Canvas, sc, p, ctx):
    """One score on a dial (accuracy, agreement, a share): the needle swings up to it."""
    share, real = _share(sc, 0.75)
    cx, cy, r = VW / 2, 470, 300
    a = stage(p, 0.0, 0.2)
    c.arc(cx, cy, r, 180, 360, (226, 216, 199, int(255 * a)), 46)
    for k in range(5):  # ticks at 0, 25, 50, 75, 100
        ang = math.radians(180 + 45 * k)
        c.line([(cx + math.cos(ang) * (r + 34), cy + math.sin(ang) * (r + 34)),
                (cx + math.cos(ang) * (r + 54), cy + math.sin(ang) * (r + 54))], NAVY + (int(255 * a),), 6)
    k = stage(p, 0.15, 0.5)
    v = clamp(share * back((p - 0.15) / 0.5)) if p > 0.15 else 0
    if v > 0.005:
        c.arc(cx, cy, r, 180, 180 + 180 * v, CORAL, 46)
    ang = math.radians(180 + 180 * v)
    c.line([(cx, cy), (cx + math.cos(ang) * (r - 60), cy + math.sin(ang) * (r - 60))], NAVY + (int(255 * a),), 14)
    c.circle(cx, cy, 30 * a, fill=NAVY)
    c.circle(cx, cy, 12 * a, fill=CORAL)
    if real and k > 0:
        c.text((cx, cy + 105), f"{round(share * 100 * k)}%", "black", 110, CORAL, anchor="mm")
    elif sc.big_text:
        b = stage(p, 0.4, 0.2)
        f, lines = fit(sc.big_text, "black", VW - 100, [80, 68, 56], 1)
        c.text((cx, cy + 105), lines[0], "black", f.size, CORAL + (int(255 * b),), anchor="mm")
    _caption(c, sc, cy + 225, p, 0.35)


def v_counter(c: Canvas, sc, p, ctx):
    """One big number counting up (a sample size, a count of posts), with copies of the thing filling in behind."""
    rnd = random.Random(ctx["seed"])
    name = sc.icons[0] if sc.icons else ""
    cols, rows, cell = 8, 7, 108
    x0, y0 = (VW - cols * cell) / 2 + cell / 2, 50 + cell / 2
    order = list(range(cols * rows))
    rnd.shuffle(order)
    for rank, i in enumerate(order):
        a = stage(p, 0.02 + 0.6 * rank / len(order), 0.08)
        if a <= 0:
            continue
        cx, cy = x0 + (i % cols) * cell, y0 + (i // cols) * cell
        if not c.icon(name, cx, cy, 64 * back(a), NAVY, 0.22 * a):
            c.circle(cx, cy, 12 * back(a), fill=NAVY + (int(50 * a),))
    k = stage(p, 0.05, 0.55)
    a = stage(p, 0.0, 0.15)
    if sc.values:
        v = sc.values[0]
        shown = v if k >= 1 else v * k
        text = f"{shown:,.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{shown:.1f}"
        final = f"{v:,.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{v:.1f}"
    else:
        text = final = sc.big_text or (sc.labels[0] if sc.labels else "")
    if not final:
        return
    f = next((font("black", s) for s in (190, 160, 130, 110, 96, 84, 72)
              if font("black", s).getlength(final) <= VW - 200), font("black", 64))
    w = min(f.getlength(final) + 100, VW - 40)
    pop = back((p - 0.0) / 0.2) if not sc.values else 1
    c.rrect((VW / 2 - w / 2 + 8, 268, VW / 2 + w / 2 + 8, 488), 40, fill=NAVY_20)
    c.rrect((VW / 2 - w / 2, 256, VW / 2 + w / 2, 476), 40, fill=WHITE + (int(255 * a),), outline=NAVY, width=5)
    c.text((VW / 2, 366), text, "black", int(f.size * pop), CORAL + (int(255 * a),), anchor="mm")
    if sc.values:
        _caption(c, sc, 560, p, 0.25)


def v_clusters(c: Canvas, sc, p, ctx):
    """Scattered data points sort themselves into groups (clustering, classifying, types of users)."""
    rnd = random.Random(ctx["seed"])
    labels = sc.labels[:4] or ["", "", ""]
    n = max(2, len(labels))
    centers = {2: [(240, 380), (680, 380)], 3: [(230, 260), (690, 260), (460, 590)],
               4: [(240, 230), (680, 230), (240, 590), (680, 590)]}[n]
    tint = stage(p, 0.6, 0.15)
    for i in range(60):
        g = i % n
        sx, sy = rnd.uniform(60, VW - 60), rnd.uniform(60, VH - 60)
        ang, rad = rnd.uniform(0, 2 * math.pi), 100 * math.sqrt(rnd.random())
        tx, ty = centers[g][0] + math.cos(ang) * rad, centers[g][1] + math.sin(ang) * rad * 0.85
        a = stage(p, 0.003 * i, 0.1)
        if a <= 0:
            continue
        k = stage(p, 0.18 + 0.004 * i, 0.4)
        x, y = sx + (tx - sx) * k, sy + (ty - sy) * k - math.sin(math.pi * k) * 30
        col = mix(NAVY, CORAL, tint) if g == n - 1 else NAVY
        c.circle(x, y, 13 * a, fill=col + (int(255 * a),))
    b = stage(p, 0.6, 0.15)
    for g, (x, y) in enumerate(centers):
        if b <= 0:
            break
        hot = g == n - 1
        c.circle(x, y, 128 + (1 - b) * 40, outline=(CORAL if hot else NAVY_40[:3]) + (int(220 * b),), width=5)
        icon = sc.icons[g] if g < len(sc.icons) else ""
        _tag(c, x, y - 165 if y < 400 or n == 2 else y + 165, labels[g], hot, b, icon, max_w=340)


def v_heatmap(c: Canvas, sc, p, ctx):
    """When or where something happens: a grid (hours x days, places) warms up and the hot spot is circled."""
    rnd = random.Random(ctx["seed"])
    rows, cols, cell, gap = 7, 12, 62, 8
    peaks = [(rnd.uniform(1, cols - 1), rnd.uniform(0.5, rows - 0.5), rnd.uniform(1.4, 2.6)) for _ in range(3)]
    heat = [[sum(math.exp(-((j - px) ** 2 + (i - py) ** 2) / (2 * s * s)) for px, py, s in peaks)
             for j in range(cols)] for i in range(rows)]
    top = max(max(r) for r in heat) or 1
    x0 = (VW - cols * (cell + gap) + gap) / 2
    y0 = 70
    hi, hj = max(((i, j) for i in range(rows) for j in range(cols)), key=lambda ij: heat[ij[0]][ij[1]])
    for i in range(rows):
        for j in range(cols):
            a = stage(p, 0.02 * (i + j), 0.15)
            if a <= 0:
                continue
            v = heat[i][j] / top * a
            col = mix((236, 228, 214), NAVY, v / 0.8) if v < 0.8 else (NAVY if v < 0.9 else CORAL)
            x, y = x0 + j * (cell + gap), y0 + i * (cell + gap)
            c.rrect((x, y, x + cell, y + cell), 12, fill=col + (255,))
    b = stage(p, 0.6, 0.15)
    if b > 0:
        x, y = x0 + hj * (cell + gap) + cell / 2, y0 + hi * (cell + gap) + cell / 2
        rr = 60 + 6 * math.sin(ctx["t"] * 5) + (1 - b) * 60
        c.circle(x, y, rr, outline=CORAL + (int(255 * b),), width=8)
    chips(c, sc.labels, 640, p, start=0.5, accent=0 if len(sc.labels) == 1 else -1)


def v_experiment(c: Canvas, sc, p, ctx):
    """A randomized experiment: one pool of people is split at random into two groups, and one gets the change."""
    rnd = random.Random(ctx["seed"])
    labels = (sc.labels + ["A", "B"])[:2]
    sides = [0] * 8 + [1] * 8
    rnd.shuffle(sides)
    slot = [0, 0]
    tint = stage(p, 0.5, 0.12)
    for i, side in enumerate(sides):
        s = slot[side]
        slot[side] += 1
        sx, sy = VW / 2 + (i % 8 - 3.5) * 58, 80 + (i // 8) * 72
        tx, ty = VW / 4 + side * VW / 2 + (s % 4 - 1.5) * 64, 330 + (s // 4) * 78
        a = stage(p, 0.008 * i, 0.1)
        if a <= 0:
            continue
        k = stage(p, 0.15 + 0.012 * i, 0.22)
        x, y = sx + (tx - sx) * k, sy + (ty - sy) * k - math.sin(math.pi * k) * 50
        person(c, x, y, 26 * (0.6 + 0.4 * a), (mix(NAVY, CORAL, tint) if side else NAVY) + (int(255 * a),))
    c.icon("arrows-shuffle", VW / 2, 215, 64, CORAL, stage(p, 0.1, 0.1) * (1 - stage(p, 0.45, 0.1)))
    b = stage(p, 0.4, 0.12)
    for side in (0, 1):
        if b <= 0:
            break
        x = VW / 4 + side * VW / 2
        col = CORAL if side else NAVY
        c.rrect((x - 160, 255, x + 160, 440), 30, outline=col + (int(255 * b),), width=5)
        f, lines = fit(labels[side], "bold", 320, [40, 34, 28], 1)
        c.text((x, 490), lines[0], "bold", f.size, col + (int(255 * b),), anchor="mm")
        icon = sc.icons[side] if side < len(sc.icons) else ""
        if side and icon:
            d = stage(p, 0.5, 0.12)
            c.circle(x + 150, 255, 46 * back((p - 0.5) / 0.12), fill=CORAL + (int(255 * d),))
            c.icon(icon, x + 150, 255, 56 * d, CREAM, d)
    if len(sc.values) >= 2:  # the outcome, only when the paper gives it
        vmax = max(abs(v) for v in sc.values[:2]) or 1
        for side in (0, 1):
            k = stage(p, 0.6 + 0.08 * side, 0.3)
            if k <= 0:
                continue
            x = VW / 4 + side * VW / 2
            h = 150 * abs(sc.values[side]) / vmax * k
            col = CORAL if side else NAVY
            c.rrect((x - 55, 770 - h, x + 55, 770), 14, fill=col + (255,))
            c.text((x, 750 - h), _fmt(sc.values[side] * k if k < 1 else sc.values[side]), "black", 40, col, anchor="md")
    elif b > 0:
        c.text((VW / 2, 350), "vs", "black", 56, NAVY + (int(255 * b),), anchor="mm")


def v_feed(c: Canvas, sc, p, ctx):
    """Social media posts scroll past a scanner; the computer reads each one and tags some (text classification)."""
    rnd = random.Random(ctx["seed"])
    tags = sc.labels or []
    px0, px1, py0, py1 = VW / 2 - 300, VW / 2 + 60, 20, 800
    a = stage(p, 0.0, 0.15)
    c.rrect((px0 + 10, py0 + 14, px1 + 10, py1 + 14), 54, fill=NAVY_20)
    c.rrect((px0, py0, px1, py1), 54, fill=WHITE + (int(255 * a),), outline=NAVY, width=6)
    layer = Canvas()
    scan = 430
    off = 620 * p
    hits = []
    for i in range(10):
        y = 70 + i * 176 - off
        if y > py1 or y + 156 < py0:
            continue
        tagged = rnd.random() < 0.55 and tags
        tag = rnd.randrange(len(tags)) if tags else 0
        img = rnd.random() < 0.4
        widths = [rnd.uniform(0.5, 1.0) for _ in range(3)]
        seen = y + 78 < scan  # the post's middle has passed the scanner
        hot = tagged and seen
        col = CORAL if hot else NAVY
        layer.rrect((px0 + 26, y, px1 - 26, y + 156), 24, fill=(CORAL_30 if hot else (240, 233, 220, 255)))
        layer.circle(px0 + 70, y + 44, 24, fill=col + (255,))
        layer.rrect((px0 + 106, y + 32, px0 + 220, y + 54), 11, fill=col + (200,))
        for k, wd in enumerate(widths[: 2 if img else 3]):
            layer.rrect((px0 + 50, y + 84 + k * 30, px0 + 50 + (px1 - px0 - 120) * wd, y + 100 + k * 30), 8,
                        fill=NAVY_40)
        if img:
            layer.rrect((px1 - 150, y + 76, px1 - 50, y + 140), 12, fill=NAVY_40)
        if hot:
            hits.append((y + 78, tag, scan - (y + 78)))
    mask = Image.new("L", c.img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([(px0 + 6) * S, (py0 + 6) * S, (px1 - 6) * S, (py1 - 6) * S],
                                           radius=48 * S, fill=255)
    layer.img.putalpha(Image.composite(layer.img.getchannel("A"), Image.new("L", mask.size, 0), mask))
    c.img.alpha_composite(layer.img)
    # the scanner line, a soft band with a bright core
    c.rrect((px0 + 6, scan - 14, px1 - 6, scan + 14), 6, fill=CORAL_30)
    c.line([(px0 + 6, scan), (px1 - 6, scan)], CORAL, 5)
    c.icon("scan", px1 + 50, scan, 56, CORAL)
    for y, tag, since in hits:
        if py0 + 40 < y < py1 - 40:
            k = clamp(since / 60)
            _tag(c, px1 + 90 - (1 - k) * 30, y, tags[tag], tag == len(tags) - 1, k,
                 sc.icons[tag] if tag < len(sc.icons) else "", size=30, max_w=VW - px1 - 150, anchor="l")


def v_magnify(c: Canvas, sc, p, ctx):
    """A lens sweeps over lots of text (posts, records, transcripts) and picks out what the study looked for."""
    rnd = random.Random(ctx["seed"])
    a = stage(p, 0.0, 0.15)
    c.rrect((58, 44, VW - 42, 624), 30, fill=NAVY_20)
    c.rrect((50, 30, VW - 50, 610), 30, fill=WHITE + (int(255 * a),), outline=NAVY, width=4)
    xl, xr, bands = 120, VW - 120, 4
    u = clamp((p - 0.08) / 0.72)

    def lens_at(u):
        b = min(int(u * bands), bands - 1)
        f = u * bands - b
        x = xl + (xr - xl) * (f if b % 2 == 0 else 1 - f)
        y = 112 + b * 126 + (126 * ease((f - 0.88) / 0.12) if b < bands - 1 else 0)
        return x, y

    lx, ly = lens_at(u)
    k = stage(p, 0.04, 0.1)
    if k > 0:
        c.circle(lx, ly, 92 * k, fill=CORAL_30[:3] + (40,))
    found = 0
    for row in range(12):
        y = 70 + row * 42
        x = 90
        while x < VW - 140:
            w = rnd.uniform(40, 130)
            target = rnd.random() < 0.06
            b = row // 3
            frac = clamp((x + w / 2 - xl) / (xr - xl))
            when = (b + (frac if b % 2 == 0 else 1 - frac)) / bands
            hit = target and u >= when and p > 0.08
            found += hit
            near = math.dist((x + w / 2, y), (lx, ly)) < 95
            fill = CORAL if hit else (NAVY if near else NAVY_40[:3])
            c.rrect((x, y - 10, x + w, y + 10), 10, fill=fill + (int((255 if hit or near else 140) * a),))
            x += w + 16
    if k > 0:  # the lens
        c.circle(lx, ly, 92 * k, outline=NAVY, width=10)
        c.line([(lx + 66 * k, ly + 66 * k), (lx + 130 * k, ly + 130 * k)], NAVY, 22)
    if sc.labels:
        _tag(c, VW / 2, 700, f"{sc.labels[0]}  ×{found}" if found else sc.labels[0], True, stage(p, 0.1, 0.15),
             sc.icons[0] if sc.icons else "", size=40, max_w=VW - 160)


def v_survey(c: Canvas, sc, p, ctx):
    """A survey question and a 1-5 answer scale; answers drop in and pile up into a histogram."""
    rnd = random.Random(ctx["seed"])
    question = sc.big_text or sc.heading
    a = stage(p, 0.0, 0.2)
    y0 = 30 + (1 - a) * 40
    c.rrect((68, y0 + 12, VW - 52, y0 + 222), 34, fill=NAVY_20)
    c.rrect((60, y0, VW - 60, y0 + 210), 34, fill=WHITE + (int(255 * a),), outline=NAVY, width=4)
    c.d.polygon([(150 * S, (y0 + 208) * S), (210 * S, (y0 + 208) * S), (150 * S, (y0 + 258) * S)],
                fill=WHITE + (int(255 * a),), outline=NAVY)
    c.icon("message-question", 130, y0 + 105, 72, CORAL, a)
    f, lines = fit(question, "bold", VW - 300, [50, 44, 38, 34], 3)
    ty = y0 + 105 - (len(lines) - 1) * f.size * 0.62
    for ln in lines:
        c.text((190, ty), ln, "bold", f.size, NAVY + (int(255 * a),), anchor="lm")
        ty += f.size * 1.25
    weights = [rnd.uniform(0.3, 1) for _ in range(5)]
    weights[rnd.randrange(5)] += 1.2
    counts = [round(9 * w / max(weights)) for w in weights]
    best = counts.index(max(counts))
    base, xs = 640, [160 + j * 150 for j in range(5)]
    b = stage(p, 0.15, 0.15)
    c.line([(100, base + 4), (VW - 100, base + 4)], NAVY + (int(255 * b),), 5)
    drops = [(j, lvl) for j in range(5) for lvl in range(counts[j])]
    rnd.shuffle(drops)
    for k, (j, lvl) in enumerate(drops):
        q = stage(p, 0.2 + 0.45 * k / len(drops), 0.12)
        if q <= 0:
            continue
        y = 300 + (base - 22 - lvl * 36 - 300) * q
        hot = j == best and p > 0.7
        c.circle(xs[j], y, 15, fill=(CORAL if hot else NAVY) + (int(255 * min(1, q * 2)),))
    for j, x in enumerate(xs):
        c.text((x, base + 44), str(j + 1), "black", 40, (CORAL if j == best and p > 0.7 else NAVY) + (int(255 * b),),
               anchor="mm")
    if len(sc.labels) >= 2:
        c.text((xs[0] - 40, base + 110), sc.labels[0], "bold", 34, NAVY + (int(255 * b),), anchor="lm")
        c.text((xs[-1] + 40, base + 110), sc.labels[-1], "bold", 34, NAVY + (int(255 * b),), anchor="rm")



def v_race(c: Canvas, sc, p, ctx):
    """Two to four groups race to the finish line; the fastest (or largest value) wins and gets the trophy."""
    rnd = random.Random(ctx["seed"])
    labels = sc.labels[:4] or ["", "", ""]
    n = max(2, len(labels))
    real = len(sc.values) == len(labels) and len(labels) >= 2
    vals = [abs(v) for v in sc.values] if real else [rnd.uniform(0.55, 0.85) for _ in range(n)]
    win = max(range(n), key=lambda i: vals[i])
    if not real:
        vals[win] = 1.0
    vmax = max(vals) or 1
    x0, x1 = 110, VW - 160
    lane = min(240, 640 / n)
    top = (VH - lane * n) / 2 + 10
    a = stage(p, 0.0, 0.15)
    for k in range(14):  # checkered finish line
        for j in (0, 1):
            if (k + j) % 2 == 0:
                y = top - 10 + k * (lane * n + 20) / 14
                c.d.rectangle([(x1 + j * 14) * S, y * S, (x1 + 14 + j * 14) * S, (y + (lane * n + 20) / 14) * S],
                              fill=NAVY + (int(255 * a),))
    t = ctx["t"]
    for i in range(n):
        y = top + i * lane + lane / 2
        c.line([(x0, y + 34), (x1 - 10, y + 34)], NAVY_40[:3] + (int(120 * a),), 4)
        k = stage(p, 0.12, 0.6) * vals[i] / vmax
        x = x0 + (x1 - x0 - 50) * k
        running = 0 < k < vals[i] / vmax - 0.01
        hop = abs(math.sin(t * 11 + i)) * 14 if running else 0
        hot = i == win and p > 0.72
        col = CORAL if i == win else NAVY
        for g in range(3):  # speed lines
            if running:
                c.line([(x - 70 - g * 26, y - 16 + g * 16), (x - 46 - g * 26, y - 16 + g * 16)], col + (120,), 5)
        icon = sc.icons[i] if i < len(sc.icons) else ""
        if not c.icon(icon, x, y - hop, 96, col, a):
            person(c, x, y - hop + 6, 34, col + (int(255 * a),))
        if labels[i]:
            f, lines = fit(labels[i], "bold", 360, [34, 30, 26], 1)
            c.text((x0 - 20, y - 100), lines[0], "bold", f.size, NAVY + (int(255 * a),), anchor="lt")
        if real and k > 0.02:
            c.text((x + 56, y), _fmt(sc.values[i] * min(1, k * vmax / vals[i])), "black", 36, col, anchor="lm")
        if hot:
            b = stage(p, 0.72, 0.12)
            c.circle(x1 + 70, y, 42 * back((p - 0.72) / 0.12), fill=CORAL)
            c.icon("trophy", x1 + 70, y, 50 * b, CREAM, b)


def v_cascade(c: Canvas, sc, p, ctx):
    """One post spreads: it branches out level by level to more and more people (a share or retweet cascade)."""
    rnd = random.Random(ctx["seed"])
    levels = [[(None, 0)]]
    for d in range(1, 5):
        kids = []
        for pi_, _ in enumerate(levels[-1]):
            for _ in range(rnd.choice((1, 2, 2, 3)) if len(levels[-1]) < 12 else rnd.choice((0, 1, 2))):
                kids.append((pi_, d))
        if len(kids) > 14:  # thin out evenly so the tree stays balanced
            kids = [kids[int(i * len(kids) / 14)] for i in range(14)]
        levels.append(kids)
    pos = []
    for d, lvl in enumerate(levels):
        n = len(lvl)
        pos.append([(VW / 2 + (j - (n - 1) / 2) * min(110, (VW - 80) / max(n, 1)), 80 + d * 140) for j in range(n)])
    grow = stage(p, 0.05, 0.65) * (len(levels) - 1)
    count = 0
    for d in range(1, len(levels)):
        k = clamp(grow - (d - 1))
        if k <= 0:
            break
        for j, (pi_, _) in enumerate(levels[d]):
            (xa, ya), (xb, yb) = pos[d - 1][pi_], pos[d][j]
            hot = d == len(levels) - 1 or (d >= 3)
            c.line([(xa, ya), (xa + (xb - xa) * ease(k), ya + (yb - ya) * ease(k))], CORAL if hot else NAVY_40, 5)
    for d, lvl in enumerate(levels):
        k = clamp(grow - (d - 1)) if d else stage(p, 0.0, 0.1)
        if k < 0.95 and d:
            continue
        for j, (x, y) in enumerate(pos[d]):
            r = (40 if d == 0 else 18) * back(k if d == 0 else clamp((grow - d + 1 - 0.95) * 8))
            if d == 0:
                c.circle(x, y, r + 8, fill=CREAM)
                c.circle(x, y, r, fill=CORAL)
                c.icon(sc.icons[0] if sc.icons else "share", x, y, r * 1.1, CREAM)
            else:
                count += 1
                c.circle(x, y, r + 5, fill=CREAM)
                c.circle(x, y, r, fill=CORAL if d >= 3 else NAVY)
    if sc.labels:
        _tag(c, VW / 2, 760, f"{sc.labels[0]}  ×{count}" if count else sc.labels[0], True, stage(p, 0.1, 0.15),
             size=38, max_w=VW - 160)


def v_balance(c: Canvas, sc, p, ctx):
    """Two things weighed against each other on a scale; it wobbles and tips toward the heavier one."""
    labels = (sc.labels + ["", ""])[:2]
    real = len(sc.values) >= 2
    left, right = (abs(sc.values[0]), abs(sc.values[1])) if real else (0.4, 1.0)
    target = 14 * clamp((right - left) / (max(left, right) or 1) * 1.5, -1, 1)
    q = clamp((p - 0.2) / 0.6)
    ang = math.radians(target * (1 - math.exp(-5 * q) * math.cos(12 * q)) if p > 0.2 else 0)
    cx, cy, L = VW / 2, 270, 310
    a = stage(p, 0.0, 0.15)
    c.d.polygon([(cx * S, cy * S), ((cx - 90) * S, 640 * S), ((cx + 90) * S, 640 * S)], fill=NAVY + (int(255 * a),))
    c.rrect((cx - 200, 640, cx + 200, 670), 15, fill=NAVY + (int(255 * a),))
    ends = [(cx - L * math.cos(ang), cy - L * math.sin(ang)), (cx + L * math.cos(ang), cy + L * math.sin(ang))]
    c.line(ends, NAVY + (int(255 * a),), 16)
    c.circle(cx, cy, 22, fill=CORAL)
    for side, (ex, ey) in enumerate(ends):
        b = stage(p, 0.08 + 0.08 * side, 0.15)
        col = CORAL if (right > left) == bool(side) else NAVY
        py = ey + 150
        c.line([(ex, ey), (ex - 90, py)], NAVY + (int(200 * a),), 4)
        c.line([(ex, ey), (ex + 90, py)], NAVY + (int(200 * a),), 4)
        c.d.chord([(ex - 120) * S, (py - 50) * S, (ex + 120) * S, (py + 50) * S], 0, 180, fill=col + (int(255 * a),))
        icon = sc.icons[side] if side < len(sc.icons) else ""
        if not c.icon(icon, ex, py - 46, 90 * back((p - 0.08 - 0.08 * side) / 0.15), col, b):
            c.circle(ex, py - 34, 34 * b, fill=col + (int(255 * b),))
        if labels[side]:
            f, lines = fit(labels[side], "bold", 300, [40, 34, 28], 1)
            c.text((ex, py + 90), lines[0], "bold", f.size, col + (int(255 * b),), anchor="mm")
        if real:
            c.text((ex, py + 140), _fmt(sc.values[side]), "black", 44, col + (int(255 * stage(p, 0.5, 0.2)),), anchor="mm")


def v_chat(c: Canvas, sc, p, ctx):
    """A conversation: messages pop in one by one, each after a typing indicator (chats, chatbots, replies)."""
    msgs = sc.labels[:4] or ["", "", ""]
    n = len(msgs)
    t = ctx["t"]
    step = min(170, 680 / n)
    for k, msg in enumerate(msgs):
        right = k % 2 == 1
        start = 0.05 + 0.75 * k / n
        y = 70 + k * step
        col = CORAL if right else WHITE
        fg = CREAM if right else NAVY
        ax = VW - 80 if right else 80
        icon = sc.icons[k] if k < len(sc.icons) else ("robot" if right else "user")
        a = stage(p, start - 0.08, 0.06)
        if a <= 0:
            continue
        c.circle(ax, y + 50, 40, fill=(CORAL if right else NAVY) + (int(255 * a),))
        if not c.icon(icon, ax, y + 50, 48, CREAM, a):
            c.circle(ax, y + 50, 14, fill=CREAM)
        b = stage(p, start, 0.1)
        if b <= 0:  # typing dots
            bx = ax + (-200 if right else 70)
            c.rrect((bx, y + 14, bx + 130, y + 86), 36, fill=col + (255,), outline=None if right else NAVY, width=4)
            for d in range(3):
                h = abs(math.sin(t * 8 - d * 0.8)) * 10
                c.circle(bx + 35 + d * 30, y + 50 - h, 9, fill=fg)
            continue
        text = msg or "…"
        f, lines = fit(text, "bold", 520, [40, 36, 32], 2)
        w = max(f.getlength(ln) for ln in lines) + 64
        h = len(lines) * f.size * 1.3 + 40
        bx = ax - 70 - w if right else ax + 70
        pop = back(b)
        cxm, cym = bx + w / 2, y + 14 + h / 2
        box = (cxm - w / 2 * pop, cym - h / 2 * pop, cxm + w / 2 * pop, cym + h / 2 * pop)
        if right:
            c.rrect(box, 34, fill=col + (255,))
        else:
            c.rrect((box[0] + 6, box[1] + 8, box[2] + 6, box[3] + 8), 34, fill=NAVY_20)
            c.rrect(box, 34, fill=col + (255,), outline=NAVY, width=4)
        if b > 0.6:
            c.text_block(bx + 32, y + 34, lines, "bold", f.size, fg, gap=1.3)


def v_geo(c: Canvas, sc, p, ctx):
    """Places on a map light up and get linked by arcs (location data, mobility, migration)."""
    rnd = random.Random(ctx["seed"])
    blobs = [(rnd.uniform(200, 720), rnd.uniform(180, 460), rnd.uniform(140, 260), rnd.uniform(90, 170)) for _ in range(4)]
    a = stage(p, 0.0, 0.3)
    land = []
    for y in range(50, 620, 26):
        for x in range(40, VW - 40, 26):
            if any(((x - bx) / rx) ** 2 + ((y - by) / ry) ** 2 < 1 for bx, by, rx, ry in blobs):
                land.append((x, y))
    for i, (x, y) in enumerate(land):
        if rnd.random() < a * 1.2:
            c.circle(x, y, 6, fill=NAVY_40[:3] + (110,))
    spots = rnd.sample(land, 6) if len(land) >= 6 else land
    t = ctx["t"]
    for i, (x, y) in enumerate(spots):
        b = stage(p, 0.15 + 0.05 * i, 0.12)
        if b <= 0:
            continue
        hot = i == len(spots) - 1
        ph = (t * 0.8 + i * 0.3) % 1
        c.circle(x, y, 18 + 50 * ph, outline=(CORAL if hot else NAVY) + (int(160 * (1 - ph) * b),), width=4)
        c.circle(x, y, 16 * back((p - 0.15 - 0.05 * i) / 0.12), fill=CORAL if hot else NAVY)
    for i in range(len(spots) - 1):
        (xa, ya), (xb, yb) = spots[i], spots[-1] if i % 2 == 0 else spots[i + 1]
        k = stage(p, 0.4 + 0.06 * i, 0.25)
        if k <= 0:
            continue
        mx, my = (xa + xb) / 2, min(ya, yb) - 90 - 0.2 * abs(xa - xb)
        pts = [((1 - u) ** 2 * xa + 2 * (1 - u) * u * mx + u * u * xb, (1 - u) ** 2 * ya + 2 * (1 - u) * u * my + u * u * yb)
               for u in [j / 30 * k for j in range(31)]]
        c.line(pts, CORAL if i % 2 == 0 else NAVY, 5)
        if k < 1:
            c.circle(*pts[-1], 12, fill=CORAL)
    chips(c, sc.labels, 690, p, start=0.5, accent=len(sc.labels) - 1 if len(sc.labels) > 1 else -1)


def v_ranking(c: Canvas, sc, p, ctx):
    """A ranked list reshuffles and one item climbs to the top (rankings, recommendations, search results)."""
    labels = sc.labels[:4] or ["", "", "", ""]
    n = max(3, len(labels)) if sc.labels else 4
    labels = (labels + [""] * n)[:n]
    order0 = list(range(n))
    final = [n - 1] + list(range(n - 1))  # the last item climbs to the top
    k = stage(p, 0.35, 0.35)
    row, top = min(150, 680 / n), 0
    top = (VH - row * n) / 2
    for i in range(n):
        a = stage(p, 0.05 * i, 0.15)
        if a <= 0:
            continue
        y = top + (order0.index(i) + (final.index(i) - order0.index(i)) * k) * row
        climb = i == n - 1
        dx = math.sin(math.pi * k) * 70 if climb else 0
        hot = climb and k > 0.5
        x0, x1 = 90 + dx, VW - 90 + dx
        c.rrect((x0 + 6, y + 18, x1 + 6, y + row - 6), 28, fill=NAVY_20)
        c.rrect((x0, y + 10, x1, y + row - 14), 28, fill=(CORAL if hot else WHITE) + (int(255 * a),), outline=NAVY, width=4)
        rank = round(order0.index(i) + (final.index(i) - order0.index(i)) * k) + 1
        c.text((x0 + 60, y + row / 2 - 2), f"#{rank}", "black", 46, (CREAM if hot else CORAL) + (int(255 * a),), anchor="mm")
        icon = sc.icons[i] if i < len(sc.icons) else ""
        lx = x0 + 130
        if c.icon(icon, lx + 30, y + row / 2 - 2, 62, CREAM if hot else NAVY, a):
            lx += 80
        if labels[i]:
            f, lines = fit(labels[i], "bold", int(x1 - lx - 100), [42, 36, 30], 1)
            c.text((lx, y + row / 2 - 2), lines[0], "bold", f.size, (CREAM if hot else NAVY) + (int(255 * a),), anchor="lm")
        else:
            c.rrect((lx, y + row / 2 - 14, lx + 160 + 60 * ((i * 37) % 5), y + row / 2 + 10), 12,
                    fill=(CREAM if hot else NAVY_40[:3]) + (int(200 * a),))
        if climb and 0 < k < 1:
            c.icon("arrow-big-up-lines", x1 - 50, y + row / 2 - 2, 60, CREAM if hot else CORAL)


def v_swipe(c: Canvas, sc, p, ctx):
    """Cards get swiped left or right, one after another (choices, dating apps, accept or reject decisions)."""
    rnd = random.Random(ctx["seed"])
    labels = (sc.labels + ["", ""])[:2]
    dirs = [rnd.choice((-1, 1)) for _ in range(5)]
    dirs[-1] = 1
    cw, ch = 400, 520
    cx, cy = VW / 2, 330
    count = [0, 0]
    swipes = 4  # the fifth card stays on the pile
    for k in range(swipes, -1, -1):  # back to front
        start = 0.1 + 0.18 * k
        q = clamp((p - start) / 0.14) if k < swipes else 0.0
        if q >= 1:
            count[dirs[k] > 0] += 1
            continue
        depth = max(0, k - sum(1 for j in range(k) if p >= 0.1 + 0.18 * j + 0.14))
        if depth > 2:
            continue
        card = Canvas.__new__(Canvas)
        card.img = Image.new("RGBA", ((cw + 40) * S, (ch + 40) * S), (0, 0, 0, 0))
        card.d = ImageDraw.Draw(card.img, "RGBA")
        card.rrect((20, 20, 20 + cw, 20 + ch), 36, fill=WHITE + (255,), outline=NAVY, width=5)
        crnd = random.Random(k * 13 + ctx["seed"])
        card.rrect((50, 50, cw - 10, 300), 26, fill=mix((226, 216, 199), NAVY, crnd.uniform(0.1, 0.35)) + (255,))
        card.circle(20 + cw / 2, 175, 70, fill=CREAM + (255,))
        for j, wd in enumerate((0.7, 0.5, 0.6)):
            card.rrect((60, 340 + j * 50, 60 + (cw - 80) * wd * crnd.uniform(0.7, 1), 364 + j * 50), 12, fill=NAVY_40)
        if q > 0:
            stamp = labels[dirs[k] > 0] or ("✓" if dirs[k] > 0 else "✕")
            col = CORAL if dirs[k] > 0 else NAVY
            card.rrect((cw / 2 - 130, 120, cw / 2 + 170, 220), 20, outline=col + (int(255 * min(1, q * 3)),), width=8)
            f, lines = fit(stamp, "black", 280, [52, 44, 36], 1)
            card.text((20 + cw / 2, 170), lines[0], "black", f.size, col + (int(255 * min(1, q * 3)),), anchor="mm")
        img = card.img
        rot = -dirs[k] * 22 * q
        if rot:
            img = img.rotate(rot, resample=Image.BICUBIC, expand=True)
        scale = 1 - 0.05 * depth
        if scale < 1:
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.BILINEAR)
        x = cx + dirs[k] * 700 * ease(q) ** 1.5
        y = cy + depth * 26 + 60 * q
        c.img.alpha_composite(img, (int(x * S - img.width / 2), int(y * S - img.height / 2)))
    for side in (0, 1):
        col = CORAL if side else NAVY
        x = 150 if side == 0 else VW - 150
        c.circle(x, 700, 52, fill=col)
        icon = sc.icons[side] if side < len(sc.icons) else ("heart" if side else "x")
        c.icon(icon, x, 700, 56, CREAM)
        c.text((x + (75 if side == 0 else -75), 700), f"{labels[side]} {count[side]}".strip(), "black", 40, col,
               anchor="lm" if side == 0 else "rm")


def v_clock(c: Canvas, sc, p, ctx):
    """A 24-hour clock: the hand sweeps round and activity bars grow at each hour; the busiest hour glows."""
    rnd = random.Random(ctx["seed"])
    peak = rnd.choice((21, 22, 23, 8, 12))
    vals = [0.15 + 0.85 * math.exp(-min(abs(h - peak), 24 - abs(h - peak)) ** 2 / 10) + rnd.uniform(0, 0.12) for h in range(24)]
    cx, cy, r = VW / 2, 360, 170
    a = stage(p, 0.0, 0.15)
    c.circle(cx, cy, r, fill=WHITE + (int(255 * a),), outline=NAVY, width=6)
    for h in range(24):
        ang = math.radians(-90 + h * 15)
        inner = r - (24 if h % 6 == 0 else 14)
        c.line([(cx + math.cos(ang) * inner, cy + math.sin(ang) * inner),
                (cx + math.cos(ang) * (r - 6), cy + math.sin(ang) * (r - 6))], NAVY + (int(255 * a),), 5 if h % 6 == 0 else 3)
    for h, lab in ((0, "0"), (6, "6"), (12, "12"), (18, "18")):
        ang = math.radians(-90 + h * 15)
        c.text((cx + math.cos(ang) * (r - 56), cy + math.sin(ang) * (r - 56)), lab, "bold", 30, NAVY + (int(255 * a),), anchor="mm")
    c.icon("sun", cx, cy + 70, 44, CORAL, a * 0.8)
    c.icon("moon", cx, cy - 70, 44, NAVY, a * 0.8)
    sweep = stage(p, 0.08, 0.6) * 24
    for h in range(24):
        k = clamp((sweep - h) * 1.5)
        if k <= 0:
            continue
        ang = math.radians(-90 + h * 15 + 7.5)
        hot = h == max(range(24), key=lambda i: vals[i])
        ln = 120 * vals[h] * back(k)
        c.line([(cx + math.cos(ang) * (r + 18), cy + math.sin(ang) * (r + 18)),
                (cx + math.cos(ang) * (r + 18 + ln), cy + math.sin(ang) * (r + 18 + ln))],
               CORAL if hot or vals[h] > 0.8 else NAVY, 16)
    hand = math.radians(-90 + sweep * 15)
    c.line([(cx, cy), (cx + math.cos(hand) * (r - 30), cy + math.sin(hand) * (r - 30))], CORAL + (int(255 * a),), 10)
    c.circle(cx, cy, 16 * a, fill=NAVY)
    chips(c, sc.labels, 720, p, start=0.6, accent=0 if len(sc.labels) == 1 else -1)


def v_echo(c: Canvas, sc, p, ctx):
    """An echo chamber: like-minded dots drift inside a bubble while outside views bounce off its wall."""
    rnd = random.Random(ctx["seed"])
    t = ctx["t"]
    cx, cy = VW / 2, 360
    a = stage(p, 0.0, 0.2)
    R = (230 + 6 * math.sin(t * 3)) * back(p / 0.25)
    c.circle(cx, cy, R, fill=(255, 252, 246, int(200 * a)), outline=NAVY + (int(255 * a),), width=6)
    if R > 40:
        c.arc(cx, cy, R - 26, 200, 250, (255, 255, 255, int(255 * a)), 10)  # a glint so it reads as a bubble
    for i in range(22):
        rr = rnd.uniform(20, 180)
        w = rnd.uniform(0.3, 0.8) * rnd.choice((-1, 1))
        ph = rnd.uniform(0, 2 * math.pi)
        b = stage(p, 0.05 + 0.01 * i, 0.1)
        if b > 0:
            c.circle(cx + math.cos(w * t + ph) * rr, cy + math.sin(w * t + ph) * rr * 0.9, 14 * b, fill=NAVY)
    out = stage(p, 0.3, 0.15)
    for i in range(10):
        ang = 2 * math.pi * i / 10 + rnd.uniform(-0.2, 0.2) + t * 0.05
        speed, ph = rnd.uniform(0.5, 0.8), rnd.uniform(0, 2)
        d = R + 26 + abs((t * speed + ph) % 2 - 1) * 200
        x, y = cx + math.cos(ang) * d, cy + math.sin(ang) * d * 0.85
        if -20 < x < VW + 20 and -20 < y < VH - 60 and out > 0:
            c.circle(x, y, 14 * out, fill=CORAL)
            near = clamp(1 - (d - R - 26) / 40)
            if near > 0:  # a little flash where it hits the wall
                c.circle(cx + math.cos(ang) * R, cy + math.sin(ang) * R * 0.85, 10 + 16 * near, fill=CORAL_30)
    if sc.labels:
        _tag(c, cx, cy + R - 50, sc.labels[0], False, stage(p, 0.3, 0.15), sc.icons[0] if sc.icons else "")
    if len(sc.labels) > 1:
        _tag(c, cx, 760, sc.labels[1], True, stage(p, 0.45, 0.15), sc.icons[1] if len(sc.icons) > 1 else "")


def _gear(c: Canvas, cx, cy, r, teeth, ang, col):
    pts = []
    for k in range(teeth * 4):
        th = ang + 2 * math.pi * k / (teeth * 4)
        rr = r if k % 4 in (0, 1) else r * 0.78
        pts.append(((cx + math.cos(th) * rr) * S, (cy + math.sin(th) * rr) * S))
    c.d.polygon(pts, fill=col)
    c.circle(cx, cy, r * 0.34, fill=WHITE)


def v_predict(c: Canvas, sc, p, ctx):
    """Inputs flow into a model (whirring gears) and a prediction comes out with a confidence bar."""
    t = ctx["t"]
    labels = sc.labels or []
    ins = labels[:-1] if len(labels) > 1 else labels
    out = labels[-1] if len(labels) > 1 else ""
    names = sc.icons[: len(ins)] if len(labels) > 1 else sc.icons[:1]
    n = max(1, min(3, len(ins)))
    a = stage(p, 0.0, 0.15)
    bx0, by0, bx1, by1 = 330, 240, 590, 500
    c.rrect((bx0 + 8, by0 + 12, bx1 + 8, by1 + 12), 36, fill=NAVY_20)
    c.rrect((bx0, by0, bx1, by1), 36, fill=NAVY + (int(255 * a),))
    spin = t * 2.2 * (0.3 + stage(p, 0.15, 0.3))
    _gear(c, 425, 340, 70, 9, spin, CREAM + (int(255 * a),))
    _gear(c, 515, 420, 50, 7, -spin * 1.3 + 0.2, CORAL + (int(255 * a),))
    for i in range(n):
        y = 370 + (i - (n - 1) / 2) * 190
        b = stage(p, 0.05 + 0.06 * i, 0.15)
        if b <= 0:
            continue
        c.circle(130, y, 70 * back((p - 0.05 - 0.06 * i) / 0.15), fill=WHITE + (int(255 * b),), outline=NAVY, width=4)
        if not c.icon(names[i] if i < len(names) else "", 130, y, 76, NAVY, b):
            c.circle(130, y, 22, fill=NAVY)
        if i < len(ins) and ins[i]:
            f, lines = fit(ins[i], "bold", 220, [30, 26, 22], 1)
            c.text((130, y + 98), lines[0], "bold", f.size, NAVY + (int(255 * b),), anchor="mm")
        for j in range(3):  # data packets flowing into the model
            u = (t * 0.9 + j / 3 + i * 0.2) % 1
            if p > 0.15:
                x = 205 + (bx0 - 215) * u
                yy = y + (370 - y) * u
                c.circle(x, yy, 9, fill=NAVY + (int(255 * (1 - abs(2 * u - 1) ** 3)),))
    k = stage(p, 0.45, 0.15)
    if k > 0:
        for j in range(2):
            u = (t * 0.9 + j / 2) % 1
            c.circle(bx1 + 10 + 50 * u, 370, 9, fill=CORAL)
        x0, y0 = 660, 290
        c.rrect((x0 + 6, y0 + 10, x0 + 230 + 6, y0 + 170), 28, fill=NAVY_20)
        c.rrect((x0, y0, x0 + 230, y0 + 160), 28, fill=CORAL + (int(255 * k),))
        text = out or (sc.big_text or "")
        if text:
            f, lines = fit(text, "black", 200, [40, 34, 28, 24], 2)
            c.text_block(x0 + 115, y0 + 30, lines, "black", f.size, CREAM + (int(255 * k),), anchor="ma")
        conf, real = _share(sc, 0.0)
        if real or not sc.values:
            fill = conf if real else 0.8
            q = stage(p, 0.55, 0.3)
            c.rrect((x0, y0 + 190, x0 + 230, y0 + 216), 13, fill=(226, 216, 199, 255))
            c.rrect((x0, y0 + 190, x0 + max(26, 230 * fill * q), y0 + 216), 13, fill=CORAL + (255,))
            if real:
                c.text((x0 + 115, y0 + 260), f"{round(fill * 100 * q)}%", "black", 44, CORAL, anchor="mm")
    if sc.big_text and out:
        b = stage(p, 0.6, 0.2)
        f, lines = fit(sc.big_text, "black", VW - 100, [60, 50, 42], 1)
        c.text((VW / 2, 720), lines[0], "black", f.size, NAVY + (int(255 * b),), anchor="mm")


DRAW = {"hook": v_hook, "paper": v_paper, "crowd": v_crowd, "network": v_network,
        "pipeline": v_pipeline, "bars": v_bars, "timeline": v_timeline, "scatter": v_scatter,
        "contrast": v_contrast, "icons": v_icons, "journey": v_journey, "spotlight": v_spotlight,
        "funnel": v_funnel, "takeaway": v_takeaway, "waffle": v_waffle, "gauge": v_gauge,
        "counter": v_counter, "clusters": v_clusters, "heatmap": v_heatmap, "experiment": v_experiment,
        "feed": v_feed, "magnify": v_magnify, "survey": v_survey, "race": v_race, "cascade": v_cascade,
        "balance": v_balance, "chat": v_chat, "geo": v_geo, "ranking": v_ranking, "swipe": v_swipe,
        "clock": v_clock, "echo": v_echo, "predict": v_predict}


def draw(sc, p: float, ctx: dict) -> Image.Image:
    c = Canvas()
    DRAW.get(sc.visual, v_icons)(c, sc, p, ctx)
    img = c.finish()
    z = 1 + 0.04 * ease(p)  # slow push-in so no scene sits still
    if sc.visual in ("hook", "takeaway") or z < 1.002:
        return img
    w, h = int(VW / z), int(VH / z)
    return img.resize((VW, VH), Image.BILINEAR, box=((VW - w) / 2, (VH - h) / 2, (VW + w) / 2, (VH + h) / 2))
