"""One daily budget for the Threads account, shared by every pipeline that posts text there.

In November 2026 the account posted about six times a day (two shorts, three stock-series posts, one
or two free posts) and views per post fell: Chinese shorts on Threads went from a median of 23 views
to 6. THREADS_DAILY_CAP (default 2, or the playbook's threads_daily_cap) caps the account's posts per Taiwan day. One of them is kept
for the evening short, so the free posts and the stock series share the rest, first come first
served (the 08:00 stock post usually takes it).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import config

TW = timezone(timedelta(hours=8))


def daily_cap() -> int:
    from . import playbook  # set by the weekly review; THREADS_DAILY_CAP still overrides

    return int(playbook.get("threads_daily_cap"))


def _day(ts: str) -> str:
    t = datetime.fromisoformat(ts)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(TW).date().isoformat()


def extras_today(now: datetime | None = None) -> int:
    """Threads text posts (free posts and stock series) already made on this Taiwan day."""
    day = (now or datetime.now(timezone.utc)).astimezone(TW).date().isoformat()
    n = 0
    for name in ("social_history.json", "stock_history.json"):
        f = config.DATA / name
        if not f.exists():
            continue
        n += sum(1 for p in json.loads(f.read_text(encoding="utf-8"))
                 if p.get("platform") == "threads" and p.get("posted") and _day(p["posted"]) == day)
    return n


def room(now: datetime | None = None) -> int:
    """How many more free or stock posts Threads may get today (one slot stays for the short)."""
    return max(0, daily_cap() - 1 - extras_today(now))
