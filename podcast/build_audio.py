"""Synthesize the dialogue, lay it on a timeline with studio sound effects, and derive
per-frame mouth shapes, subtitles and screen cards for the renderer.

Usage: python podcast/build_audio.py podcast/episodes/ep01_en.json
Writes podcast/out/dialog.wav and podcast/web/timeline.json.

TTS engines (all run on CPU through sherpa-onnx):
  supertonic  Supertonic 3, English, 10 voices (0-4 female, 5-9 male)
  kokoro      Kokoro v1.1 Chinese+English (used for the Chinese episode)
"""
import json, os, re, sys, hashlib
from pathlib import Path
import numpy as np, soundfile as sf
import sherpa_onnx
import sfx

FPS = 30
SR = 24000
OUTRO = 3.0
ROOT = Path(__file__).parent
CACHE = ROOT / ".cache" / "tts"
OUT = ROOT / "out"
MODELS = Path(os.environ.get('TTS_MODELS', ROOT / '.cache'))
KOKORO = MODELS / 'kokoro-multi-lang-v1_1'
SUPERTONIC = MODELS / 'sherpa-onnx-supertonic-3-tts-int8-2026-05-11'

_engines = {}
def engine(name):
    if name not in _engines:
        if name == 'kokoro':
            K = str(KOKORO) + '/'
            cfg = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=K + 'model.onnx', voices=K + 'voices.bin', tokens=K + 'tokens.txt',
                    data_dir=K + 'espeak-ng-data', dict_dir=K + 'dict',
                    lexicon=K + 'lexicon-us-en.txt,' + K + 'lexicon-zh.txt'), num_threads=4),
                rule_fsts=K + 'date-zh.fst,' + K + 'phone-zh.fst,' + K + 'number-zh.fst')
        else:
            P = str(SUPERTONIC) + '/'
            cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
                supertonic=sherpa_onnx.OfflineTtsSupertonicModelConfig(
                    duration_predictor=P + 'duration_predictor.int8.onnx', text_encoder=P + 'text_encoder.int8.onnx',
                    vector_estimator=P + 'vector_estimator.int8.onnx', vocoder=P + 'vocoder.int8.onnx',
                    tts_json=P + 'tts.json', unicode_indexer=P + 'unicode_indexer.bin', voice_style=P + 'voice.bin'),
                num_threads=4))
        _engines[name] = sherpa_onnx.OfflineTts(cfg)
    return _engines[name]


# spoken forms for the TTS: "A.I." makes it pause between the letters, so say it as one word
SAY = {'A.I.': 'Ay Eye', 'AI': 'Ay Eye'}


def synth(text, eng, sid, speed, steps=10):
    for k, v in SAY.items():
        text = re.sub(r'(?<![\w.])' + re.escape(k) + r'(?![\w])', v, text)
    key = hashlib.sha1(f"{eng}|{text}|{sid}|{speed}|{steps}".encode()).hexdigest()[:16]
    p = CACHE / f"{key}.wav"
    if not p.exists():
        if eng == 'kokoro':
            a = engine(eng).generate(text, sid=sid, speed=speed)
        else:
            g = sherpa_onnx.GenerationConfig(); g.sid = sid; g.num_steps = steps; g.speed = speed; g.extra["lang"] = "en"
            a = engine(eng).generate(text, g)
        x = np.array(a.samples, dtype=np.float32)
        if a.sample_rate != SR:
            x = np.interp(np.arange(0, len(x), a.sample_rate / SR), np.arange(len(x)), x).astype(np.float32)
        sf.write(p, x, SR)
    x, sr = sf.read(p, dtype='float32')
    # trim silence, keep a few ms of breath
    idx = np.where(np.abs(x) > 0.01)[0]
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


def chunks_zh(text, maxlen=17):
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


def chunks_en(text, maxlen=44):
    """Split an English line into subtitle chunks at punctuation, then by words."""
    out = []
    for part in re.split(r'(?<=[,.?!;:])\s+', text.strip()):
        words, cur = part.split(), ''
        for w in words:
            if cur and len(cur) + 1 + len(w) > maxlen:
                out.append(cur); cur = w
            else:
                cur = (cur + ' ' + w).strip()
        if cur:
            if out and len(out[-1]) + len(cur) < 22 and not out[-1].endswith(('.', '?', '!')):
                out[-1] += ' ' + cur
            else:
                out.append(cur)
    return out




