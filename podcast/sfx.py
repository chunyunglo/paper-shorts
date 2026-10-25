"""Studio sound effects made in code: band sting, applause, and an audience laugh built
from many short TTS laughs (no sample libraries needed)."""
import numpy as np

SR = 24000
rng = np.random.default_rng(7)


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


def applause(dur, gain=1.0):
    n = int((dur + 1.2) * SR)
    out = np.zeros(n, np.float32)
    clap = lambda: _bandpass(rng.normal(0, 1, int(0.03 * SR)).astype(np.float32), 600 + rng.random() * 800, 2500 + rng.random() * 3000) * np.exp(-np.linspace(0, 9, int(0.03 * SR)))
    for _ in range(70):
        rate = 3.5 + rng.random() * 3
        t = rng.random() * 0.35
        stop = dur * (0.75 + rng.random() * 0.35)
        g = 0.4 + rng.random() * 0.6
        while t < stop:
            i = int(t * SR); c = clap()
            fade = min(1.0, (stop - t) / 0.6)
            out[i:i + len(c)] += c[:max(0, n - i)] * g * fade
            t += 1 / rate * (0.85 + rng.random() * 0.3)
    out = reverb(out, 1.0, 0.25)[:n]
    out *= _env(n, 0.25, 0.9)
    return out / (np.abs(out).max() + 1e-9) * 0.5 * gain


def laugh(clips, dur, gain=1.0):
    """Crowd laugh: many short TTS laughs, pitch-shifted, staggered, through a room."""
    n = int((dur + 1.5) * SR)
    out = np.zeros(n, np.float32)
    for _ in range(36):
        c = clips[rng.integers(len(clips))]
        ratio = 0.85 + rng.random() * 0.4
        idx = np.arange(0, len(c) - 1, ratio)
        c = np.interp(idx, np.arange(len(c)), c).astype(np.float32)
        c = c * _env(len(c), 0.02, min(0.4, len(c) / SR / 2))
        start = int(rng.random() * 0.45 * SR + rng.exponential(0.12) * SR)
        g = (0.3 + rng.random() * 0.7) * (0.6 if rng.random() < 0.5 else 1.0)
        L = min(len(c), n - start)
        out[start:start + L] += c[:L] * g
    out = _bandpass(out, 180, 5500)
    out = reverb(out, 1.3, 0.45)[:n]
    out *= _env(n, 0.05, dur * 0.6)
    return out / (np.abs(out).max() + 1e-9) * 0.42 * gain


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
