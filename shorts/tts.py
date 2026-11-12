"""Voiceover: synthesize each subtitle line, then lay them on one timeline.

Providers:
  gemini  Gemini 3.8 Flash TTS (needs GEMINI_API_KEY). Default when the key exists.
  google  Google Cloud Text-to-Speech (needs GOOGLE_TTS_API_KEY). Fallback, or default without a Gemini key.
  edge    Microsoft Edge neural voices via the edge-tts package (no key). Fallback.
  silent  Silence sized to the text, for offline tests.
"""
from __future__ import annotations

import asyncio
import base64
import io
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import brand, config
from .safelog import ApiError, http, log

SR = 24000
GAP_LINE = 0.07
PAD_SCENE_START = 0.04
PAD_SCENE_END = 0.16


@dataclass
class LineTiming:
    start: float
    end: float


@dataclass
class SceneTiming:
    start: float
    end: float
    lines: list[LineTiming] = field(default_factory=list)


def _wav_to_array(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data)) as w:
        if w.getframerate() != SR or w.getnchannels() != 1:
            raise RuntimeError("Unexpected TTS audio format")
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def _trim(a: np.ndarray, thresh: float = 0.01) -> np.ndarray:
    idx = np.flatnonzero(np.abs(a) > thresh)
    if idx.size == 0:
        return a
    lo, hi = max(idx[0] - int(0.03 * SR), 0), min(idx[-1] + int(0.06 * SR), a.size)
    return a[lo:hi]


# Chosen by the owner from the voice samples (2026-10-25): zh #07 Chirp3 Charon, en #13 Chirp3 Aoede.
DEFAULT_VOICES = {"zh": "cmn-CN-Chirp3-HD-Charon", "en": "en-US-Chirp3-HD-Aoede", "pt": "pt-BR-Chirp3-HD-Charon"}
# Chosen by the owner (2026-10-28): Kai's voice, shared by the shorts and the podcast host, in every language.
GEMINI_MODEL = "gemini-3.8-flash-tts"
GEMINI_VOICE = "Achird"
# Used if the chosen voice fails (Edge TTS is an unofficial service and may break).
GOOGLE_FALLBACK = {"zh": "cmn-TW-Wavenet-C", "en": "en-US-Neural2-J", "pt": "pt-BR-Neural2-B"}
EDGE_FALLBACK = {"zh": "zh-TW-YunJheNeural", "en": "en-US-AriaNeural", "pt": "pt-BR-AntonioNeural"}


def rate() -> float:
    return float(config.env("TTS_RATE", "1.0"))  # normal speed; 1.1 and 1.25 felt rushed to the owner


def synth_google(text: str, voice: str) -> np.ndarray:
    body = {
        "input": {"text": text},
        "voice": {"languageCode": "-".join(voice.split("-")[:2]), "name": voice},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": SR, "speakingRate": rate()},
    }
    resp = http("google-tts", "synthesize", "POST",
                "https://texttospeech.googleapis.com/v1/text:synthesize",
                headers={"X-Goog-Api-Key": config.require("GOOGLE_TTS_API_KEY")}, json=body)
    return _wav_to_array(base64.b64decode(resp.json()["audioContent"]))


def synth_gemini(text: str, voice: str) -> np.ndarray:
    body = {
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {"voice": voice}}},
    }
    model = config.env("GEMINI_TTS_MODEL", GEMINI_MODEL)
    for attempt in range(5):  # per-minute rate limits answer 429; wait them out
        try:
            resp = http("gemini-tts", "generate", "POST",
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                        headers={"x-goog-api-key": config.require("GEMINI_API_KEY")}, json=body)
            break
        except ApiError as exc:
            if exc.status != 429 or attempt == 4:
                raise
            time.sleep(15 * (attempt + 1))
    audio = _wav_to_array(base64.b64decode(resp.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]))
    return _tempo(audio, rate())


def _tempo(a: np.ndarray, factor: float) -> np.ndarray:
    """Speed up without changing pitch (Gemini has no speaking-rate setting)."""
    if abs(factor - 1) < 0.01:
        return a
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "a.wav", Path(tmp) / "b.wav"
        write_wav(src, a)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-filter:a", f"atempo={factor}",
                        "-ac", "1", "-ar", str(SR), "-sample_fmt", "s16", str(dst)], check=True)
        return _wav_to_array(dst.read_bytes())


