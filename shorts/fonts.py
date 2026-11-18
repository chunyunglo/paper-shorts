"""Font lookup (Noto Sans CJK TC) and text wrapping for mixed Chinese/English."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

CANDIDATES = {
    "bold": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
             "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc"],
    "regular": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"],
    "black": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"],
}


@lru_cache(maxsize=None)
def _face_index(path: str) -> int:
    """Index of the Traditional Chinese face inside the .ttc collection."""
    for i in range(12):
        try:
            name = ImageFont.truetype(path, 20, index=i).getname()[0]
        except OSError:
            break
        if name.endswith(" TC"):
            return i
    return 0


@lru_cache(maxsize=None)
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for path in CANDIDATES[weight]:
        if Path(path).exists():
            return ImageFont.truetype(path, size, index=_face_index(path))
    raise SystemExit("Noto Sans CJK not found; install fonts-noto-cjk")


# Latin words, accents included (pecuária, vídeo), stay whole; CJK breaks per character
_TOKEN = re.compile(r"[A-Za-z0-9À-ÖØ-öø-ɏ][A-Za-z0-9À-ÖØ-öø-ɏ.,:;%'’&+\-/]*\s*|\s+|.")
_NO_LINE_START = set("，。、！？：；）」』,.!?:;)%")


def wrap(text: str, f: ImageFont.FreeTypeFont, max_w: int, max_lines: int = 3) -> list[str]:
    lines: list[str] = []
    cur = ""
    for tok in _TOKEN.findall(text.strip()):
        trial = cur + tok
        if f.getlength(trial.rstrip()) <= max_w or not cur.strip():
            cur = trial
        elif tok[0] in _NO_LINE_START:
            cur = trial  # keep punctuation with the previous line
        else:
            lines.append(cur.rstrip())
            cur = tok.lstrip()
    if cur.strip():
        lines.append(cur.rstrip())
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and f.getlength(last + "…") > max_w:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


_CLAUSE = re.compile(r"[^，、：；？！,;:?!\s]+[，、：；？！,;:?!]*\s*")


def clause_wrap(text: str, f: ImageFont.FreeTypeFont, max_w: int) -> list[str] | None:
    """Break only after punctuation (or spaces), packing clauses greedily. None if a clause is too wide."""
    lines: list[str] = []
    cur = ""
    for clause in _CLAUSE.findall(text.strip()):
        if f.getlength(clause.strip()) > max_w:
            return None
        if cur and f.getlength((cur + clause).strip()) > max_w:
            lines.append(cur.strip())
            cur = clause
        else:
            cur += clause
    if cur.strip():
        lines.append(cur.strip())
    return lines


def fit(text: str, weight: str, max_w: int, sizes: list[int], max_lines: int):
    """Largest size whose wrap fits within max_lines and max_w; returns (font, lines).
    Multi-line text breaks at punctuation when it can, so phrases stay whole. When even the
    smallest size given is too big (a long word in a narrow card), it keeps shrinking, down to
    60% of that size, before it cuts the text short."""
    last = sizes[-1]
    smaller = [s for s in (round(last * k) for k in (0.9, 0.8, 0.7, 0.6)) if s < last]
    for s in [*sizes, *smaller]:
        f = font(weight, s)
        lines = wrap(text, f, max_w, max_lines=99)
        if len(lines) > max_lines or any(f.getlength(ln) > max_w for ln in lines):
            continue
        if len(lines) == 1:
            return f, lines
        nicer = clause_wrap(text, f, max_w)
        return f, nicer if nicer and len(nicer) <= max_lines else lines
    f = font(weight, smaller[-1] if smaller else last)
    lines = wrap(text, f, max_w, max_lines)
    return f, [_shorten(ln, f, max_w) for ln in lines]


def _shorten(line: str, f: ImageFont.FreeTypeFont, max_w: int) -> str:
    if f.getlength(line) <= max_w:
        return line
    while line and f.getlength(line + "…") > max_w:
        line = line[:-1]
    return line + "…"
