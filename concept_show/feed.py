"""The show's public podcast feed, self-hosted on GitHub.

Each published episode is a GitHub release tagged boring-epNN (not a pre-release) holding episode.mp3 and
meta.json. The feed (docs/boring-stats/feed.xml, served by GitHub Pages) lists those releases; Spotify, Apple
Podcasts and KKBOX read it once submitted and pick up new episodes on their own. Each MP3's download count on
its release is the per-episode statistic the planner reads back.

python -m concept_show feed <releases.json> <out.xml>   releases.json = `gh api repos/{repo}/releases`
"""
from __future__ import annotations

import email.utils
import json
import sys
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from .show import CAST, SHOW

TAG = "boring-ep"
FEED = CAST.get("feed", {})


def published(releases: list[dict]) -> list[dict]:
    """Published episodes, oldest first: tag, title, description, date, mp3 url, size, downloads."""
    eps = []
    for r in releases:
        if not r.get("tag_name", "").startswith(TAG) or r.get("prerelease") or r.get("draft"):
            continue
        mp3 = next((a for a in r.get("assets", []) if a["name"] == "episode.mp3"), None)
        if not mp3:
            continue
        eps.append({"tag": r["tag_name"], "title": r.get("name") or r["tag_name"], "notes": r.get("body") or "",
                    "date": r.get("published_at") or r.get("created_at"), "url": mp3["browser_download_url"],
                    "size": mp3.get("size", 0), "downloads": mp3.get("download_count", 0)})
    return sorted(eps, key=lambda e: e["date"])


def _date(iso: str) -> str:
    return email.utils.format_datetime(datetime.fromisoformat(iso.replace("Z", "+00:00")))


def rss(eps: list[dict]) -> str:
    f = FEED
    items = []
    for n, e in enumerate(eps, 1):
        items.append(f"""  <item>
   <title>{escape(e['title'])}</title>
   <description>{escape(e['notes'])}</description>
   <guid isPermaLink="false">{escape(e['tag'])}</guid>
   <pubDate>{_date(e['date'])}</pubDate>
   <enclosure url="{escape(e['url'])}" length="{e['size']}" type="audio/mpeg"/>
   <itunes:episode>{n}</itunes:episode>
   <itunes:explicit>false</itunes:explicit>
  </item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
 <channel>
  <title>{escape(SHOW)}</title>
  <link>{escape(f.get('site', ''))}</link>
  <atom:link href="{escape(f.get('url', ''))}" rel="self" type="application/rss+xml"/>
  <description>{escape(f.get('description', ''))}</description>
  <language>zh-tw</language>
  <itunes:author>{escape(f.get('author', SHOW))}</itunes:author>
  <itunes:owner><itunes:name>{escape(f.get('author', SHOW))}</itunes:name><itunes:email>{escape(f.get('email', ''))}</itunes:email></itunes:owner>
  <itunes:image href="{escape(f.get('cover', ''))}"/>
  <itunes:category text="{escape(f.get('category', 'Science'))}"/>
  <itunes:explicit>false</itunes:explicit>
  <itunes:type>episodic</itunes:type>
{chr(10).join(reversed(items))}
 </channel>
</rss>
"""


def missing() -> list[str]:
    """Show settings the directories require before the feed can be submitted."""
    return [k for k in ("url", "site", "description", "email", "cover") if not FEED.get(k)]


def main(releases_path: str, out_path: str) -> None:
    eps = published(json.loads(Path(releases_path).read_text(encoding="utf-8")))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(rss(eps), encoding="utf-8")
    print(f"Feed: {len(eps)} episodes", flush=True)
    if m := missing():
        print("Feed is not ready to submit; fill these in cast.json \"feed\": " + ", ".join(m), file=sys.stderr)
