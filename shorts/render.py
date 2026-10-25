"""Compose 1080x1920 frames (header, scene visual, subtitles) for one language and encode with ffmpeg."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from . import brand, visuals
from .config import ASSETS, BRAND_EN, BRAND_ZH, CORAL, CREAM, FPS, H, INK_MUTED, NAVY, W

from .fonts import clause_wrap, fit, font
from .script import Script
from .tts import SceneTiming

VIS_X, VIS_Y = (W - visuals.VW) // 2, 360
SUB_Y = 1235
MARGIN = 80


@dataclass
class SceneView:
    """One scene in one language, as the renderer and visuals see it."""
    visual: str
    heading: str
    labels: list[str]
    values: list[float]
    big_text: str
    lines: list[str]


def localize(script: Script, lang: str) -> list[SceneView]:
    if lang == "pt":
        if not script.pt:
            raise RuntimeError("Script has no Portuguese version")
        return [SceneView(sc.visual, ls.heading.upper(), ls.labels, sc.values, ls.big_text, ls.lines)
                for sc, ls in zip(script.scenes, script.pt.scenes)]
    out = []
    for sc in script.scenes:
        if lang == "zh":
            out.append(SceneView(sc.visual, sc.heading_zh, sc.labels, sc.values, sc.big_text,
                                 [l.zh for l in sc.lines]))
        else:
            out.append(SceneView(sc.visual, sc.heading_en.upper(), sc.labels_en or sc.labels, sc.values,
                                 sc.big_text_en or sc.big_text, [l.en for l in sc.lines]))
    return out


def subtitle_lines_en(text: str):
    text = text.strip()
    for size in (60, 56, 52, 48):
        f = font("bold", size)
        lines = clause_wrap(text, f, W - 2 * MARGIN)
        if lines and len(lines) <= 2:
            return f, lines
    return fit(text, "bold", W - 2 * MARGIN, [48], 3)


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
    def __init__(self, script: Script, paper: dict, timings: list[SceneTiming], total: float, lang: str = "zh"):
        self.paper, self.timings, self.total, self.lang = paper, timings, total, lang
        self.scenes = localize(script, lang)
        self.bg = background()
        self.small_logo = logo(64)
        self.ctx_base = {"paper": paper, "lang": lang,
                         "paper_title": {"zh": script.paper_title_zh,
                                         "pt": script.pt.paper_title if script.pt else ""}.get(lang) or paper["title"],
                         "logo": logo(150 * visuals.S)}
        self._header_cache: dict[int, Image.Image] = {}
        self.cards = brand.Cards(self.bg, logo(300), lang)

    @property
    def duration(self) -> float:
        return self.total + brand.OUTRO

    def frame_count(self) -> int:
        return int(self.duration * FPS)

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
        label = f"{i + 1:02d}  ·  {self.scenes[i].heading}"
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
        sc, st = self.scenes[i], self.timings[i]
        k = 0
        for j, lt in enumerate(st.lines):
            if t >= lt.start - 0.05:
                k = j
        line, lt = sc.lines[k], st.lines[k]
        end = st.lines[k + 1].start if k + 1 < len(st.lines) else st.end
        a = 1.0 if i == 0 and k == 0 else visuals.ease((t - lt.start + 0.05) / 0.15)  # frame 0 is readable
        a *= 1 - visuals.ease((t - (end - 0.1)) / 0.1) if k + 1 < len(st.lines) else 1
        f, rows = subtitle_lines(line) if self.lang == "zh" else subtitle_lines_en(line)
        y = SUB_Y + (1 - a) * 14
        col = tuple(int(CREAM[c] + (NAVY[c] - CREAM[c]) * a) for c in range(3))
        for ln in rows:
            d.text((MARGIN, y), ln, font=f, fill=col)
            y += f.size * 1.3
        prog = visuals.clamp((t - lt.start) / max(0.1, lt.end - lt.start))
        d.rounded_rectangle([MARGIN, y + 6, MARGIN + 120 * prog + 1, y + 13], 3, fill=CORAL)

    def source_line(self, d: ImageDraw.ImageDraw, i: int) -> None:
        if i == 0:
            return
        p = self.paper
        authors = p.get("authors") or []
        who = ""
        if authors:
            who = authors[0].split(" ")[-1] + (" et al." if len(authors) > 1 else "") + ", "
        txt = f"{'Fonte' if self.lang == 'pt' else 'Source'}: {who}{p['venue']} {p.get('published', '')[:4]}"
        d.text((MARGIN, 1580), txt, font=font("regular", 28), fill=INK_MUTED)

    def frame(self, n: int) -> Image.Image:
        t = n / FPS
        if t >= self.total:
            return self.cards.outro(t - self.total)
        i = self.scene_at(t)
        st = self.timings[i]
        p = visuals.clamp((t - st.start) / (st.end - st.start))
        img = self.header(i).copy()
        ctx = dict(self.ctx_base, seed=i * 101 + 7, t=t)
        vis = visuals.draw(self.scenes[i], p, ctx)
        # fade the visual in at scene start, except the hook: frame 0 must already grab attention
        alpha = 1.0 if i == 0 else visuals.ease((t - st.start) / 0.25)
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
