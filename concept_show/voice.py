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
TURN_GAP = 0.3  # between single turns, when each turn is its own request


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
    vid = lambda k: hosts[k].get("voice_id", hosts[k]["voice"])
    if any(h.get("designed") for h in hosts.values()):  # one turn, one voice (designed voices can't be mixed)
        (spk, text), = chunk
        parts = [{"text": text, **({"speech_metadata": {"style": style}} if style else {})}]
        speech = {"voiceConfig": {"voice": vid(spk)}}
    else:
        meta = lambda s: {"speaker": SPEAKERS[s], **({"style": style} if style else {})}
        parts = [{"text": t, "speech_metadata": meta(s)} for s, t in chunk]
        speech = {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": [
            {"speaker": SPEAKERS[k], "voiceConfig": {"voice": vid(k)}} for k in ("K", "A")]}}
    return json.dumps({"contents": [{"role": "user", "parts": parts}],
                       "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": speech}},
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


def _library() -> list[dict]:
    """Every voice in the library (prebuilt, Extended Voice Library, and this project's own). Read-only."""
    voices, token = [], ""
    for _ in range(10):
        url = "https://generativelanguage.googleapis.com/v1beta/voices?page_size=1000" + (
            "&page_token=" + urllib.parse.quote(token) if token else "")
        req = urllib.request.Request(url, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
        try:
            d = json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            sys.exit(f"Voice list failed (status {e.code})")
        voices += d.get("voices", [])
        token = d.get("nextPageToken") or d.get("next_page_token") or ""
        if not token:
            break
    return voices


def _f(v: dict, *names: str) -> str:
    return str(next((v[n] for n in names if v.get(n)), ""))


PREVIEWS = Path(os.environ.get("TTS_PREVIEWS", CACHE.parent / "previews"))


def _api(method: str, path: str, payload: dict | None = None) -> dict:
    url = "https://generativelanguage.googleapis.com/v1beta/" + path
    req = urllib.request.Request(url, json.dumps(payload, ensure_ascii=False).encode() if payload else None,
                                 {"x-goog-api-key": os.environ["GEMINI_API_KEY"], "Content-Type": "application/json"},
                                 method=method)
    try:
        return json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        why, _ = _quota(e)
        sys.exit(f"Voices API {method} failed (status {e.code}{': ' + why if why else ''})")


def designed_voice(name: str, spec: dict) -> str:
    """A voice designed from spec["design"] and stored in the Gemini project (one-year lifetime). Reused by
    display name, so it is designed once and every later run sounds the same."""
    display = f"{name} {hashlib.sha1(spec['design'].encode()).hexdigest()[:8]}"
    listing = _api("GET", "voices?type=prompted&page_size=200")
    for v in listing.get("voices", []):
        if _f(v, "displayName", "display_name") == display:
            print(f"{name}: designed voice {_f(v, 'id')} (reused)", flush=True)
            return _f(v, "id")
    made = _api("POST", "voices", {"store": True, "voice": {
        "model": MODEL, "type": "prompted", "display_name": display, "gender": spec.get("gender", "female"),
        "language_code": spec.get("language", "zh-TW"), "prompted": {"input": spec["design"]}}})
    vid = _f(made, "id")
    sample = (made.get("sample_audio") or made.get("sampleAudio") or {}).get("data")
    if sample:
        PREVIEWS.mkdir(parents=True, exist_ok=True)
        (PREVIEWS / f"voice-preview-{name}.wav").write_bytes(base64.b64decode(sample))
    print(f"{name}: designed voice {vid} (new)", flush=True)
    return vid


def resolve_voices(hosts: dict) -> None:
    """A host's voice is a prebuilt name ("Achird") or a filter {"language": "TW", "gender": "female",
    "pick": 0}: the pick-th matching library voice, in id order, so every run picks the same one.
    Prints only ids, languages and genders."""
    lib = None
    for h in hosts.values():
        v = h["voice"]
        if isinstance(v, str):
            h["voice_id"] = v
            continue
        if "design" in v:
            h["voice_id"], h["designed"] = designed_voice(h["name"], v), True
            continue
        lib = lib if lib is not None else _library()
        match = sorted((x for x in lib
                        if v["language"].lower() in _f(x, "languageCode", "language_code").lower()
                        and _f(x, "gender").lower().startswith(v["gender"].lower())),
                       key=lambda x: _f(x, "id", "name"))
        if len(match) <= v.get("pick", 0):
            langs = sorted({_f(x, "languageCode", "language_code") for x in lib})
            sys.exit(f"{len(match)} library voices match {v}; {len(lib)} voices in all, languages: "
                     + ", ".join(langs[:80]))
        x = match[v.get("pick", 0)]
        h["voice_id"] = _f(x, "id", "name").split("/")[-1]
        print(f"{h['name']}: voice {h['voice_id']} ({_f(x, 'languageCode', 'language_code')}, "
              f"{_f(x, 'gender')}); {len(match)} voices matched", flush=True)


def frames(wav_bytes: bytes) -> tuple[bytes, tuple]:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.readframes(w.getnframes()), (w.getnchannels(), w.getsampwidth(), w.getframerate())


def main(show_path: str, out_path: str) -> None:
    show = json.loads(Path(show_path).read_text(encoding="utf-8"))
    # Voices and style always come from the current cast.json, so a saved script can be re-voiced after a change
    cast = json.loads((Path(__file__).resolve().parent / "cast.json").read_text(encoding="utf-8"))
    show["style"] = cast.get("style", "")
    renames = {show.get("show", ""): cast["show"]}
    for k, h in show["hosts"].items():
        renames[h["name"]] = cast["hosts"][k]["name"]
        h.update(voice=cast["hosts"][k]["voice"], name=cast["hosts"][k]["name"])
    renames = {a: b for a, b in renames.items() if a and a != b}
    if renames:  # a script saved before a rename still says the old names; speak the current ones
        print("Renaming in the saved script: " + ", ".join(f"{a} -> {b}" for a, b in renames.items()), flush=True)
        for r in show["lines"]:
            for a, b in renames.items():
                r[1] = r[1].replace(a, b)
    resolve_voices(show["hosts"])
    rows = [r for r in show["lines"] if r[0] in SPEAKERS]
    if a := os.environ.get("TTS_SAMPLE_LINES"):  # voice only the first N lines, to try a voice change cheaply
        rows = rows[:int(a)]
    # Designed voices cannot share a multi-speaker request, so each turn is its own request
    per_turn = any(h.get("designed") for h in show["hosts"].values())
    parts = [[(r[0], r[1])] for r in rows] if per_turn else chunks(rows)
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
        pcm += [f, b"\0" * int((TURN_GAP if per_turn else GAP) * fmt[2]) * fmt[0] * fmt[1]]
    with wave.open(out_path, "wb") as w:
        w.setnchannels(fmt[0])
        w.setsampwidth(fmt[1])
        w.setframerate(fmt[2])
        w.writeframes(b"".join(pcm))
    print(f"Wrote {out_path} from {len(parts)} chunks; {budget.sent} Gemini requests this run", flush=True)


def _key(chunk, hosts, style="") -> str:
    return hashlib.sha1(body(chunk, hosts, style) + MODEL.encode()).hexdigest()[:16]
