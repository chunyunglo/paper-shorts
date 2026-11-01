"""Voice a saved concept-show script with Gemini multi-speaker TTS, a few turns per request.

python -m concept_show voice <show.json> <out.wav>

Gemini Flash-Lite TTS allows 10 requests a minute and 100 a day on this key, so lines are grouped into
chunks (both hosts in one request), requests are spaced at least PACE seconds apart, and the run stops
before sending more than MAX_REQUESTS. Each chunk's audio is cached by its text, so a rerun after a
failure only sends the chunks that are still missing. Never prints the key, URL or response body.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-lite-tts")
# One request can return at most 16,384 output tokens, roughly 10 minutes of audio, so a 13-20 minute
# episode needs 2-3 requests; 2000 characters is about 7 minutes of speech.
CHUNK_CHARS = int(os.environ.get("TTS_CHUNK_CHARS", "2000"))
PACE = float(os.environ.get("TTS_PACE_SECONDS", "8"))  # 10 requests a minute at most; stay under it
MAX_REQUESTS = int(os.environ.get("TTS_MAX_REQUESTS", "25"))
CACHE = Path(os.environ.get("TTS_CACHE", Path(__file__).resolve().parent.parent / "out" / "concept_show" / ".tts"))
SPEAKERS = {"K": "Kai", "A": "Anne"}  # ASCII labels for the request; the spoken names are in the text
GAP = 0.45  # seconds of silence between chunks


def chunks(lines: list[list]) -> list[list[tuple[str, str]]]:
    out, cur, n = [], [], 0
    for spk, text, *_ in lines:
        if cur and n + len(text) > CHUNK_CHARS:
            out.append(cur)
            cur, n = [], 0
        cur.append((spk, text))
        n += len(text)
    return out + ([cur] if cur else [])


def body(chunk: list[tuple[str, str]], hosts: dict, style: str = "") -> bytes:
    meta = lambda s: {"speaker": SPEAKERS[s], **({"style": style} if style else {})}
    parts = [{"text": t, "speech_metadata": meta(s)} for s, t in chunk]
    voices = [{"speaker": SPEAKERS[k], "voiceConfig": {"voice": hosts[k].get("voice_id") or hosts[k]["voice"]}}
              for k in ("K", "A")]
    return json.dumps({"contents": [{"role": "user", "parts": parts}],
                       "generationConfig": {"responseModalities": ["AUDIO"],
                                            "speechConfig": {"multiSpeakerVoiceConfig": {
                                                "speakerVoiceConfigs": voices}}}},
                      ensure_ascii=False).encode()


def _quota(err: urllib.error.HTTPError) -> tuple[str, int]:
    try:
        e = json.load(err).get("error", {})
    except Exception:
        return "", 0
    details = e.get("details", [])
    if err.code == 400:  # say why (e.g. a voice the multi-speaker mode rejects); the message never holds the key
        return re.sub(r"[^\w .,:;'()/-]", "", str(e.get("message", "")))[:200], 0
    quota, wait = "", 0
    for d in details:
        for v in d.get("violations", []):
            quota = quota or re.sub(r"[^A-Za-z]", "", str(v.get("quotaId", "")))[:80]
        m = re.fullmatch(r"(\d+)(?:\.\d+)?s", str(d.get("retryDelay", "")))
        wait = int(m.group(1)) + 2 if m else wait
    return quota, min(wait, 90)


class Budget:
    def __init__(self) -> None:
        self.sent, self.last = 0, 0.0

    def request(self, data: bytes) -> bytes:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
        for attempt in range(3):
            if self.sent >= MAX_REQUESTS:
                sys.exit(f"Stopped at the request cap ({MAX_REQUESTS}); rerun to continue from the cache")
            time.sleep(max(0.0, self.last + PACE - time.time()))
            self.last, self.sent = time.time(), self.sent + 1
            req = urllib.request.Request(url, data, {"x-goog-api-key": os.environ["GEMINI_API_KEY"],
                                                     "Content-Type": "application/json"})
            try:
                d = json.load(urllib.request.urlopen(req, timeout=300))
                return base64.b64decode(d["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
            except urllib.error.HTTPError as e:
                quota, wait = _quota(e)
                if (e.code != 429 and e.code < 500) or "PerDay" in quota or attempt == 2:
                    sys.exit(f"Gemini TTS failed (status {e.code}{': ' + quota if quota else ''}) "
                             f"after {self.sent} requests")
                time.sleep(max(wait, 20))
        raise AssertionError


def resolve_voices(hosts: dict) -> None:
    """Look up each host's voice by name in the voice library (prebuilt and Extended Voice Library) and
    store its id. A read-only list call; prints only the id, language and gender it found."""
    for h in hosts.values():
        url = ("https://generativelanguage.googleapis.com/v1beta/voices?page_size=50&search="
               + urllib.parse.quote(h["voice"]))
        req = urllib.request.Request(url, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
        try:
            found = json.load(urllib.request.urlopen(req, timeout=60)).get("voices", [])
        except urllib.error.HTTPError as e:
            sys.exit(f"Voice lookup failed (status {e.code})")
        name = h["voice"].lower()
        match = [v for v in found if name in (str(v.get("displayName", "")) + " " + str(v.get("id", ""))
                                              + " " + str(v.get("name", ""))).lower()]
        if not match:
            print(f"Search for {h['voice']!r} returned {len(found)} voices:", flush=True)
            for v in found[:25]:
                print("  ", {k: v.get(k) for k in ("id", "name", "displayName", "languageCode", "gender")}, flush=True)
            sys.exit(f"No voice named {h['voice']!r} in the voice library")
        v = match[0]
        h["voice_id"] = v.get("id") or v.get("name", "").split("/")[-1]
        print(f"Voice {h['voice']}: {h['voice_id']} ({v.get('languageCode', '?')}, {v.get('gender', '?')})",
              flush=True)


def frames(wav_bytes: bytes) -> tuple[bytes, tuple]:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.readframes(w.getnframes()), (w.getnchannels(), w.getsampwidth(), w.getframerate())


def main(show_path: str, out_path: str) -> None:
    show = json.loads(Path(show_path).read_text(encoding="utf-8"))
    # Voices and style always come from the current cast.json, so a saved script can be re-voiced after a change
    cast = json.loads((Path(__file__).resolve().parent / "cast.json").read_text(encoding="utf-8"))
    show["style"] = cast.get("style", "")
    for k, h in show["hosts"].items():
        h["voice"] = cast["hosts"][k]["voice"]
    resolve_voices(show["hosts"])
    rows = [r for r in show["lines"] if r[0] in SPEAKERS]
    if a := os.environ.get("TTS_SAMPLE_LINES"):  # voice only the first N lines, to try a voice change cheaply
        rows = rows[:int(a)]
    parts = chunks(rows)
    CACHE.mkdir(parents=True, exist_ok=True)
    todo = sum(1 for c in parts if not (CACHE / f"{_key(c, show['hosts'], show.get('style', ''))}.wav").exists())
    print(f"{len(parts)} chunks, {todo} to voice with {MODEL}", flush=True)
    if todo > MAX_REQUESTS:
        sys.exit(f"{todo} requests needed, more than the cap of {MAX_REQUESTS}; raise TTS_CHUNK_CHARS")
    budget, pcm, fmt = Budget(), [], None
    for i, c in enumerate(parts):
        p = CACHE / f"{_key(c, show['hosts'], show.get('style', ''))}.wav"
        if not p.exists():
            p.write_bytes(budget.request(body(c, show["hosts"], show.get("style", ""))))
            print(f"voiced chunk {i + 1}/{len(parts)}", flush=True)
        f, fmt_i = frames(p.read_bytes())
        fmt = fmt or fmt_i
        if fmt_i != fmt:
            sys.exit("Chunks came back in different audio formats")
        pcm += [f, b"\0" * int(GAP * fmt[2]) * fmt[0] * fmt[1]]
    with wave.open(out_path, "wb") as w:
        w.setnchannels(fmt[0])
        w.setsampwidth(fmt[1])
        w.setframerate(fmt[2])
        w.writeframes(b"".join(pcm))
    print(f"Wrote {out_path} from {len(parts)} chunks; {budget.sent} Gemini requests this run", flush=True)


def _key(chunk, hosts, style="") -> str:
    return hashlib.sha1(body(chunk, hosts, style) + MODEL.encode()).hexdigest()[:16]
