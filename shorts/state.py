"""Persistent state.

data/history.json (committed to main) holds every published episode: paper
metadata, the script, and the platform post ids. It is public on purpose:
it only contains public paper info and our own posts.

Comment-processing state lives elsewhere (see comments.py) and stores only
salted hashes of comment ids.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .config import HISTORY_FILE


def load_history() -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))


def save_history(items: list[dict[str, Any]]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from . import journal

    journal.write()


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:120]


def seen_keys(history: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for ep in history:
        paper = ep.get("paper", {})
        for k in ("id", "doi"):
            if paper.get(k):
                keys.add(str(paper[k]).lower())
        if paper.get("title"):
            keys.add(norm_title(paper["title"]))
    return keys
