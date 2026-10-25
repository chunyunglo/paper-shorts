"""Render the same narration in several voices so the owner can pick one by ear."""
from __future__ import annotations

import subprocess

from .config import OUT
from .safelog import log
from .tts import synth_edge, synth_google, write_wav

TEXT = ("2023年，請願網站 Change.org 加入了 AI 協助撰寫請願的工具。"
        "研究者分析了使用者寫的請願書，結果發現，寫法明顯改變，但成效並沒有變好。")

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
]


def render_all() -> None:
    out = OUT / "voices"
    out.mkdir(parents=True, exist_ok=True)
    index = ["# 聲音試聽 Voice samples", "", f"句子：{TEXT}", ""]
    for n, (prov, voice, label) in enumerate(VOICES, 1):
        try:
            audio = (synth_google if prov == "google" else synth_edge)(TEXT, voice)
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
