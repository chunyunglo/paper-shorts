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


DRAW = {"hook": v_hook, "paper": v_paper, "crowd": v_crowd, "network": v_network,
        "pipeline": v_pipeline, "bars": v_bars, "timeline": v_timeline, "scatter": v_scatter,
        "contrast": v_contrast, "icons": v_icons, "journey": v_journey, "spotlight": v_spotlight,
        "funnel": v_funnel, "takeaway": v_takeaway}


def draw(sc, p: float, ctx: dict) -> Image.Image:
    c = Canvas()
    DRAW.get(sc.visual, v_icons)(c, sc, p, ctx)
    img = c.finish()
    z = 1 + 0.04 * ease(p)  # slow push-in so no scene sits still
    if sc.visual in ("hook", "takeaway") or z < 1.002:
        return img
    w, h = int(VW / z), int(VH / z)
    return img.resize((VW, VH), Image.BILINEAR, box=((VW - w) / 2, (VH - h) / 2, (VW + w) / 2, (VH + h) / 2))
