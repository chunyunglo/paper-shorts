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

COMMENT = {"youtube": youtube.comment, "instagram": meta.ig_comment, "threads": meta.th_reply}
DELETE = {"youtube": youtube.delete, "instagram": meta.ig_delete, "threads": meta.th_delete}

DISCLOSURE = {
    "zh": "本影片腳本、配音與畫面皆由 AI 生成，內容依據原始論文；請以論文原文為準。",
    "en": "Script, voice, and visuals are AI-generated from the paper. Please refer to the original paper.",
    "pt": "Roteiro, voz e imagens gerados por IA a partir do artigo. Consulte o artigo original.",
}
OTHER = {"zh": "English and Português versions on our channel.",
         "en": "中文版與 Português 版也在我們的頻道。",
         "pt": "Versões em chinês e inglês no nosso canal."}
AI_TAG = {"zh": "#AI生成", "en": "#AIgenerated", "pt": "#feitocomIA"}
CITE_LABEL = {"zh": "📄 論文出處", "en": "📄 Paper", "pt": "📄 Artigo"}


def citation(p: dict) -> str:
    """APA-style reference: Authors (Year). Title. Venue. DOI or URL."""
    authors = p.get("authors") or []
    if len(authors) > 3:
        who = ", ".join(authors[:3]) + ", et al."
    else:
        who = ", ".join(authors)
    ref = f"{who} ({p['published'][:4]}). {p['title']}. {p['venue']}."
    link = f"https://doi.org/{p['doi']}" if p.get("doi") else p["url"]
    return f"{ref.strip()} {link}"


def first_comment(ep: dict, lang: str) -> str:
    return f"{CITE_LABEL[lang]}\n{citation(ep['paper'])}"


def captions(ep: dict, lang: str) -> dict[str, str]:
    s, p = ep["script"], ep["paper"]
    pt = s.get("pt") or {}
    hashtags = pt.get("hashtags") if lang == "pt" and pt.get("hashtags") else s["hashtags"]
    tags = " ".join("#" + h.replace(" ", "") for h in hashtags)
    authors = p.get("authors") or []
    who = (authors[0] + (" et al." if len(authors) > 1 else "") + " ") if authors else ""
    cite = f"{who}({p['published'][:4]}). {p['title']}. {p['venue']}."
    title = {"zh": s["title_zh"], "en": s["title_en"], "pt": pt.get("title")}[lang]
    desc = {"zh": s["description_zh"], "en": s["description_en"], "pt": pt.get("description")}[lang]
    long = f"{title}\n\n{desc}\n\n📄 {cite}\n{p['url']}\n\n{DISCLOSURE[lang]}\n{OTHER[lang]}\n\n{tags}"
    ai_tag = AI_TAG[lang]
    short = f"{title}\n\n{desc}\n\n📄 {p['url']}\n{ai_tag}"
    if len(short) > 490:
        short = f"{title}\n\n📄 {p['url']}\n{ai_tag}"
    return {"yt_title": title[:90] + " #Shorts", "long": long, "threads": short, "tags": hashtags}


def publish_episode(folder: Path, video_base_url: str, only: list[str] | None = None,
                    langs: list[str] | None = None) -> None:
    """video_base_url: the release download URL prefix; files are video_<lang>.mp4 under it.
    After each post, a first comment with the full citation goes under it."""
    ep = json.loads((folder / "episode.json").read_text(encoding="utf-8"))
    targets = only or ["youtube", "instagram", "threads"]
    posts = ep.setdefault("posts", {})
    # Posts made by an earlier run (e.g. zh/en at 19:00 Taiwan, pt later) live in history.
    for h in load_history():
        if h["episode"] == ep["episode"]:
            for lang, done in h.get("posts", {}).items():
                posts.setdefault(lang, {}).update({k: v for k, v in done.items() if k not in posts.get(lang, {})})
    failed = []

    for lang, video in ep["videos"].items():
        if langs and lang not in langs:
            continue
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
                return
            try:  # the citation comment is nice to have; a failure here does not fail the post
                COMMENT[name](done[name]["id"], first_comment(ep, lang))
            except (ApiError, SystemExit, KeyError) as exc:
                log(f"{name} ({lang}): citation comment failed - {exc}")

        attempt("youtube", lambda: {"id": (vid := youtube.upload(
            folder / video["file"], cap["yt_title"], cap["long"], cap["tags"], lang)),
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


def delete_episode(episode: str) -> None:
    """Delete every post of one episode, then drop the episode from history.
    Posts that could not be deleted stay in history so a later run can retry them."""
    history = load_history()
    ep = next((h for h in history if h["episode"] == episode), None)
    if not ep:
        raise SystemExit(f"Episode {episode} is not in history")
    failed = []
    for lang, posts in ep.get("posts", {}).items():
        for name in list(posts):
            try:
                DELETE[name](posts[name]["id"])
                log(f"{name} ({lang}): deleted")
                del posts[name]
            except (ApiError, SystemExit, KeyError) as exc:
                log(f"{name} ({lang}): delete FAILED - {exc}")
                failed.append(f"{name}/{lang}")
    ep["posts"] = {l: p for l, p in ep.get("posts", {}).items() if p}
    save_history([h for h in history if h["episode"] != episode or ep["posts"]])
    if failed:
        raise SystemExit("Could not delete: " + ", ".join(failed) + " (delete these by hand)")
