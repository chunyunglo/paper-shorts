"""Recent news headlines, so an episode can tie its paper to something people are talking about."""
from __future__ import annotations

import calendar
import time

import feedparser
from pydantic import BaseModel

from .safelog import http, log

# Top stories for each audience (Taiwan, US/international), plus tech and science,
# where most computational behavior papers find their link.
FEEDS = {
    "TW": "https://news.google.com/rss?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "US": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "tech": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
    "science": "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en-US&gl=US&ceid=US:en",
}
UA = {"User-Agent": "paper-shorts/1.0 (+https://github.com/chunyunglo/paper-shorts)"}


class Headline(BaseModel):
    title: str
    source: str = ""
    published: str = ""
    region: str = ""


def parse(feed_bytes: bytes, region: str, days: int = 3, now: float | None = None) -> list[Headline]:
    now = now or time.time()
    out = []
    for e in feedparser.parse(feed_bytes).entries:
        title, src = e.get("title", "").strip(), (e.get("source") or {}).get("title", "")
        if src and title.endswith(f" - {src}"):
            title = title[: -len(src) - 3].strip()
        ts = e.get("published_parsed")
        if ts and now - calendar.timegm(ts) > days * 86400:
            continue
        if title:
            out.append(Headline(title=title, source=src, region=region,
                                published=time.strftime("%Y-%m-%d", ts) if ts else ""))
    return out


def headlines(per_feed: int = 25) -> list[Headline]:
    """Never fails: an unreachable feed only means fewer (or no) headlines."""
    out: list[Headline] = []
    seen: set[str] = set()
    for region, url in FEEDS.items():
        try:
            resp = http("news", region, "GET", url, headers=UA)
            items = parse(resp.content, region)[:per_feed]
        except Exception as exc:
            log(f"News feed {region} skipped: {exc}")
            continue
        for h in items:
            if h.title.lower() not in seen:
                seen.add(h.title.lower())
                out.append(h)
    log(f"News: {len(out)} recent headlines")
    return out


def listing(items: list[Headline]) -> str:
    return "\n".join(f"<{i}> [{h.region}] {h.title} ({h.source}, {h.published})" for i, h in enumerate(items))