def main():
    CACHE.mkdir(parents=True, exist_ok=True); OUT.mkdir(exist_ok=True)
    ep = json.loads(Path(sys.argv[1]).read_text())
    hosts = ep['hosts']
    en = ep.get('lang', 'zh') == 'en'
    speed0 = 1.05 if en else 1.15
    t = 0.0
    intro = 3.2
    placed, effects = [], []
    for row in ep['lines']:
        if row[0] == 'SFX':
            kind, opt = row[1], row[2]
            effects.append({'kind': kind, 'start': t + 0.1, 'dur': opt.get('dur', 3.0), 'gain': opt.get('gain', 1.0)})
            if kind == 'sting':
                intro = t + 0.1 + opt.get('dur', 3.0) - 0.5
                t = intro - 0.3
            continue
        spk, text, opt = row
        h = hosts[spk]
        x = synth(text, h.get('tts', 'kokoro'), h['voice'], round(opt.get('speed', 1.0) * speed0, 3))
        t += opt.get('gap', 0.3)
        placed.append((spk, text, opt, t, x))
        t += len(x) / SR
        if opt.get('laugh'):
            d = 1.0 + 1.6 * opt['laugh']
            effects.append({'kind': 'laugh', 'start': t - 0.15, 'dur': d, 'gain': 0.55 + 0.45 * opt['laugh'], 'after': spk})
            t += d * 0.6
        if opt.get('applause'):
            d = opt['applause']
            effects.append({'kind': 'applause', 'start': t - 0.2, 'dur': d, 'gain': 1.0})
            t += d * 0.55
    total = t + OUTRO + 1.0
    N = int(total * SR) + 3 * SR
    tracks = {k: np.zeros(N, np.float32) for k in hosts}
    lines = []
    for spk, text, opt, st, x in placed:
        i = int(st * SR)
        tracks[spk][i:i + len(x)] += x
        end = st + len(x) / SR
        L = {'spk': spk, 'start': round(st, 3), 'end': round(end, 3), 'text': text, 'emo': opt.get('emo'),
             'gest': opt.get('gest'), 'card': opt.get('card'), 'toCamera': bool(opt.get('toCamera')), 'laugh': opt.get('laugh', 0)}
        shown = opt.get('sub', text.replace('Change dot org', 'Change.org').replace('A.I.', 'AI'))
        cs = chunks_en(shown) if en else chunks_zh(shown)
        lens = np.array([len(c) for c in cs], float)
        edges = st + np.concatenate([[0], np.cumsum(lens) / lens.sum()]) * (end - st)
        L['subs'] = [[round(edges[k], 3), round(edges[k + 1], 3), c] for k, c in enumerate(cs)]
        lines.append(L)
        if opt.get('back'):
            other = next(k for k in hosts if k != spk)
            oh = hosts[other]
            b = synth(opt['back'], oh.get('tts', 'kokoro'), oh['voice'], 1.0) * 0.45
            bt = st + (end - st) * 0.5
            j = int(bt * SR)
            tracks[other][j:j + len(b)] += b
            L['back'] = {'spk': other, 'start': round(bt, 3), 'end': round(bt + len(b) / SR, 3)}
    voices = sum(tracks.values())
    fx = np.zeros(N, np.float32)
    for e in effects:
        if e['kind'] == 'sting':
            y = sfx.sting(e['dur'])
        elif e['kind'] == 'applause':
            y = sfx.applause(e['dur'], e['gain'])
        else:
            y = sfx.laugh(e['dur'], e['gain'])
        i = int(e['start'] * SR); L_ = min(len(y), N - i)
        fx[i:i + L_] += y[:L_]
        e['end'] = round(e['start'] + e['dur'], 3); e['start'] = round(e['start'], 3)
    rng = np.random.default_rng(1)
    room = np.convolve(rng.normal(0, 1, N).astype(np.float32), np.ones(40) / 40, 'same') * 0.0025
    mix = voices / (np.abs(voices).max() + 1e-9) * 0.85 + fx * 0.8 + room
    mix = np.tanh(mix * 1.1) / np.tanh(1.1)
    sf.write(OUT / 'dialog.wav', mix[:int(total * SR)], SR)
    mouths = {k: np.round(mouth_track(v[:int(total * SR)]), 3).tolist() for k, v in tracks.items()}
    tl = {'fps': FPS, 'duration': round(total, 3), 'intro': round(intro, 3), 'outro': OUTRO, 'title': ep['title'],
          'show': ep.get('show'), 'paper': ep['paper'], 'cards': ep.get('cards', {}), 'hosts': hosts, 'lines': lines, 'sfx': effects, 'mouth': mouths}
    (ROOT / 'web' / 'timeline.json').write_text(json.dumps(tl, ensure_ascii=False))
    print(f"duration {total:.1f}s, {len(lines)} lines, {len(effects)} effects")


if __name__ == '__main__':
    main()
