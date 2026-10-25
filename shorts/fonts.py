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


_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.,:;%'’&+\-/]*\s*|\s+|.")
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


def fit(text: str, weight: str, max_w: int, sizes: list[int], max_lines: int):
    """Largest size whose wrap fits within max_lines; returns (font, lines)."""
    for s in sizes:
        f = font(weight, s)
        lines = wrap(text, f, max_w, max_lines=99)
        if len(lines) <= max_lines:
            return f, lines
    f = font(weight, sizes[-1])
    return f, wrap(text, f, max_w, max_lines)
