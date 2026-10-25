"""Synthesize the dialogue with Kokoro (sherpa-onnx), lay it on a timeline, and
derive per-frame mouth shapes, subtitles and screen cards for the renderer.

Usage: python podcast/build_audio.py podcast/episodes/ep01.json
Writes podcast/out/dialog.wav and podcast/web/timeline.json."""
import json, os, re, sys, hashlib
from pathlib import Path
import numpy as np, soundfile as sf
import sherpa_onnx

FPS = 30
SR = 24000
INTRO = 3.2   # seconds of title before the first line
OUTRO = 3.0
ROOT = Path(__file__).parent
CACHE = ROOT / ".cache" / "tts"
OUT = ROOT / "out"
K = os.environ.get('KOKORO_DIR', str(ROOT / '.cache' / 'kokoro-multi-lang-v1_1')) + '/'

_tts = None
def tts():
    global _tts
    if _tts is None:
        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=K + 'model.onnx', voices=K + 'voices.bin', tokens=K + 'tokens.txt',
                data_dir=K + 'espeak-ng-data', dict_dir=K + 'dict',
                lexicon=K + 'lexicon-us-en.txt,' + K + 'lexicon-zh.txt'), num_threads=4),
            rule_fsts=K + 'date-zh.fst,' + K + 'phone-zh.fst,' + K + 'number-zh.fst')
        _tts = sherpa_onnx.OfflineTts(cfg)
    return _tts


def synth(text, sid, speed):
    key = hashlib.sha1(f"{text}|{sid}|{speed}".encode()).hexdigest()[:16]
    p = CACHE / f"{key}.wav"
    if not p.exists():
        a = tts().generate(text, sid=sid, speed=speed)
        sf.write(p, np.array(a.samples, dtype=np.float32), a.sample_rate)
    x, sr = sf.read(p, dtype='float32')
    assert sr == SR
    # trim silence, keep a few ms of breath
    env = np.abs(x) > 0.01
    idx = np.where(env)[0]
    if len(idx):
        x = x[max(0, idx[0] - 600): idx[-1] + 2400]
    return x


def mouth_track(x):
    """Five VRM visemes per frame from a single speaker's track."""
    hop = SR // FPS
    n = len(x) // hop + 1
    out = np.zeros((n, 5), np.float32)  # aa ih ou ee oh
    win = np.hanning(hop * 2)
    freqs = np.fft.rfftfreq(hop * 2, 1 / SR)
    lo = (freqs > 150) & (freqs < 900)
    mid = (freqs > 900) & (freqs < 2400)
    hi = (freqs > 2400) & (freqs < 5000)
    for i in range(n):
        seg = x[i * hop: i * hop + hop * 2]
        if len(seg) < hop * 2:
            seg = np.pad(seg, (0, hop * 2 - len(seg)))
        rms = np.sqrt((seg ** 2).mean()) + 1e-9
        db = 20 * np.log10(rms)
        open_ = np.clip((db + 42) / 26, 0, 1)
        if open_ <= 0:
            continue
        s = np.abs(np.fft.rfft(seg * win)) ** 2
        L, M, H = s[lo].sum() + 1e-9, s[mid].sum() + 1e-9, s[hi].sum() + 1e-9
        front = np.clip((np.log10(M / L) + 0.6) / 1.2, 0, 1)   # high F2 -> ee/ih
        fric = np.clip((np.log10(H / (L + M)) + 1.0) / 1.0, 0, 1)  # s/sh -> narrow
        round_ = (1 - front) * (1 - fric)
        w = np.array([
            (1 - front) * (1 - round_ * 0.6),     # aa
            front * fric,                         # ih
            round_ * 0.5,                         # ou
            front * (1 - fric),                   # ee
            round_ * 0.6,                         # oh
        ])
        w = w / (w.sum() + 1e-9) * open_
        out[i] = w
    # attack fast, release slower
    sm = np.zeros_like(out)
    for i in range(n):
        prev = sm[i - 1] if i else 0
        a = np.where(out[i] > prev, 0.75, 0.4)
        sm[i] = prev + a * (out[i] - prev)
    return sm


def chunks(text, maxlen=17):
    """Split a line into subtitle chunks at punctuation, no chunk longer than maxlen."""
    parts = [p for p in re.split(r'(?<=[，。？！、])', text) if p.strip()]
    out = []
    for p in parts:
        p = p.strip()
        while len(p) > maxlen:
            out.append(p[:maxlen]); p = p[maxlen:]
        if out and len(out[-1]) + len(p) <= 11 and not out[-1].endswith(('。', '？', '！')):
            out[-1] += p
        else:
            out.append(p)
    return [re.sub(r'[，。、]$', '', c) for c in out]


def main():
    CACHE.mkdir(parents=True, exist_ok=True); OUT.mkdir(exist_ok=True)
    ep = json.loads(Path(sys.argv[1]).read_text())
    hosts = ep['hosts']
    total = INTRO + 2
    placed = []
    t = INTRO
    for spk, text, opt in ep['lines']:
        x = synth(text, hosts[spk]['voice'], round(opt.get('speed', 1.0) * 1.15, 3))
        gap = opt.get('gap', 0.3)
        t += gap
        placed.append((spk, text, opt, t, x))
        t += len(x) / SR
    total = t + OUTRO
    N = int(total * SR) + SR
    tracks = {'A': np.zeros(N, np.float32), 'B': np.zeros(N, np.float32)}
    lines = []
    for spk, text, opt, st, x in placed:
        i = int(st * SR)
        tracks[spk][i:i + len(x)] += x
        en = st + len(x) / SR
        L = {'spk': spk, 'start': round(st, 3), 'end': round(en, 3), 'text': text,
             'emo': opt.get('emo'), 'gest': opt.get('gest'), 'card': opt.get('card')}
        # subtitles: proportional timing on characters
        cs = chunks(opt.get('sub', text.replace('Change dot org', 'Change.org')))
        lens = np.array([len(c) for c in cs], float)
        edges = st + np.concatenate([[0], np.cumsum(lens) / lens.sum()]) * (en - st)
        L['subs'] = [[round(edges[k], 3), round(edges[k + 1], 3), c] for k, c in enumerate(cs)]
        lines.append(L)
        if opt.get('back'):
            other = 'B' if spk == 'A' else 'A'
            b = synth(opt['back'], hosts[other]['voice'], 1.0) * 0.45
            bt = st + (en - st) * 0.5
            j = int(bt * SR)
            tracks[other][j:j + len(b)] += b
            L['back'] = {'spk': other, 'start': round(bt, 3), 'end': round(bt + len(b) / SR, 3)}
    mix = tracks['A'] + tracks['B']
    # gentle room tone so silences are not digital-black
    rng = np.random.default_rng(1)
    room = rng.normal(0, 1, N).astype(np.float32)
    room = np.convolve(room, np.ones(40) / 40, 'same') * 0.0025
    mix = mix + room
    peak = np.abs(mix).max()
    mix = mix / peak * 0.89
    sf.write(OUT / 'dialog.wav', mix[:int(total * SR)], SR)
    mouths = {k: np.round(mouth_track(v[:int(total * SR)]), 3).tolist() for k, v in tracks.items()}
    tl = {'fps': FPS, 'duration': round(total, 3), 'intro': INTRO, 'title': ep['title'],
          'paper': ep['paper'], 'hosts': hosts, 'lines': lines, 'mouth': mouths}
    (ROOT / 'web' / 'timeline.json').write_text(json.dumps(tl, ensure_ascii=False))
    print(f"duration {total:.1f}s, {len(lines)} lines")


if __name__ == '__main__':
    main()
