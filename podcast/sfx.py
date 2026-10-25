"""Studio sound effects: a band sting made in code, and applause and audience laughs layered
from real recordings (ESC-50 clapping and laughing clips, fetched by setup.sh)."""
import os
from pathlib import Path
import numpy as np

SR = 24000
rng = np.random.default_rng(7)
CROWD_DIR = os.environ.get("CROWD_DIR", str(Path(__file__).parent / ".cache" / "esc50" / "audio"))


def _env(n, a, d):
    e = np.ones(n, np.float32)
    a, d = int(a * SR), int(d * SR)
    if a: e[:a] = np.linspace(0, 1, a)
    if d: e[-d:] *= np.linspace(1, 0, d) ** 2
    return e


def _lowpass(x, cut):
    # one-pole lowpass, cut in Hz (scalar or per-sample array)
    a = np.exp(-2 * np.pi * np.asarray(cut, np.float32) / SR) * np.ones(len(x), np.float32)
    y = np.zeros_like(x); s = 0.0
    for i in range(len(x)):
        s = (1 - a[i]) * x[i] + a[i] * s; y[i] = s
    return y


def _bandpass(x, lo, hi):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, len(x)).astype(np.float32)


def reverb(x, seconds=1.4, wet=0.3):
    n = int(seconds * SR)
    ir = rng.normal(0, 1, n).astype(np.float32) * np.exp(-np.linspace(0, 7, n)).astype(np.float32)
    ir = _bandpass(ir, 150, 6000); ir /= np.abs(ir).sum() ** 0.5 * 8
    L = len(x) + n
    y = np.fft.irfft(np.fft.rfft(x, L) * np.fft.rfft(ir, L), L)[:len(x) + n].astype(np.float32)
    out = np.zeros(len(x) + n, np.float32); out[:len(x)] += x * (1 - wet)
    return out + y * wet


APPLAUSE_CLIPS = ['1-105224-A', '1-110537-A', '1-94036-A', '3-177082-A', '4-189828-A', '4-189832-A', '4-189832-B',
                  '4-189833-A', '4-189836-A', '4-189838-A', '4-205738-A', '5-218494-A', '5-249937-A', '5-262957-A']
LAUGH_CLIPS = ['1-1791-A', '1-30043-A', '1-36164-B', '1-73123-A', '2-60791-A', '2-60794-A', '2-60795-A', '2-62226-A',
               '2-79769-A', '2-79775-A', '3-107123-A', '3-110536-A', '3-118487-A', '3-119459-A', '3-126113-A',
               '3-132747-A', '4-132803-A', '4-132810-A', '4-132816-A', '4-164243-A', '4-167571-A', '5-244526-A',
               '5-253534-A']
BIG_LAUGHS = ['1-36164-B', '1-73123-A', '2-79769-A', '3-118487-A', '4-132816-A', '5-253534-A', '4-132810-A', '3-107123-A']
# clips the CED audio tagger hears as 'Laughter' / 'Belly laugh' rather than 'Snicker'
FULL_LAUGHS = BIG_LAUGHS + ['5-244526-A', '3-110536-A', '4-132803-A']
ROOM_LAUGHS = ['2-60791-A', '2-60794-A', '2-60795-A']  # recorded in a hall, several people
_clips = {}


def _load(name, cls):
    """A real recording from ESC-50 (podcast/.cache/esc50), mono at SR, trimmed and normalized."""
    if name not in _clips:
        import soundfile as sf
        x, sr = sf.read(f"{CROWD_DIR}/{name}-{cls}.wav", dtype='float32')
        if x.ndim > 1: x = x.mean(1)
        x = np.interp(np.arange(0, len(x), sr / SR), np.arange(len(x)), x).astype(np.float32)
        x = x - x.mean()
        e = np.convolve(np.abs(x), np.ones(480) / 480, 'same')
        on = np.where(e > e.max() * 0.08)[0]
        if len(on): x = x[max(0, on[0] - 240): on[-1] + 2400]
        _clips[name] = x / (np.sqrt((x ** 2).mean()) + 1e-9) * 0.1
    return _clips[name]


def _resample(x, ratio):
    idx = np.arange(0, len(x) - 1, ratio)
    return np.interp(idx, np.arange(len(x)), x).astype(np.float32)


def applause(dur, gain=1.0):
    """Studio applause from real audience recordings: several crowds layered and crossfaded."""
    n = int((dur + 1.4) * SR)
    out = np.zeros(n, np.float32)
    xf = int(0.5 * SR)
    for layer in range(3):
        t = int(rng.random() * 0.12 * SR)
        while t < n:
            c = _load(APPLAUSE_CLIPS[rng.integers(len(APPLAUSE_CLIPS))], 22)
            c = _resample(c, 0.96 + rng.random() * 0.08)
            c = c[int(rng.random() * 0.3 * len(c)):]
            c = c * _env(len(c), 0.04 if t < SR else 0.5, 0.5)
            L = min(len(c), n - t); out[t:t + L] += c[:L] * (0.6 + 0.4 * rng.random())
            t += len(c) - xf
    out = reverb(out, 1.0, 0.18)[:n]
    # quick swell, hold, then the crowd thins out over the last second
    e = _env(n, 0.12, 0.05)
    tail = np.clip((np.arange(n) / SR - dur) / 1.2, 0, 1)
    out *= e * (1 - tail) ** 1.6
    return out / (np.abs(out).max() + 1e-9) * 0.5 * gain


