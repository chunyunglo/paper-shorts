"""Studio audience made entirely in code (no recordings, so no licence strings attached).

Applause: a physical model of a crowd clapping (after Peltola et al., "Synthesis of hand clapping
sounds", 2007). Each clapper has a hand configuration (a resonant band), a clapping rate with
jitter, and a distance; they join in over the first half second and drop out one by one.

Laughter: single "hah / ha / huh" syllables spoken by each of the 103 Kokoro voices (Apache-2.0),
re-timed into a laugh: 4-5 syllables a second, every one a different take, pitch and brightness,
falling in pitch and level, with the odd breath. A few laughers up front over a quiet wash.
"""
import numpy as np
from scipy.signal import lfilter, butter, sosfilt

SR = 24000


def _reson(x, f, bw):
    """Two-pole resonator at f Hz with bandwidth bw Hz, unity gain at the peak (roughly)."""
    r = np.exp(-np.pi * bw / SR)
    a1, a2 = -2 * r * np.cos(2 * np.pi * f / SR), r * r
    return lfilter([1 - r], [1, a1, a2], x)


def _filt(x, kind, f, order=2):
    sos = butter(order, np.asarray(f) / (SR / 2), btype=kind, output='sos')
    return sosfilt(sos, x)


def _room(x, rng, t60=1.1, wet=0.35, pre=0.012):
    """Diffuse studio room: exponentially decaying filtered noise IR with a short pre-delay."""
    n = int(t60 * SR)
    t = np.arange(n) / SR
    ir = rng.normal(0, 1, n) * np.exp(-6.9 * t / t60)
    ir = _filt(ir, 'bandpass', (180, 5500))
    ir[: int(pre * SR)] = 0
    ir /= np.sqrt((ir ** 2).sum()) * 3.0
    L = len(x) + n
    y = np.fft.irfft(np.fft.rfft(x, L) * np.fft.rfft(ir, L), L)
    out = y * wet
    out[: len(x)] += x * (1 - wet)
    return out


def _fade(n, a, d):
    e = np.ones(n)
    a, d = int(a * SR), int(d * SR)
    if a > 0:
        e[:a] = np.linspace(0, 1, a) ** 1.5
    if d > 0:
        e[-d:] *= np.linspace(1, 0, d) ** 2
    return e


# ---------------------------------------------------------------- applause

def applause(dur, gain=1.0, seed=None):
    rng = np.random.default_rng(seed)
    n = int((dur + 1.4) * SR)
    groups = {'near': np.zeros(n), 'mid': np.zeros(n), 'far': np.zeros(n)}
    count = int(300 + 100 * min(1.0, dur / 3))
    for _ in range(count):
        dist = rng.choice(['near', 'mid', 'far'], p=[0.0, 0.45, 0.55])
        g = {'near': 1.0, 'mid': 0.8, 'far': 0.6}[dist] * rng.uniform(0.6, 1.0)
        rate = rng.uniform(3.3, 5.6)
        t = rng.exponential(0.12) + rng.uniform(0, 0.25)              # joining in
        stop = dur * rng.uniform(0.7, 1.08)                             # dropping out one by one
        fc = rng.uniform(750, 2300); bw = fc / rng.uniform(1.8, 5.0)   # hand configuration
        burst_len = int(rng.uniform(0.008, 0.016) * SR)
        x = np.zeros(n)
        while t < stop:
            i = int(t * SR)
            if i + burst_len * 4 >= n:
                break
            amp = g * rng.uniform(0.7, 1.15) * (0.85 if t > stop - 0.4 else 1.0)
            b = rng.normal(0, 1, burst_len * 4) * np.exp(-np.arange(burst_len * 4) / burst_len)
            x[i:i + len(b)] += amp * b
            t += (1 / rate) * rng.normal(1, 0.06)
            rate *= rng.uniform(0.995, 1.003)                           # slowly tiring
        y = _reson(x, fc, bw) * 1.0 + _filt(x, 'highpass', 1800) * 0.08 
        groups[dist] += y
    out = groups['near'] + _filt(groups['mid'], 'lowpass', 6000) + _filt(groups['far'], 'lowpass', 3500)
    out = _room(_filt(out, 'highpass', 300), rng, 1.2, 0.38)[:n]
    out *= _fade(n, 0.08, 0.9)
    return (out / (np.abs(out).max() + 1e-9) * 0.55 * gain).astype(np.float32)


# ---------------------------------------------------------------- laughter from TTS syllables

