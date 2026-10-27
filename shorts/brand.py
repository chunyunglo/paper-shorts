"""The fixed closing card. It is identical in every episode (only the language changes), so the
channel always closes the same way, in the same palette. There is no opening card: the first
frame is the hook, because viewers decide in the first seconds whether to keep watching."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from .config import BRAND_EN, BRAND_ZH, CORAL, CREAM, HANDLE, INK_MUTED, NAVY, W
from .fonts import font

OUTRO = 2.4   # seconds

FOLLOW = {"zh": "追蹤・週一到週六 每天一篇新論文", "en": "Follow · a new paper every Mon–Sat",
          "pt": "Siga · um estudo novo de segunda a sábado"}


def _ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def _mix(c, a: float):
    return tuple(int(CREAM[i] + (c[i] - CREAM[i]) * a) for i in range(3))


class Cards:
    def __init__(self, bg: Image.Image, logo: Image.Image, lang: str):
        self.bg, self.logo, self.lang = bg, logo, lang

    def _brand(self, img: Image.Image, t: float, y: int) -> None:
        """Logo, channel name and a coral rule, animating in over the first ~0.5 s of t."""
        a = _ease(t / 0.45)
        lg = self.logo
        if a < 1:
            s = 0.85 + 0.15 * a
            lg = lg.resize((int(lg.width * s), int(lg.height * s)), Image.LANCZOS)
            lg.putalpha(lg.getchannel("A").point(lambda v: int(v * a)))
        img.paste(lg, ((W - lg.width) // 2, y - lg.height // 2), lg)
        d = ImageDraw.Draw(img)
        b = _ease((t - 0.15) / 0.4)
        top = y + self.logo.height // 2 + 40
        d.text((W / 2, top + 70 + (1 - b) * 20), BRAND_ZH, font=font("black", 120), fill=_mix(NAVY, b), anchor="mm")
        d.text((W / 2, top + 175 + (1 - b) * 20), BRAND_EN, font=font("bold", 52), fill=_mix(INK_MUTED, b), anchor="mm")
        r = _ease((t - 0.3) / 0.35) * 220
        d.rounded_rectangle([W / 2 - r, top + 235, W / 2 + r + 1, top + 247], 6, fill=CORAL)

    def outro(self, t: float) -> Image.Image:
        img = self.bg.copy()
        self._brand(img, t, 660)
        d = ImageDraw.Draw(img)
        a = _ease((t - 0.5) / 0.4)
        d.rounded_rectangle([140, 1160, W - 140, 1290], 65, fill=_mix(NAVY, a))
        d.text((W / 2, 1225), FOLLOW[self.lang], font=font("bold", {"zh": 44, "en": 40}.get(self.lang, 34)),
               fill=CREAM, anchor="mm")
        d.text((W / 2, 1370), HANDLE, font=font("regular", 40), fill=_mix(INK_MUTED, a), anchor="mm")
        return img


def sting(sr: int, seconds: float, rising: bool) -> np.ndarray:
    """A short fixed chime (C-E-G up, or G-E-C down for the outro). Generated, not licensed."""
    n = int(sr * seconds)
    out = np.zeros(n, dtype=np.float32)
    notes = [523.25, 659.25, 783.99]
    for k, f in enumerate(notes if rising else notes[::-1]):
        lo = int(k * 0.11 * sr)
        m = min(int(0.9 * sr), n - lo)
        if m <= 0:
            continue
        s = np.arange(m) / sr
        tone = np.sin(2 * np.pi * f * s) + 0.25 * np.sin(4 * np.pi * f * s)
        out[lo:lo + m] += (0.07 * np.exp(-s * 4.5) * tone).astype(np.float32)
    fade = min(int(0.3 * sr), n)
    out[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    return out


def wrap_audio(a: np.ndarray, sr: int) -> np.ndarray:
    return np.concatenate([a, sting(sr, OUTRO, False)])
