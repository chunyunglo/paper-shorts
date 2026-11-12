"""Find where each narration line starts and ends in one recording of the whole narration, by
transcribing it (faster-whisper, on the CPU) and matching the transcript to the script text."""
from __future__ import annotations

import difflib
import re
import unicodedata

import numpy as np

from .safelog import log

MODEL = "base"   # small and quick on a CPU; we only need where the words are, not a perfect transcript
_model = None


def _norm(text: str) -> str:
    """Letters, digits and CJK characters only, lowercased: what a transcript and the script share."""
    out = []
    for ch in unicodedata.normalize("NFKC", text).lower():
        if ch.isalnum():
            out.append(ch)
    return "".join(out)


def _words(audio: np.ndarray, sr: int, lang: str) -> list[tuple[str, float, float]]:
    global _model
    from faster_whisper import WhisperModel  # optional dependency: without it we fall back

    if _model is None:
        _model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    if sr != 16000:  # whisper wants 16 kHz
        n = int(audio.size * 16000 / sr)
        audio = np.interp(np.linspace(0, audio.size - 1, n), np.arange(audio.size), audio).astype(np.float32)
    segments, _ = _model.transcribe(audio, language=lang, word_timestamps=True, beam_size=1,
                                    condition_on_previous_text=False, vad_filter=False)
    return [(w.word, w.start, w.end) for seg in segments for w in (seg.words or [])]


def line_bounds(audio: np.ndarray, sr: int, lines: list[str], lang: str) -> list[tuple[float, float]] | None:
    """(start, end) in seconds of each line's speech, or None when the transcript doesn't match well enough."""
    try:
        words = _words(audio, sr, lang)
    except Exception as exc:  # no model, no package, bad audio: the caller falls back
        log(f"Alignment unavailable ({type(exc).__name__})")
        return None
    # one time per transcript character, spread evenly over its word
    heard, times = [], []
    for text, start, end in words:
        chars = _norm(text)
        for i, ch in enumerate(chars):
            heard.append(ch)
            times.append(start + (end - start) * (i + 0.5) / len(chars))
    script, owner = [], []
    for k, line in enumerate(lines):
        for ch in _norm(line):
            script.append(ch)
            owner.append(k)
    if not heard or not script:
        return None
    matcher = difflib.SequenceMatcher(None, script, heard, autojunk=False)
    at: dict[int, float] = {}
    for a, b, size in matcher.get_matching_blocks():
        for i in range(size):
            at[a + i] = times[b + i]
    bounds = []
    for k in range(len(lines)):
        idx = [i for i, o in enumerate(owner) if o == k]
        hit = [at[i] for i in idx if i in at]
        # every line must be clearly found: most of its characters heard, in order
        if not idx or len(hit) < max(2, 0.5 * len(idx)):
            return None
        bounds.append((min(hit), max(hit)))
    for (s0, e0), (s1, e1) in zip(bounds, bounds[1:]):
        if s1 < e0 - 0.05:  # lines overlap: the match went wrong
            return None
    return bounds
