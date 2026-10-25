"""Owner review before publishing.

prepare (afternoon): the episode's videos go on a pre-release, and the Actions bot opens a review
issue in this repo. Because the bot (not the owner) opens it, GitHub notifies the owner by email
and app push. (Issues the owner's own token creates never notify the owner.)
revise (any time): any other owner comment is feedback. revise.yml has Claude rewrite the script,
re-renders every video onto the same release, and posts the new version on the issue.
publish (evening): only if the owner's latest comment on that issue is an approval (e.g. "OK",
"沒問題") does the episode go out. Otherwise nothing is posted and the issue is closed as skipped.
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
REJECTIONS = {"不要上", "不上", "先不要", "取消", "skip", "不要", "no", "cancel"}
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


def kind(text: str) -> str:
    """What an owner comment on a review issue means: approve, reject, or feedback (revise)."""
    t = re.sub(r"[\s。.!！~～,，]+$", "", text.strip().lower())
    if not t:
        return "reject"
    if is_approval(text):
        return "approve"
    if t in REJECTIONS:
        return "reject"
    return "feedback"


def videos_md(ep: dict, base: str, version: str = "") -> str:
    name = {"zh": "中文版", "en": "English", "pt": "Português (BR)"}
    q = f"?v={version}" if version else ""
    rows = "\n".join(f"- **{name.get(lang, lang)}**（{v['duration']:.0f} 秒）：[{v['file']}]({base}/{v['file']}{q})"
                     for lang, v in ep["videos"].items())
    covers = " ".join(f'<img src="{base}/cover_{lang}.jpg{q}" width="200">' for lang in ep["videos"])
    return f"{rows}\n\n{covers}"


def news_md(n: dict | None) -> str:
    if not n:
        return "### 時事連結 News hook\n這集沒有找到合適的時事，用一般開場。\n\n"
    return f"### 時事連結 News hook\n{n['title']}（{n['source']}，{n['published']}）\n{n['link']}\n\n"


def open_review(folder: Path, tag: str) -> int:
    ep = json.loads((folder / "episode.json").read_text(encoding="utf-8"))
    s, p = ep["script"], ep["paper"]
    base = f"https://github.com/{config.GITHUB_REPO}/releases/download/{tag}"
    when = os.environ.get("PUBLISH_AT", "今晚 19:00")
    body = (f"## {s['title_zh']} / {s['title_en']}\n\n"
            f"回覆 **OK** 或 **沒問題**，就會上片到 YouTube、Instagram、Threads：{when}。\n"
            f"想修改就直接留言寫要改什麼（例如「第三段講太快」「標題換成…」），"
            f"Claude 會改腳本、重做三支影片，約 10 分鐘後在這裡貼新版本，你再回 OK。\n"
            f"回「不要上」或不回覆，這集就不上片。\n\n"
            f"Reply **OK** to publish ({when}). Write what to change and a revised version is posted here. "
            f"No reply means no post.\n\n"
            f"### 影片 Videos\n{videos_md(ep, base)}\n\n"
            f"### 論文 Paper\n[{p['title']}]({p['url']}), {p['venue']} ({p['published']})\n\n"
            f"{news_md(ep.get('news'))}"
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


def _is_approved(issue: dict) -> bool:
    """The owner's latest comment decides: feedback after an OK means the new version needs its own OK."""
    comments = http("github", "list review comments", "GET", issue["comments_url"], headers=_gh(),
                    params={"per_page": 100}).json()
    mine = [c for c in comments if c["user"]["login"] == owner()]
    return bool(mine) and kind(mine[-1].get("body", "")) == "approve"


def tag_of(number: int) -> str:
    issue = http("github", "get review issue", "GET",
                 f"https://api.github.com/repos/{inbox()}/issues/{number}", headers=_gh()).json()
    m = MARKER.search(issue.get("body") or "")
    if not m:
        raise SystemExit(f"Issue #{number} is not a review issue")
    return m.group(1)


def post_revision(number: int, folder: Path, tag: str, changes: str, version: str) -> None:
    ep = json.loads((folder / "episode.json").read_text(encoding="utf-8"))
    s = ep["script"]
    base = f"https://github.com/{config.GITHUB_REPO}/releases/download/{tag}"
    body = (f"## 新版本 Revised version\n\n**{s['title_zh']}** / {s['title_en']}\n\n"
            f"### 改了什麼\n{changes or '-'}\n\n### 影片 Videos\n{videos_md(ep, base, version)}\n\n"
            f"<details><summary>腳本 Script</summary>\n\n{(folder / 'script.md').read_text(encoding='utf-8')}\n</details>\n\n"
            f"沒問題就回 **OK**；還要改就再留言。Reply **OK** to publish, or comment again to revise.")
    http("github", "comment revision", "POST", f"https://api.github.com/repos/{inbox()}/issues/{number}/comments",
         headers=_gh(), json={"body": body})


def comment(number: int, text: str) -> None:
    http("github", "comment on review", "POST", f"https://api.github.com/repos/{inbox()}/issues/{number}/comments",
         headers=_gh(), json={"body": text})


def approved() -> list[tuple[int, str]]:
    """(issue number, release tag) for each open review the owner approved."""
    out = []
    for issue in _open_reviews():
        if _is_approved(issue):
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
        if not _is_approved(issue):
            close(issue["number"], "沒有收到確認，這集今天不上片。Not approved, so it was not posted.", False)
            log(f"Review #{issue['number']}: not approved, skipped")
