"""Compose 1080x1920 frames (header, scene visual, bilingual subtitles) and encode with ffmpeg."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from . import visuals
from .config import ASSETS, BRAND_EN, BRAND_ZH, CORAL, CREAM, FPS, H, INK_MUTED, NAVY, W
from .fonts import fit, font, wrap
from .script import Script
from .tts import SceneTiming

VIS_X, VIS_Y = (W - visuals.VW) // 2, 360
SUB_Y = 1235
MARGIN = 80


def subtitle_lines(text: str):
    """Prefer one line (shrinking a little), else two lines at full size. No trailing period."""
    text = text.strip().rstrip("。.，,")
    f, lines = fit(text, "black", W - 2 * MARGIN, [66, 62, 58, 54], 1)
    if len(lines) == 1 and not lines[0].endswith("…"):
        return f, lines
    for size in (66, 60, 54):
        f = font("black", size)
        # break at the punctuation/space closest to the middle, if both halves fit
        cuts = [i + 1 for i, ch in enumerate(text[:-1]) if ch in "，、：；？！ "]
        for cut in sorted(cuts, key=lambda i: abs(i - len(text) / 2)):
            a, b = text[:cut].strip(), text[cut:].strip()
            if max(f.getlength(a), f.getlength(b)) <= W - 2 * MARGIN:
                return f, [a, b]
    return fit(text, "black", W - 2 * MARGIN, [66, 60, 54], 2)


def background() -> Image.Image:
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    for y in range(40, H, 48):  # faint dot grid, like graph paper
        for x in range(36, W, 48):
            d.ellipse([x - 1.6, y - 1.6, x + 1.6, y + 1.6], fill=(232, 223, 207))
    return img


def logo(size: int) -> Image.Image:
    im = Image.open(ASSETS / "avatar.png").convert("RGBA")
    # crop the cream margin so the mark itself fills the tile
    return im.crop((100, 160, 900, 840)).resize((size, int(size * 680 / 800)), Image.LANCZOS)


class Renderer:
    def __init__(self, script: Script, paper: dict, timings: list[SceneTiming], total: float):
        self.script, self.paper, self.timings, self.total = script, paper, timings, total
        self.bg = background()
        self.small_logo = logo(64)
        self.ctx_base = {"paper": paper, "paper_title_zh": script.paper_title_zh,
                         "logo": logo(150 * visuals.S)}
        self._header_cache: dict[int, Image.Image] = {}

    def frame_count(self) -> int:
        return int(self.total * FPS) + 1

    def scene_at(self, t: float) -> int:
        for i, s in enumerate(self.timings):
            if t < s.end:
                return i
        return len(self.timings) - 1

    def header(self, i: int) -> Image.Image:
        """Static parts for scene i: background, brand row, heading."""
        if i in self._header_cache:
            return self._header_cache[i]
        img = self.bg.copy()
        d = ImageDraw.Draw(img)
        img.paste(self.small_logo, (MARGIN, 128), self.small_logo)
        d.text((MARGIN + 84, 160), BRAND_ZH, font=font("black", 38), fill=NAVY, anchor="lm")
        zw = font("black", 38).getlength(BRAND_ZH)
        d.text((MARGIN + 100 + zw, 162), BRAND_EN, font=font("regular", 30), fill=INK_MUTED, anchor="lm")
        sc = self.script.scenes[i]
        label = f"{i + 1:02d}  {sc.heading_zh}  ·  {sc.heading_en.upper()}"
        d.text((MARGIN, 290), label, font=font("bold", 34), fill=CORAL, anchor="lm")
        self._header_cache = {i: img}
        return img

    def progress_bar(self, d: ImageDraw.ImageDraw, t: float) -> None:
        n = len(self.timings)
        gap = 10
        seg = (W - 2 * MARGIN - gap * (n - 1)) / n
        for k, s in enumerate(self.timings):
            x = MARGIN + k * (seg + gap)
            d.rounded_rectangle([x, 70, x + seg, 78], 4, fill=(222, 212, 196))
            frac = visuals.clamp((t - s.start) / (s.end - s.start))
            if frac > 0:
                d.rounded_rectangle([x, 70, x + max(8, seg * frac), 78], 4, fill=NAVY if frac < 1 else CORAL)

    def subtitles(self, d: ImageDraw.ImageDraw, i: int, t: float) -> None:
        sc, st = self.script.scenes[i], self.timings[i]
        k = 0
        for j, lt in enumerate(st.lines):
            if t >= lt.start - 0.05:
                k = j
        line, lt = sc.lines[k], st.lines[k]
        end = st.lines[k + 1].start if k + 1 < len(st.lines) else st.end
        a = visuals.ease((t - lt.start + 0.05) / 0.18)
        a *= 1 - visuals.ease((t - (end - 0.12)) / 0.12) if k + 1 < len(st.lines) else 1
        fz, zh = subtitle_lines(line.zh)
        y = SUB_Y + (1 - a) * 14
        col = tuple(int(CREAM[c] + (NAVY[c] - CREAM[c]) * a) for c in range(3))
        for ln in zh:
            d.text((MARGIN, y), ln, font=fz, fill=col)
            y += fz.size * 1.3
        prog = visuals.clamp((t - lt.start) / max(0.1, lt.end - lt.start))
        d.rounded_rectangle([MARGIN, y + 6, MARGIN + 120 * prog + 1, y + 13], 3, fill=CORAL)
        fe = font("regular", 38)
        y += 34
        en_col = tuple(int(CREAM[c] + (INK_MUTED[c] - CREAM[c]) * a) for c in range(3))
        for ln in wrap(line.en, fe, W - 2 * MARGIN, max_lines=2):
            d.text((MARGIN, y), ln, font=fe, fill=en_col)
            y += 50

    def source_line(self, d: ImageDraw.ImageDraw, i: int) -> None:
        if i == 0:
            return
        p = self.paper
        first = (p.get("authors") or [""])[0].split(" ")[-1]
        txt = f"Source: {first}{' et al.' if len(p.get('authors') or []) > 1 else ''}, {p['venue']} {p.get('published', '')[:4]}"
        d.text((MARGIN, 1580), txt, font=font("regular", 28), fill=INK_MUTED)

    def frame(self, n: int) -> Image.Image:
        t = n / FPS
        i = self.scene_at(t)
        st = self.timings[i]
        p = visuals.clamp((t - st.start) / (st.end - st.start))
        img = self.header(i).copy()
        ctx = dict(self.ctx_base, seed=i * 101 + 7, t=t)
        vis = visuals.draw(self.script.scenes[i], p, ctx)
        # fade the visual in at scene start
        alpha = visuals.ease((t - st.start) / 0.25)
        if alpha < 1:
            vis.putalpha(vis.getchannel("A").point(lambda v: int(v * alpha)))
        img.paste(vis, (VIS_X, VIS_Y + int((1 - alpha) * 30)), vis)
        d = ImageDraw.Draw(img)
        self.progress_bar(d, t)
        self.subtitles(d, i, t)
        self.source_line(d, i)
        return img


def encode(r: Renderer, audio: Path, out: Path, preview_every: int = 0) -> None:
    cmd = ["ffmpeg", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(audio),
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-g", str(FPS * 2),
           "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
           "-shortest", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin
    for n in range(r.frame_count()):
        img = r.frame(n)
        proc.stdin.write(img.tobytes())
        if preview_every and n % preview_every == 0:
            img.save(out.parent / f"frame_{n:05d}.png")
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed")