def syllable_bank(synth, path, voices=range(103), texts=('Hah!', 'Ha!', 'Huh!')):
    """Single laugh syllables spoken by every Kokoro voice (Apache-2.0), trimmed; cached to path."""
    import os
    if os.path.exists(path):
        z = np.load(path, allow_pickle=True)
        return list(z['bank'])
    bank = []
    for v in voices:
        for t in texts:
            y = synth(t, 'kokoro', v, 1.0)
            e = np.abs(y) > np.abs(y).max() * 0.05
            if not e.any():
                continue
            i0, i1 = np.argmax(e), len(e) - np.argmax(e[::-1])
            y = y[max(0, i0 - 120): min(len(y), i1 + 240)].astype(np.float32)
            bank.append((v, t, y / (np.abs(y).max() + 1e-9)))
    np.savez(path, bank=np.array(bank, dtype=object))
    return bank


def _shift(y, ratio):
    """Resample by ratio (>1 = higher and shorter)."""
    n = max(8, int(len(y) / ratio))
    return np.interp(np.linspace(0, len(y) - 1, n), np.arange(len(y)), y)


def tts_laugher(bank, dur, rng, voice=None):
    """One person laughing: that voice's laugh syllables in a laugh rhythm, every syllable a little
    different (which take, pitch, length, brightness), falling in pitch and level, with breaths."""
    v = rng.choice(sorted({b[0] for b in bank})) if voice is None else voice
    mine = [b[2] for b in bank if b[0] == v]
    rate = rng.uniform(3.9, 5.2)
    n = int((dur + 0.8) * SR)
    out = np.zeros(n)
    pos, k = rng.uniform(0, 0.04), 0
    syl = max(2, int(dur * rate))
    lift = rng.uniform(1.0, 1.2)
    while k < syl and pos < dur:
        prog = k / max(1, syl - 1)
        y = mine[rng.integers(len(mine))]
        y = _shift(y, lift * (1.14 - 0.2 * prog) * rng.normal(1, 0.05))
        L = min(len(y), int((1 / rate) * rng.uniform(0.75, 1.15) * SR))
        y = y[:L] * np.minimum(1, (L - np.arange(L)) / (0.03 * SR))
        if rng.random() < 0.5:                                      # brightness varies syllable to syllable
            y = y + rng.uniform(-0.5, 0.6) * np.diff(y, prepend=0) * 3
        loud = (1.0 if k == 0 else 0.85) * (1 - 0.5 * prog) * rng.uniform(0.75, 1.1)
        i = int(pos * SR)
        if i + L >= n:
            break
        out[i:i + L] += y * loud
        pos += (1 / rate) * rng.normal(1, 0.1) * (1 + 0.3 * prog)
        if rng.random() < 0.12 and k > 1:                           # catch a breath mid-laugh
            b = int(rng.uniform(0.15, 0.3) * SR); i = int(pos * SR)
            if i + b < n:
                out[i:i + b] += _filt(rng.normal(0, 1, b), 'bandpass', (900, 4000)) * 0.05 * np.sin(np.linspace(0, np.pi, b))
            pos += b / SR
        k += 1
    return out


def tts_laugh(bank, dur, gain=1.0, seed=None, near_n=4, far_n=16, far_gain=0.15):
    """Audience laugh: a handful of laughers you can pick out up front, over a wash of the rest of
    the room (quieter, duller, more reverberant, less in step)."""
    rng = np.random.default_rng(seed)
    n = int((dur + 1.8) * SR)
    near, far = np.zeros(n), np.zeros(n)
    voices = rng.permutation(sorted({b[0] for b in bank}))
    for j in range(near_n + far_n):
        is_near = j < near_n
        d = rng.uniform(0.7, 1.15) * dur if is_near else rng.uniform(0.4, 1.0) * dur
        start = rng.uniform(0.0, 0.3) + rng.exponential(0.1 if is_near else 0.25)
        y = tts_laugher(bank, d, rng, voices[j % len(voices)]) * rng.uniform(0.7, 1.0)
        i = int(start * SR); L = min(len(y), n - i)
        (near if is_near else far)[i:i + L] += y[:L]
    far = _filt(far, 'lowpass', 2600)
    out = near / max(1, near_n) ** 0.5 + far * far_gain / max(1, far_n) ** 0.5 * 2.5
    out = _filt(out, 'highpass', 100)
    out = _room(out, rng, 0.6, 0.1)[:n]
    out *= _fade(n, 0.03, dur * 0.45 + 0.6)
    return (out / (np.abs(out).max() + 1e-9) * 0.5 * gain).astype(np.float32)
