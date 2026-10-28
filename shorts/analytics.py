"""Read the channel's numbers (the "back office") so the automatic pipelines can learn from them.

collect()  pulls per-post numbers for every published short and podcast episode:
           YouTube public counters (any token), YouTube Analytics watch time / retention /
           subscribers gained (only if the refresh token has yt-analytics.readonly),
           Instagram and Threads insights (if the tokens allow; otherwise skipped).
Writes STATE_DIR/analytics/latest.json, appends a compact daily row per post to
history.jsonl, writes a readable report.md, and (weekly) asks Claude for strategy.md:
what has worked, which the paper picker and the podcast writer read before each episode.

Only numbers about our own posts are stored; no viewer or commenter data.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from . import config, llm
from .publish import meta, youtube
from .safelog import ApiError, log
from .state import load_history

STATE_DIR = Path(os.environ.get("STATE_DIR", config.ROOT / "state"))
DIR = STATE_DIR / "analytics"
PODCAST_HISTORY = config.DATA / "podcast_history.json"


def load_podcast_history() -> list[dict]:
    if not PODCAST_HISTORY.exists():
        return []
    return json.loads(PODCAST_HISTORY.read_text(encoding="utf-8"))


def _posts() -> list[dict]:
    """Every published post we know of, one row per platform and language."""
    rows = []
    for ep in load_history():
        title = (ep.get("script") or {}).get("title_en") or ep["paper"]["title"]
        for lang, posts in (ep.get("posts") or {}).items():
            for platform, p in posts.items():
                rows.append({"kind": "short", "episode": ep["episode"], "title": title, "lang": lang,
                             "platform": platform, "id": p["id"], "url": p.get("url", ""),
                             "paper": ep["paper"]["title"], "created": ep.get("created", "")})
    for ep in load_podcast_history():
        if yt := ep.get("youtube"):
            rows.append({"kind": "podcast", "episode": ep["episode"], "title": ep["title"], "lang": "en",
                         "platform": "youtube", "id": yt["id"], "url": yt.get("url", ""),
                         "paper": ep["paper"]["title"], "created": ep.get("created", "")})
    return rows


def collect() -> dict:
    rows = _posts()
    now = datetime.now(timezone.utc)
    report: dict = {"collected_at": now.isoformat(timespec="seconds"), "channel": {}, "notes": [], "posts": rows}
    yt_ids = [r["id"] for r in rows if r["platform"] == "youtube"]
    if yt_ids and config.env("YOUTUBE_REFRESH_TOKEN"):
        try:
            report["channel"]["youtube"] = youtube.channel_stats()
            stats = youtube.video_stats(yt_ids)
            deep = youtube.analytics_by_video(yt_ids, "2025-01-01", now.date().isoformat())
            if deep is None:
                report["notes"].append("YouTube Analytics not authorized (token lacks yt-analytics.readonly): "
                                       "only public counters, no watch time or retention")
            for r in rows:
                if r["platform"] == "youtube":
                    r["metrics"] = stats.get(r["id"], {"missing": True}) | ((deep or {}).get(r["id"]) or {})
        except (ApiError, SystemExit) as exc:
            report["notes"].append(f"YouTube skipped: {exc}")
    for platform, fn, secret in (("instagram", meta.ig_insights, "IG_ACCESS_TOKEN"),
                                 ("threads", meta.th_insights, "THREADS_ACCESS_TOKEN")):
        if not config.env(secret):
            continue
        got = 0
        for r in rows:
            if r["platform"] != platform:
                continue
            try:
                r["metrics"] = fn(r["id"])
                got += bool(r["metrics"])
            except (ApiError, SystemExit):
                r["metrics"] = {}
        if not got and any(r["platform"] == platform for r in rows):
            report["notes"].append(f"{platform}: no insights returned (token may lack the insights permission)")
    log(f"Analytics: {len(rows)} posts, " + ", ".join(
        f"{p}={sum(1 for r in rows if r['platform'] == p and r.get('metrics'))}"
        for p in ("youtube", "instagram", "threads")))
    return report


def views(r: dict) -> int:
    m = r.get("metrics") or {}
    return int(m.get("views") or m.get("reach") or 0)


def summary(report: dict, top: int = 5) -> str:
    """Plain-text digest for prompts and for the owner."""
    rows = report.get("posts", [])
    out = [f"Collected {report.get('collected_at', '?')}"]
    if ch := report.get("channel", {}).get("youtube"):
        out.append(f"YouTube channel: {ch['subscriberCount']} subscribers, {ch['viewCount']} total views, "
                   f"{ch['videoCount']} videos")
    out += [f"Note: {n}" for n in report.get("notes", [])]
    for kind in ("short", "podcast"):
        for platform in ("youtube", "instagram", "threads"):
            rs = [r for r in rows if r["kind"] == kind and r["platform"] == platform and r.get("metrics")]
            if not rs:
                continue
            rs.sort(key=views, reverse=True)
            avg = sum(map(views, rs)) / len(rs)
            out.append(f"\n{kind} on {platform}: {len(rs)} posts, average {avg:.0f} views")
            by_lang: dict[str, list[int]] = {}
            for r in rs:
                by_lang.setdefault(r["lang"], []).append(views(r))
            if len(by_lang) > 1:
                out.append("  by language: " + ", ".join(f"{l} {sum(v) / len(v):.0f}" for l, v in by_lang.items()))
            pick = rs[:top] + [r for r in rs[-3:] if r not in rs[:top]]
            for r in pick:
                m = r["metrics"]
                extra = ""
                if "averageViewPercentage" in m:
                    extra = f", avg watched {m['averageViewPercentage']:.0f}%, +{m.get('subscribersGained', 0)} subs"
                out.append(f"  - {views(r)} views, {m.get('likes', 0)} likes, {m.get('comments', m.get('replies', 0))} "
                           f"comments{extra} | {r['lang']} | {r['title']}")
    return "\n".join(out)


def report_md(report: dict, strategy: str = "") -> str:
    rows = sorted((r for r in report.get("posts", []) if r.get("metrics")), key=views, reverse=True)
    md = ["# Channel analytics 頻道數據", "", f"Updated {report.get('collected_at', '?')}", "",
          "```", summary(report), "```", ""]
    if strategy:
        md += ["## Strategy 經營策略 (written by Claude)", "", strategy, ""]
    md += ["## All posts", "", "| kind | platform | lang | views | likes | comments | title |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        m = r["metrics"]
        md.append(f"| {r['kind']} | {r['platform']} | {r['lang']} | {views(r)} | {m.get('likes', '')} | "
                  f"{m.get('comments', m.get('replies', ''))} | [{r['title']}]({r['url']}) |")
    return "\n".join(md) + "\n"


class Strategy(BaseModel):
    observations: list[str] = Field(description="3-6 concrete observations from the numbers (cite the numbers)")
    shorts_advice: str = Field(description="2-4 sentences: which topics, hooks, titles and languages to favor for shorts")
    podcast_advice: str = Field(description="2-4 sentences: which papers and angles to favor for the weekly talk show, "
                                            "and what to change in its format if the numbers suggest it")
    caveat: str = Field(description="One sentence on how much to trust this given the sample size")


STRATEGY_SYSTEM = """You run the YouTube/Instagram/Threads channel "Behavior Decoded" (1-minute \
shorts in Chinese, English and Portuguese, each explaining one computational human-behavior paper) \
and its weekly English late-night-style talk show "Behavior Decoded Tonight" (hosts Kai and Anne). \
Read the channel numbers and write short, practical guidance for the next episodes. Be honest about \
small samples: with a handful of posts, say so rather than inventing trends. Never suggest \
clickbait that misstates a paper, and never suggest changing the scientific content to chase views."""


def write_strategy(report: dict) -> str:
    s = llm.ask(Strategy, STRATEGY_SYSTEM, summary(report, top=8), effort="medium", max_tokens=4000)
    return ("\n".join(f"- {o}" for o in s.observations)
            + f"\n\n**Shorts:** {s.shorts_advice}\n\n**Podcast:** {s.podcast_advice}\n\n_{s.caveat}_")


def guidance() -> str:
    """What the pipelines read before picking or writing: the latest digest and strategy, if any."""
    parts = []
    if (DIR / "strategy.md").exists():
        parts.append((DIR / "strategy.md").read_text(encoding="utf-8").strip())
    if (DIR / "latest.json").exists():
        parts.append(summary(json.loads((DIR / "latest.json").read_text(encoding="utf-8"))))
    return "\n\n".join(parts)


def run(strategy: bool | None = None) -> None:
    report = collect()
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    day = report["collected_at"][:10]
    with (DIR / "history.jsonl").open("a", encoding="utf-8") as fh:
        for r in report["posts"]:
            if r.get("metrics"):
                fh.write(json.dumps({"day": day, "platform": r["platform"], "id": r["id"], **r["metrics"]}) + "\n")
    sfile = DIR / "strategy.md"
    # file times are lost on checkout, so the note carries its own date on the first line
    written = sfile.read_text(encoding="utf-8").split("\n", 1)[0][-10:] if sfile.exists() else ""
    stale = written < (datetime.now(timezone.utc) - timedelta(days=6)).date().isoformat()
    if strategy or (strategy is None and stale and config.env("ANTHROPIC_API_KEY")):
        if any(r.get("metrics") for r in report["posts"]):
            sfile.write_text(f"Written {day}\n\n" + write_strategy(report) + "\n", encoding="utf-8")
            log("Strategy note updated")
    text = sfile.read_text(encoding="utf-8") if sfile.exists() else ""
    (DIR / "report.md").write_text(report_md(report, text), encoding="utf-8")
