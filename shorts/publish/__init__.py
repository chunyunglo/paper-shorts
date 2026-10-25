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

DISCLOSURE = "本影片腳本、配音與畫面皆由 AI 生成，內容依據原始論文；請以論文原文為準。\n" \
             "Script, voice, and visuals are AI-generated from the paper. Please refer to the original paper."


def captions(ep: dict) -> dict[str, str]:
    s, p = ep["script"], ep["paper"]
    tags = " ".join("#" + h.replace(" ", "") for h in s["hashtags"])
    first = (p.get("authors") or ["?"])[0]
    cite = f"{first}{' et al.' if len(p.get('authors') or []) > 1 else ''} ({p['published'][:4]}). {p['title']}. {p['venue']}."
    long = (f"{s['title_zh']}｜{s['title_en']}\n\n{s['description_zh']}\n\n{s['description_en']}\n\n"
            f"📄 {cite}\n{p['url']}\n\n{DISCLOSURE}\n\n{tags}")
    yt_title = f"{s['title_zh']}｜{s['title_en']}"
    if len(yt_title) > 90:
        yt_title = s["title_zh"][:60]
    short = f"{s['title_zh']}\n{s['title_en']}\n\n{s['description_zh']}\n\n📄 {p['url']}\n#AI生成 {tags}"
    if len(short) > 490:
        short = f"{s['title_zh']}\n{s['title_en']}\n\n📄 {p['url']}\n#AI生成"
    return {"yt_title": yt_title + " #Shorts", "long": long, "threads": short}


def publish_episode(folder: Path, video_url: str, only: list[str] | None = None) -> None:
    ep = json.loads((folder / "episode.json").read_text(encoding="utf-8"))
    cap = captions(ep)
    targets = only or ["youtube", "instagram", "threads"]
    posts = ep.setdefault("posts", {})
    failed = []

    def attempt(name, fn):
        if name not in targets or name in posts:
            return
        try:
            posts[name] = fn()
        except (ApiError, SystemExit, KeyError) as exc:
            log(f"{name}: FAILED - {exc}")
            failed.append(name)

    attempt("youtube", lambda: {"id": (vid := youtube.upload(
        folder / "video.mp4", cap["yt_title"], cap["long"], ep["script"]["hashtags"])),
        "url": f"https://youtube.com/shorts/{vid}"})
    attempt("instagram", lambda: dict(zip(("id", "url"), meta.ig_publish_reel(
        video_url, cap["long"][:2150], ep["cover_offset_ms"]))))
    attempt("threads", lambda: dict(zip(("id", "url"), meta.th_publish_video(video_url, cap["threads"]))))

    ep["video_url"] = video_url
    (folder / "episode.json").write_text(json.dumps(ep, ensure_ascii=False, indent=2), encoding="utf-8")
    if posts:
        history = [h for h in load_history() if h["episode"] != ep["episode"]]
        history.append({k: ep[k] for k in ("episode", "created", "paper", "script", "posts", "video_url")})
        save_history(history)
        log(f"History updated: {', '.join(sorted(posts))}")
    if failed:
        raise SystemExit(f"Publishing failed on: {', '.join(failed)}")