def synth_edge(text: str, voice: str) -> np.ndarray:
    import edge_tts

    pct = f"+{round((rate() - 1) * 100)}%"
    with tempfile.TemporaryDirectory() as tmp:
        mp3, wav = Path(tmp) / "a.mp3", Path(tmp) / "a.wav"
        asyncio.run(edge_tts.Communicate(text, voice, rate=pct).save(str(mp3)))
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(mp3), "-ac", "1",
                        "-ar", str(SR), "-sample_fmt", "s16", str(wav)], check=True)
        return _wav_to_array(wav.read_bytes())


def synth_silent(text: str, voice: str = "") -> np.ndarray:
    per_char = 0.17 if any("\u4e00" <= ch <= "\u9fff" for ch in text) else 0.055
    return np.zeros(int(SR * max(0.6, len(text) * per_char)), dtype=np.float32)


def choose(lang: str) -> tuple[str, str]:
    """(provider, voice) for a language. Voice names ending in 'Neural' are Edge voices."""
    if config.env("TTS_PROVIDER") == "silent":
        return "silent", ""
    if config.env("GEMINI_API_KEY") and config.env("TTS_PROVIDER", "gemini") == "gemini":
        return "gemini", config.env("GEMINI_VOICE", GEMINI_VOICE)
    voice = config.env(f"TTS_VOICE_{lang.upper()}", DEFAULT_VOICES[lang])
    if voice.endswith("Neural"):
        return "edge", voice
    if config.env("GOOGLE_TTS_API_KEY"):
        return "google", voice
    return "edge", EDGE_FALLBACK[lang]


SYNTH = {"gemini": synth_gemini, "google": synth_google, "edge": synth_edge, "silent": synth_silent}


def voiceover(scenes: list[list[str]], out_wav: Path, lang: str) -> tuple[list[SceneTiming], float]:
    """scenes: the spoken lines of each scene. Writes a mono wav, returns timings in seconds.
    If the chosen voice fails, the whole video is redone in a fallback voice so it stays consistent."""
    name, voice = choose(lang)
    try:
        return _voiceover(scenes, out_wav, lang, name, voice)
    except Exception as exc:
        if name == "silent":
            raise
        fb = ("google", GOOGLE_FALLBACK[lang]) if config.env("GOOGLE_TTS_API_KEY") else ("edge", EDGE_FALLBACK[lang])
        if fb == (name, voice):
            raise
        log(f"TTS ({lang}): {voice} failed ({exc}); falling back to {fb[1]}")
        return _voiceover(scenes, out_wav, lang, *fb)


# Lines already spoken in this run: a re-render after the visual check repeats most of them, and
# re-requesting every line used up Gemini's daily quota (Nov 12, when the fallback voice was used).
_spoken: dict[tuple[str, str, str], np.ndarray] = {}
# The voice each language was actually spoken in (after any fallback), for episode.json.
used: dict[str, str] = {}


def _sentence(text: str, lang: str) -> str:
    """End each line as a sentence, so the voice pauses where the subtitles change."""
    text = text.strip()
    if text and text[-1] in "。！？!?.…":
        return text
    return text.rstrip("，、,;；：:") + ("。" if lang == "zh" else ".")