def laugh(dur, gain=1.0):
    """Audience laugh from real recorded laughs: a room bed plus individual laughers at different distances."""
    n = int((dur + 1.6) * SR)
    out = np.zeros(n, np.float32)
    k = 22 + int(22 * min(1.0, dur / 2.6))
    w = np.array([8.0 if c in FULL_LAUGHS else 0.5 for c in LAUGH_CLIPS]); w /= w.sum()   # mostly open, full-voiced laughs
    for j in range(k):
        p = rng.choice(len(LAUGH_CLIPS), p=w)
        c = _load(LAUGH_CLIPS[p], 26)
        c = _resample(c[int(rng.random() * 0.25 * len(c)):], 0.9 + rng.random() * 0.2)
        seg = int(min(len(c), (dur * (0.55 + 0.5 * rng.random()) + 0.4) * SR))
        c = c[:seg] * _env(seg, 0.03, min(0.6, seg / SR / 2))
        start = int((rng.random() * 0.3 + rng.exponential(0.08)) * SR)
        far = rng.random()
        g = (1.0 - 0.65 * far) * (0.7 + 0.3 * rng.random())
        if far > 0.4: c = reverb(_lowpass(c, 1800 + 1500 * (1 - far)), 1.4, 0.6)[:len(c) + SR // 2]  # back rows
        L = min(len(c), n - start); out[start:start + L] += c[:L] * g
    for p in ROOM_LAUGHS[:1 + int(dur > 2)]:
        c = _load(p, 26)[:int((dur + 0.6) * SR)]
        c = c * _env(len(c), 0.05, 0.6)
        L = min(len(c), n); out[:L] += c[:L] * 0.5
    out = _bandpass(out, 90, 9000)
    out = reverb(out, 1.2, 0.3)[:n]
    out *= _env(n, 0.04, dur * 0.5 + 0.6)
    return out / (np.abs(out).max() + 1e-9) * 0.45 * gain


def sting(dur=3.2):
    """House-band hit: drum fill into a brassy chord and a crash."""
    n = int(dur * SR); t = np.arange(n) / SR
    out = np.zeros(n, np.float32)
    def put(x, at, g=1.0):
        i = int(at * SR); L = min(len(x), n - i); out[i:i + L] += x[:L] * g
    def kick():
        m = int(0.35 * SR); tt = np.arange(m) / SR
        return (np.sin(2 * np.pi * (50 * tt + 90 * (1 - np.exp(-tt * 30)) / 30)) * np.exp(-tt * 9)).astype(np.float32)
    def snare():
        m = int(0.25 * SR); tt = np.arange(m) / SR
        return (_bandpass(rng.normal(0, 1, m).astype(np.float32), 1500, 8000) * np.exp(-tt * 18) * 0.7 + np.sin(2 * np.pi * 190 * tt) * np.exp(-tt * 25) * 0.5).astype(np.float32)
    def tom(f):
        m = int(0.3 * SR); tt = np.arange(m) / SR
        return (np.sin(2 * np.pi * f * tt * (1 - tt * 0.6)) * np.exp(-tt * 12)).astype(np.float32)
    for at, x in [(0.0, kick()), (0.0, snare()), (0.18, snare()), (0.36, tom(180)), (0.48, tom(150)), (0.6, tom(120)), (0.72, tom(95)), (0.84, snare())]:
        put(x, at, 0.8)
    hit = 0.98
    put(kick(), hit, 1.2)
    crash = _bandpass(rng.normal(0, 1, int(2.2 * SR)).astype(np.float32), 4000, 11000) * np.exp(-np.linspace(0, 6, int(2.2 * SR)))
    put(crash.astype(np.float32), hit, 0.5)
    # brass: detuned saws on a big major chord, filter opens then closes
    chord = [130.81, 164.81, 196.0, 246.94, 293.66, 392.0]
    m = int((dur - hit) * SR); tt = np.arange(m) / SR
    brass = np.zeros(m, np.float32)
    for f in chord:
        for det in (-0.004, 0.0, 0.004):
            ph = (f * (1 + det) * tt) % 1.0
            brass += (2 * ph - 1).astype(np.float32)
    cut = 600 + 3800 * np.exp(-tt * 2.5) * (1 - np.exp(-tt * 40))
    brass = _lowpass(brass / len(chord) / 3, cut) * _env(m, 0.015, 1.2)
    put(brass, hit, 0.9)
    out = reverb(out, 1.2, 0.2)[:n]
    return out / (np.abs(out).max() + 1e-9) * 0.6
