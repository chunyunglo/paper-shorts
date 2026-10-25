"""Render the same narration in several voices so the owner can pick one by ear."""
from __future__ import annotations

import subprocess

from .config import OUT
from .safelog import log
from .tts import synth_edge, synth_google, write_wav

TEXT = {
    "zh": ("2023年，請願網站 Change.org 加入了 AI 協助撰寫請願的工具。"
           "研究者分析了使用者寫的請願書，結果發現，寫法明顯改變，但成效並沒有變好。"),
    "en": ("In 2023, the petition site Change.org added an AI writing tool. Researchers analyzed "
           "the petitions people wrote, and found the writing changed a lot, but the results didn't improve."),
    "pt": ("Em 2023, o site de petições Change.org lançou uma ferramenta de IA para escrever petições. "
           "Os pesquisadores analisaram os textos e descobriram que a escrita mudou muito, mas os resultados não melhoraram."),
}

VOICES = [
    ("google", "cmn-TW-Wavenet-A", "台灣 女聲 A（目前使用）"),
    ("google", "cmn-TW-Wavenet-B", "台灣 男聲 B"),
    ("google", "cmn-TW-Wavenet-C", "台灣 男聲 C"),
    ("google", "cmn-CN-Chirp3-HD-Aoede", "Chirp3 HD 女聲 Aoede（較自然，口音偏中國）"),
    ("google", "cmn-CN-Chirp3-HD-Leda", "Chirp3 HD 女聲 Leda"),
    ("google", "cmn-CN-Chirp3-HD-Puck", "Chirp3 HD 男聲 Puck"),
    ("google", "cmn-CN-Chirp3-HD-Charon", "Chirp3 HD 男聲 Charon"),
    ("edge", "zh-TW-HsiaoChenNeural", "Edge 台灣 女聲 曉臻"),
    ("edge", "zh-TW-HsiaoYuNeural", "Edge 台灣 女聲 曉雨"),
    ("edge", "zh-TW-YunJheNeural", "Edge 台灣 男聲 雲哲"),
    ("google", "en-US-Neural2-F", "English female Neural2-F (current)"),
    ("google", "en-US-Neural2-J", "English male Neural2-J"),
    ("google", "en-US-Chirp3-HD-Aoede", "English female Chirp3 HD Aoede"),
    ("google", "en-US-Chirp3-HD-Leda", "English female Chirp3 HD Leda"),
    ("google", "en-US-Chirp3-HD-Puck", "English male Chirp3 HD Puck"),
    ("google", "en-US-Chirp3-HD-Charon", "English male Chirp3 HD Charon"),
    ("edge", "en-US-AriaNeural", "Edge English female Aria"),
    ("edge", "en-US-AndrewNeural", "Edge English male Andrew"),
    ("google", "pt-BR-Chirp3-HD-Aoede", "Português feminina Chirp3 HD Aoede"),
    ("google", "pt-BR-Chirp3-HD-Leda", "Português feminina Chirp3 HD Leda"),
    ("google", "pt-BR-Chirp3-HD-Kore", "Português feminina Chirp3 HD Kore"),
    ("google", "pt-BR-Chirp3-HD-Puck", "Português masculina Chirp3 HD Puck"),
    ("google", "pt-BR-Chirp3-HD-Charon", "Português masculina Chirp3 HD Charon"),
    ("google", "pt-BR-Chirp3-HD-Fenrir", "Português masculina Chirp3 HD Fenrir"),
    ("google", "pt-BR-Neural2-A", "Português feminina Neural2-A"),
    ("google", "pt-BR-Neural2-B", "Português masculina Neural2-B"),
    ("edge", "pt-BR-FranciscaNeural", "Edge Português feminina Francisca"),
    ("edge", "pt-BR-AntonioNeural", "Edge Português masculina Antonio"),
]


def lang_of(voice: str) -> str:
    return "zh" if voice.startswith(("cmn", "zh")) else voice[:2]


def render_all(langs: list[str] | None = None) -> None:
    out = OUT / "voices"
    out.mkdir(parents=True, exist_ok=True)
    langs = langs or list(TEXT)
    index = ["# 聲音試聽 Voice samples", ""] + [f"{l}: {TEXT[l]}\n" for l in langs]
    picked = [v for v in VOICES if lang_of(v[1]) in langs]
    for n, (prov, voice, label) in enumerate(picked, 1):
        text = TEXT[lang_of(voice)]
        try:
            audio = (synth_google if prov == "google" else synth_edge)(text, voice)
        except Exception as exc:
            log(f"{voice}: failed ({exc})")
            index.append(f"- {n:02d} {label} `{voice}`: 無法產生")
            continue
        wav = out / f"{n:02d}.wav"
        write_wav(wav, audio)
        mp3 = out / f"{n:02d}-{voice}.mp3"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-b:a", "128k", str(mp3)], check=True)
        wav.unlink()
        index.append(f"- {n:02d} {label} `{voice}`")
        log(f"{voice}: ok")
    (out / "voices.md").write_text("\n".join(index) + "\n", encoding="utf-8")
