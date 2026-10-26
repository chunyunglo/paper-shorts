"""Studio audience from real recordings, all CC0 from Freesound (see assets/crowd/CREDITS.md).

Laughs: Kinoton's "Sitcom Laughter 9x, Small Audience", cut into its nine laughs. Each audience
reaction uses the laugh whose length fits best (never the same one twice in a row), with a second
laugh layered under it for big reactions, so the room sounds bigger and repeats are hard to spot.

Applause: nervousneal's "Applause, small audience" (about 50 people). A stretch of the steady part,
a swell in, then the recording's own tail as people stop; two offset layers for a fuller house.
"""
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SR = 24000
ASSETS = Path(__file__).parent / 'assets' / 'crowd'
_cache = {}


def _load(name):
    if name not in _cache:
        x, sr = sf.read(str(ASSETS / name), dtype='float32')
        if x.ndim > 1:
            x = x.mean(1)
        g = np.gcd(SR, sr)
        _cache[name] = resample_poly(x, SR // g, sr // g).astype(np.float32)
    return _cache[name]


def _laughs():
    return sorted(p.name for p in ASSETS.glob('laugh_*.flac'))


def _pitch(x, ratio):
    n = max(8, int(len(x) / ratio))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def _fit(x, length, fade):
    """Cut x to length samples with a fade-out of fade seconds at the end (if it is longer)."""
    if len(x) <= length:
        return x
    y = x[:length].copy()
    f = min(len(y), int(fade * SR))
    y[-f:] *= np.linspace(1, 0, f) ** 2
    return y


_last = []


def laugh(dur, gain=1.0, rng=None):
    rng = rng or np.random.default_rng()
    names = _laughs()
    want = dur + 0.9
    fresh = [n for n in names if n not in _last[-2:]] or names
    lens = np.array([len(_load(n)) / SR for n in fresh])
    score = np.abs(lens - want) + 0.5 * (lens < dur) + rng.uniform(0, 0.6, len(fresh))
    main = fresh[int(np.argmin(score))]
    _last.append(main)
    total = int((dur + 1.4) * SR)
    out = np.zeros(total, np.float32)
    x = _fit(_load(main), total, 0.7)
    out[:len(x)] += x
    if gain > 0.8:   # a second group a beat later, a little lower: a bigger room
        other = names[int(rng.integers(len(names)))]
        if other == main:
            other = names[(names.index(main) + 1) % len(names)]
        y = _pitch(_load(other), rng.uniform(0.97, 1.03))
        d = int(rng.uniform(0.08, 0.2) * SR)
        y = _fit(y, total - d, 0.7)
        out[d:d + len(y)] += y * 0.45
    return (out / (np.abs(out).max() + 1e-9) * 0.6 * gain).astype(np.float32)


def applause(dur, gain=1.0, rng=None):
    rng = rng or np.random.default_rng()
    x = _load('applause_1.flac')
    tail_at = int(8.4 * SR)                      # from here on, the recorded crowd winds down
    body, tail = x[:tail_at], x[tail_at:]
    n = int(dur * SR)
    cf = int(0.3 * SR)
    total = n + len(tail)
    out = np.zeros(total, np.float32)
    for layer, g in ((0, 1.0), (1, 0.55)):
        s = int(rng.uniform(0, max(1, len(body) - n - 1)))
        seg = body[s:s + n]
        if layer:
            seg = _pitch(seg, rng.uniform(0.96, 1.04))[:n]
        seg = seg.copy()
        sw = min(len(seg), int(0.35 * SR))
        seg[:sw] *= np.linspace(0, 1, sw) ** 1.5          # swell in
        seg[-cf:] *= np.linspace(1, 0, cf)                # crossfade into the recorded tail
        t = tail.copy(); t[:cf] *= np.linspace(0, 1, cf)
        out[:len(seg)] += seg * g
        a = len(seg) - cf
        out[a:a + len(t)] += t[:total - a] * g
    return (out / (np.abs(out).max() + 1e-9) * 0.55 * gain).astype(np.float32)
