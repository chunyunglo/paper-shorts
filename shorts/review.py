"""Owner review before publishing.

prepare (afternoon): the episode's videos go on a pre-release, and the Actions bot opens a review
issue in this repo. Because the bot (not the owner) opens it, GitHub notifies the owner by email
and app push. (Issues the owner's own token creates never notify the owner.)
publish (evening): only if the owner replied with an approval (e.g. "OK", "沒問題") on that
issue does the episode go out. Otherwise nothing is posted and the issue is closed as skipped.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import config
from .safelog import http, log

APPROVALS = {"ok", "okay", "ok!", "沒問題", "没问题", "可以", "可以上", "通過", "通过", "approve", "approved",
             "lgtm", "上", "上吧", "好", "好的", "👍", "yes", "go"}
MARKER = re.compile(r"<!-- release: (\S+) -->")


def _gh() -> dict:
    return {"Authorization": f"Bearer {config.require('GITHUB_TOKEN')}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def inbox() -> str:
    return config.GITHUB_REPO


def owner() -> str:
    return config.GITHUB_REPO.split("/")[0]


def is_approval(text: str) -> bool:
    t = re.sub(r"[\s。.!！~～,，]+$", "", text.strip().lower())
    return t in APPROVALS or (len(t) <= 6 and any(t.startswith(a) for a in ("ok", "沒問題", "可以", "lgtm", "👍")))


def open_review(folder: Path, tag: str) -> int:
    ep = json.loads((folder / "episode.json").read_text(encoding="utf-8"))
    s, p = ep["script"], ep["paper"]
    base = f"https://github.com/{config.GITHUB_REPO}/releases/download/{tag}"
    when = os.environ.get("PUBLISH_AT", "今晚 19:00")
    name = {"zh": "中文版", "en": "English", "pt": "Português (BR)"}
    videos = "\n".join(
        f"- **{name.get(lang, lang)}**（{v['duration']:.0f} 秒）：[{v['file']}]({base}/{v['file']})"
        for lang, v in ep["videos"].items())
    covers = " ".join(f'<img src="{base}/cover_{lang}.jpg" width="240">' for lang in ep["videos"])
    body = (f"## {s['title_zh']} / {s['title_en']}\n\n"
            f"回覆 **OK** 或 **沒問題**，就會上片到 YouTube、Instagram、Threads：{when}。\n"
            f"沒回覆或回其他內容，這集就不上片。\n\n"
            f"Reply **OK** to publish ({when}). No reply means no post.\n\n"
            f"### 影片 Videos\n{videos}\n\n{covers}\n\n"
            f"### 論文 Paper\n[{p['title']}]({p['url']}), {p['venue']} ({p['published']})\n\n"
            f"<details><summary>腳本 Script</summary>\n\n{(folder / 'script.md').read_text(encoding='utf-8')}\n</details>\n\n"
            f"<!-- release: {tag} -->\n")
    resp = http("github", "open review issue", "POST", f"https://api.github.com/repos/{inbox()}/issues",
                headers=_gh(), json={"title": f"[審核] {s['title_zh']}", "body": body,
                                     "labels": ["review"], "assignees": [owner()]})
    number = resp.json()["number"]
    log(f"Review issue opened: #{number}")
    return number


def _open_reviews() -> list[dict]:
    resp = http("github", "list review issues", "GET", f"https://api.github.com/repos/{inbox()}/issues",
                headers=_gh(), params={"labels": "review", "state": "open", "per_page": 20})
    return [i for i in resp.json() if "pull_request" not in i and MARKER.search(i.get("body") or "")]


def approved() -> list[tuple[int, str]]:
    """(issue number, release tag) for each open review the owner approved."""
    out = []
    for issue in _open_reviews():
        comments = http("github", "list review comments", "GET", issue["comments_url"], headers=_gh(),
                        params={"per_page": 100}).json()
        if any(c["user"]["login"] == owner() and is_approval(c.get("body", "")) for c in comments):
            out.append((issue["number"], MARKER.search(issue["body"]).group(1)))
    log(f"Reviews: {len(out)} approved")
    return out


def close(number: int, message: str, published: bool, keep_open: bool = False) -> None:
    base = f"https://api.github.com/repos/{inbox()}/issues/{number}"
    http("github", "comment on review", "POST", f"{base}/comments", headers=_gh(), json={"body": message})
    if keep_open:
        return
    http("github", "close review", "PATCH", base, headers=_gh(),
         json={"state": "closed", "state_reason": "completed" if published else "not_planned"})


def skip_unapproved() -> None:
    """At publish time, close reviews nobody approved so they don't pile up."""
    for issue in _open_reviews():
        comments = http("github", "list review comments", "GET", issue["comments_url"], headers=_gh(),
                        params={"per_page": 100}).json()
        if not any(c["user"]["login"] == owner() and is_approval(c.get("body", "")) for c in comments):
            close(issue["number"], "沒有收到確認，這集今天不上片。Not approved, so it was not posted.", False)
            log(f"Review #{issue['number']}: not approved, skipped")
