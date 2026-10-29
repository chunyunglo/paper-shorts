"""data/decisions.md: a readable log of what went out and why.

Rebuilt from the three history files (shorts, talk show, free posts) every time one of them is
saved, so it never drifts from what was actually posted. Newest day first. Each entry keeps the
picker's own reason, including which channel numbers or viewer feedback shaped it.
"""
from __future__ import annotations

import json

from . import config

FILE = config.DATA / "decisions.md"
MISSING = "（沒有記錄：這篇在開始記錄理由之前發的 / posted before reasons were kept）"


def _load(name: str) -> list[dict]:
    path = config.DATA / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def entries() -> list[tuple[str, list[str]]]:
    """(timestamp, markdown lines) for every post, unsorted."""
    out = []
    for ep in _load("history.json"):
        s, p = ep.get("script", {}), ep["paper"]
        link = next((v["url"] for lang in ep.get("posts", {}).values() for v in lang.values() if v.get("url")), "")
        title = f"{s.get('title_zh', '')} / {s.get('title_en', '')}".strip(" /") or p["title"]
        lines = [f"- **短影音 Short** · [{title}]({link})" if link else f"- **短影音 Short** · {title}",
                 f"  - 論文 Paper: [{p['title']}]({p['url']}) ({p.get('venue', '')})",
                 f"  - 為什麼 Why: {ep.get('pick_reason') or MISSING}"]
        if n := ep.get("news"):
            lines.append(f"  - 時事 News hook: {n['title']} ({n.get('source', '')}). {n.get('link', '')}".rstrip())
        out.append((ep.get("created", ""), lines))
    for ep in _load("podcast_history.json"):
        url = ep.get("youtube", {}).get("url", "")
        lines = [f"- **脫口秀 Talk show** · [{ep['title']}]({url})" if url else f"- **脫口秀 Talk show** · {ep['title']}",
                 f"  - 論文 Paper: [{ep['paper']['title']}]({ep['paper']['url']})",
                 f"  - 為什麼 Why: {ep.get('pick_reason') or MISSING}"]
        out.append((ep.get("publish_at") or ep.get("created", ""), lines))
    for post in _load("social_history.json"):
        text = " ".join(post["text"].split())
        lines = [f"- **自由發文 Free post** · {post['platform']}/{post['lang']} · {post['kind']} · [link]({post['url']})",
                 f"  - 內容 Text: {text[:120]}{'…' if len(text) > 120 else ''}",
                 f"  - 為什麼 Why: {post.get('why') or MISSING}"]
        if post.get("news"):
            lines.append(f"  - 時事 News hook: {post['news']}")
        if post.get("episodes"):
            lines.append(f"  - 根據的集數 Based on: {', '.join(post['episodes'])}")
        out.append((post["posted"], lines))
    return out


def render() -> str:
    md = ["# 發文決策紀錄 Decision log", "",
          "每次發文後自動更新：每篇為什麼發、參考了哪些數據或觀眾回饋。最新的在最上面。",
          "Rebuilt after every post from data/*.json: why each post went out. Newest first.",
          "Weekly strategy notes: `analytics/strategy_log.md` on the `state` branch; the weekly self-review of "
          "these decisions against their results: `analytics/lessons.md` (history in `lessons_log.md`).", ""]
    day = None
    for ts, lines in sorted(entries(), key=lambda e: e[0], reverse=True):
        if ts[:10] != day:
            day = ts[:10]
            md += ["", f"## {day}", ""]
        md += lines
    return "\n".join(md) + "\n"


def write() -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(render(), encoding="utf-8")
