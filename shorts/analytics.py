"""Read the channel's numbers (the "back office") so the automatic pipelines can learn from them.

collect()  pulls per-post numbers for every published short and podcast episode:
           YouTube public counters (any token), YouTube Analytics watch time / retention /
           subscribers gained (only if the refresh token has yt-analytics.readonly),
           Instagram and Threads insights (if the tokens allow; otherwise skipped).
Writes STATE_DIR/analytics/latest.json, appends a compact daily row per post to
history.jsonl, writes a readable report.md, and (weekly) asks Claude for strategy.md:
what has worked, which the paper pickers, the script writers and the free-post planner read.
The same weekly run first writes a self-review of past decisions against their results (memory.py).

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
    from .social import load as load_social

    for i, sp in enumerate(load_social()):
        if sp.get("id"):
            rows.append({"kind": "social", "episode": f"social-{i}", "title": sp["text"][:80], "lang": sp["lang"],
                         "platform": sp["platform"], "id": sp["id"], "url": sp.get("url", ""),
                         "paper": ", ".join(sp.get("episodes") or []), "created": sp["posted"]})
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
    out.append("Note: every short and talk show has one comment from us (the paper citation), and our replies "
               "to viewers count too, so comment counts overstate viewer comments; likes may include our own.")
    for kind in ("short", "podcast", "social"):
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


def report_md(report: dict, strategy: str = "", lessons: str = "") -> str:
    rows = sorted((r for r in report.get("posts", []) if r.get("metrics")), key=views, reverse=True)
    md = ["# Channel analytics 頻道數據", "", f"Updated {report.get('collected_at', '?')}", "",
          "```", summary(report), "```", ""]
    if strategy:
        md += ["## Strategy 經營策略 (written by Claude)", "", strategy, ""]
    if lessons:
        md += ["## Self-review 自我檢討 (past decisions vs. results)", "", lessons, ""]
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
    social_advice: str = Field("", description="1-3 sentences on the free Threads text posts and Instagram slide posts "
                                               "(kind, language, platform), or empty if there are no numbers yet")
    caveat: str = Field(description="One sentence on how much to trust this given the sample size")


STRATEGY_SYSTEM = """You run the YouTube/Instagram/Threads channel "Behavior Decoded" (1-minute \
shorts in Chinese and English, each explaining one computational human-behavior paper) \
and its weekly English late-night-style talk show "Behavior Decoded Tonight" (hosts Kai and Anne), \
plus free posts between episodes (Threads text, Instagram slides; "social" in the numbers). \
Read the channel numbers and write short, practical guidance for the next episodes. Be honest about \
small samples: with a handful of posts, say so rather than inventing trends. Never suggest \
clickbait that misstates a paper, and never suggest changing the scientific content to chase views."""


def write_strategy(report: dict) -> str:
    from . import memory

    prompt = summary(report, top=8)
    if lessons := memory.lessons():
        prompt += "\n\nThis week's self-review of our past decisions (build on it):\n<lessons>\n" + lessons + "\n</lessons>"
    s = llm.ask(Strategy, STRATEGY_SYSTEM, prompt, effort="medium", max_tokens=4000)
    return ("\n".join(f"- {o}" for o in s.observations)
            + f"\n\n**Shorts:** {s.shorts_advice}\n\n**Podcast:** {s.podcast_advice}"
            + (f"\n\n**Free posts:** {s.social_advice}" if s.social_advice.strip() else "")
            + f"\n\n_{s.caveat}_")


def guidance() -> str:
    """What the pipelines read before picking or writing: the latest digest and strategy, if any."""
    from . import memory

    parts = []
    if lessons := memory.lessons():
        parts.append("Lessons from our weekly self-review of past posts and their results:\n" + lessons)
    if (DIR / "strategy.md").exists():
        parts.append((DIR / "strategy.md").read_text(encoding="utf-8").strip())
    if (DIR / "latest.json").exists():
        parts.append(summary(json.loads((DIR / "latest.json").read_text(encoding="utf-8"))))
    from .comments import recent_feedback

    if fb := recent_feedback():
        parts.append("What viewers told us in comments (paraphrased, newest last):\n"
                     + "\n".join(f"- {r['day']} ({r['episode']}): {r['note']}" for r in fb))
    return "\n\n".join(parts)


def weekly_email(report: dict, strategy: str, lessons: str) -> bool:
    """The owner's weekly letter: the self-review, the new strategy and the numbers, by private email."""
    from . import notify

    day = report.get("collected_at", "")[:10]
    url = f"https://github.com/{config.GITHUB_REPO}/blob/state/analytics/report.md"
    body = "\n\n".join([
        f"行為解碼 每週檢討與策略 Weekly review and strategy, {day}",
        "== 自我檢討 Self-review (past decisions vs. results) ==\n\n" + (lessons or "(還沒有：貼文太新，無法評估)"),
        "== 經營策略 Strategy ==\n\n" + (strategy or "(none yet)"),
        "== 數據摘要 Numbers ==\n\n" + summary(report),
        f"完整報告 Full report: {url}\n決策紀錄 Decision log: https://github.com/{config.GITHUB_REPO}"
        "/blob/main/data/decisions.md"])
    ok = notify.email(f"[行為解碼] 每週檢討與策略 {day}", body)
    log("Weekly report emailed" if ok else "Weekly report not emailed (check the ALERT_EMAIL_* secrets)")
    return ok


def run(strategy: bool | None = None, email: bool = False) -> None:
    """email: send the weekly letter even if the strategy was not rewritten this run."""
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
            from . import memory

            try:  # look back at what worked first, so the new strategy builds on it
                memory.retrospect()
            except RuntimeError as exc:
                log(f"Retrospective skipped: {exc}")
            note = write_strategy(report)
            sfile.write_text(f"Written {day}\n\n" + note + "\n", encoding="utf-8")
            # strategy.md is replaced each week; the log keeps every note so past reasoning stays readable
            logfile = DIR / "strategy_log.md"
            old = logfile.read_text(encoding="utf-8") if logfile.exists() else "# 經營策略紀錄 Strategy log\n"
            logfile.write_text(old.rstrip("\n") + f"\n\n## {day}\n\n{note}\n", encoding="utf-8")
            log("Strategy note updated")
            email = True  # a new weekly note goes to the owner
    text = sfile.read_text(encoding="utf-8") if sfile.exists() else ""
    from . import memory

    (DIR / "report.md").write_text(report_md(report, text, memory.lessons()), encoding="utf-8")
    if email:
        weekly_email(report, "\n".join(text.split("\n")[2:]).strip(), memory.lessons())