def split_at_pauses(a: np.ndarray, weights: list[float], frame: float = 0.01, min_pause: float = 0.08,
                    thresh: float = 0.01) -> list[np.ndarray] | None:
    """Cut one recording of several lines at the pauses between them. weights: each line's length
    (characters or words), to know roughly where each cut should be. None if the pauses can't be found."""
    n = len(weights)
    if n == 1:
        return [a]
    hop = int(SR * frame)
    frames = a[: a.size // hop * hop].reshape(-1, hop)
    loud = np.sqrt((frames ** 2).mean(axis=1)) > thresh
    voiced = np.flatnonzero(loud)
    if voiced.size == 0:
        return None
    first, last = voiced[0], voiced[-1]
    pauses, i = [], first
    while i <= last:  # runs of quiet frames inside the speech
        if not loud[i]:
            j = i
            while j <= last and not loud[j]:
                j += 1
            if (j - i) * frame >= min_pause:
                pauses.append((i, j))
            i = j
        else:
            i += 1
    if len(pauses) < n - 1:
        return None
    total, cum, cuts, prev = sum(weights), 0.0, [], first
    span = last - first
    for k in range(n - 1):
        cum += weights[k]
        want = first + span * cum / total
        window = max(80, 0.35 * span * weights[k] / total)  # frames: 0.8 s or a third of the line
        options = [(abs((s + e) / 2 - want) - 0.5 * (e - s), s, e) for s, e in pauses
                   if s > prev and abs((s + e) / 2 - want) <= window]
        if not options:
            return None
        _, s, e = min(options)
        cuts.append(((s + e) // 2) * hop)
        prev = e
    edges = [0] + cuts + [a.size]
    return [a[edges[k]:edges[k + 1]] for k in range(n)]


def _voiceover(scenes: list[list[str]], out_wav: Path, lang: str, name: str, voice: str):
    log(f"TTS ({lang}): {name} {voice}")
    label = f"{name} {voice}".strip()

    def synth(text: str) -> np.ndarray:
        key = (name, voice, text)
        if key not in _spoken:
            _spoken[key] = SYNTH[name](text, voice)
        return _spoken[key]

    if name == "gemini":
        # one request for the whole narration (Gemini's daily request quota ran out on Nov 12 at one
        # request per line), cut back into lines at the pauses; per-line requests only if that fails
        flat = [_sentence(x, lang) for lines in scenes for x in lines]
        whole = synth("\n".join(flat))
        parts = split_at_pauses(whole, [len(x) if lang == "zh" else len(x.split()) for x in flat])
        if parts is None:
            log(f"TTS ({lang}): could not cut the narration at its pauses; voicing line by line")
        else:
            it = iter(parts)
            pre = {(name, voice, x): next(it) for lines in scenes for x in lines}
            _spoken.update({k: v for k, v in pre.items() if k not in _spoken})
    chunks: list[np.ndarray] = []
    timings: list[SceneTiming] = []
    t = 0.0

    def add(a: np.ndarray) -> None:
        nonlocal t
        chunks.append(a)
        t += a.size / SR

    def silence(sec: float) -> None:
        add(np.zeros(int(SR * sec), dtype=np.float32))

    for lines in scenes:
        scene = SceneTiming(start=t, end=t)
        silence(PAD_SCENE_START)
        for i, text in enumerate(lines):
            if i:
                silence(GAP_LINE)
            start = t
            add(_trim(synth(text)))
            scene.lines.append(LineTiming(start, t))
        silence(PAD_SCENE_END)
        scene.end = t
        timings.append(scene)

    voice = np.concatenate(chunks)
    mixed = voice * 0.95 + music_bed(voice.size, [s.start for s in timings[1:]])
    # The fixed outro chime is appended; timings stay relative to the narration.
    write_wav(out_wav, brand.wrap_audio(mixed, SR))
    used[lang] = label
    return timings, t


def write_wav(path: Path, a: np.ndarray) -> None:
    pcm = (np.clip(a, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def music_bed(n: int, cues: list[float]) -> np.ndarray:
    """A quiet generated pad (Am-F-C-G) plus a soft tick at each scene change. No licensed music."""
    t = np.arange(n) / SR
    chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (196.0, 261.63, 329.63), (196.0, 246.94, 293.66)]
    bar = 4.0
    out = np.zeros(n, dtype=np.float32)
    for k in range(int(n / SR / bar) + 1):
        lo, hi = int(k * bar * SR), min(int((k + 1) * bar * SR), n)
        if lo >= n:
            break
        seg = t[lo:hi] - k * bar
        env = np.minimum(1, seg / 0.8) * np.minimum(1, (bar - seg) / 0.8)
        tone = sum(np.sin(2 * np.pi * f * t[lo:hi]) + 0.3 * np.sin(4 * np.pi * f * t[lo:hi])
                   for f in chords[k % 4])
        out[lo:hi] += (0.012 * env * tone).astype(np.float32)
    for c in cues:
        lo = int(c * SR)
        m = min(int(0.25 * SR), n - lo)
        if m <= 0:
            continue
        s = np.arange(m) / SR
        out[lo:lo + m] += (0.05 * np.exp(-s * 18) * np.sin(2 * np.pi * 880 * s)).astype(np.float32)
    fade = min(int(1.5 * SR), n)
    out[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    return out
