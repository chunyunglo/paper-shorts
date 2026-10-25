"""Publish one episode folder to every platform and record it in data/history.json.

Each platform is attempted independently; a failure on one does not stop the others,
and the job exits non-zero at the end if anything failed.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..safelog import ApiError, log
from ..state import load_history, save_history
from . import meta, youtube

DISCLOSURE = {
    "zh": "本影片腳本、配音與畫面皆由 AI 生成，內容依據原始論文；請以論文原文為準。",
    "en": "Script, voice, and visuals are AI-generated from the paper. Please refer to the original paper.",
}


def captions(ep: dict, lang: str) -> dict[str, str]:
    s, p = ep["script"], ep["paper"]
    tags = " ".join("#" + h.replace(" ", "") for h in s["hashtags"])
    authors = p.get("authors") or []
    who = (authors[0] + (" et al." if len(authors) > 1 else "") + " ") if authors else ""
    cite = f"{who}({p['published'][:4]}). {p['title']}. {p['venue']}."
    title = s["title_zh"] if lang == "zh" else s["title_en"]
    desc = s["description_zh"] if lang == "zh" else s["description_en"]
    other = "English version on our channel." if lang == "zh" else "中文版也在我們的頻道。"
    long = f"{title}\n\n{desc}\n\n📄 {cite}\n{p['url']}\n\n{DISCLOSURE[lang]}\n{other}\n\n{tags}"
    ai_tag = "#AI生成" if lang == "zh" else "#AIgenerated"
    short = f"{title}\n\n{desc}\n\n📄 {p['url']}\n{ai_tag}"
    if len(short) > 490:
        short = f"{title}\n\n📄 {p['url']}\n{ai_tag}"
    return {"yt_title": title[:90] + " #Shorts", "long": long, "threads": short}


def publish_episode(folder: Path, video_base_url: str, only: list[str] | None = None) -> None:
    """video_base_url: the release download URL prefix; files are video_<lang>.mp4 under it."""
    ep = json.loads((folder / "episode.json").read_text(encoding="utf-8"))
    targets = only or ["youtube", "instagram", "threads"]
    posts = ep.setdefault("posts", {})
    failed = []

    for lang, video in ep["videos"].items():
        cap = captions(ep, lang)
        url = f"{video_base_url.rstrip('/')}/{video['file']}"
        done = posts.setdefault(lang, {})

        def attempt(name, fn):
            if name not in targets or name in done:
                return
            try:
                done[name] = fn()
            except (ApiError, SystemExit, KeyError) as exc:
                log(f"{name} ({lang}): FAILED - {exc}")
                failed.append(f"{name}/{lang}")

        attempt("youtube", lambda: {"id": (vid := youtube.upload(
            folder / video["file"], cap["yt_title"], cap["long"], ep["script"]["hashtags"], lang)),
            "url": f"https://youtube.com/shorts/{vid}"})
        attempt("instagram", lambda: dict(zip(("id", "url"), meta.ig_publish_reel(
            url, cap["long"][:2150], video["cover_offset_ms"]))))
        attempt("threads", lambda: dict(zip(("id", "url"), meta.th_publish_video(url, cap["threads"]))))

    ep["video_base_url"] = video_base_url
    (folder / "episode.json").write_text(json.dumps(ep, ensure_ascii=False, indent=2), encoding="utf-8")
    if any(posts.values()):
        history = [h for h in load_history() if h["episode"] != ep["episode"]]
        history.append({k: ep[k] for k in ("episode", "created", "paper", "script", "videos", "posts", "video_base_url")})
        save_history(history)
        log("History updated: " + ", ".join(f"{l}:{'+'.join(sorted(v))}" for l, v in posts.items()))
    if failed:
        raise SystemExit(f"Publishing failed on: {', '.join(failed)}")
