"""Studio sound effects, all made in code: a band sting, and the audience (see crowd.py)."""
import numpy as np
import crowd

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
    return crowd.applause(dur, gain, seed=int(rng.integers(1 << 30)))


def laugh(bank, dur, gain=1.0):
    return crowd.tts_laugh(bank, dur, gain, seed=int(rng.integers(1 << 30)))


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
