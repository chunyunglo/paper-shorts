"""Tell the owner that some comments need a human, without making comment content public.

Email (SMTP) is the main channel. Fallback when email is not set up or fails:
1. Details (comment text, author, Claude's note, a suggested reply) go to a PRIVATE place:
   an issue in the private inbox repo (GH_PAT; ALERT_REPO, default <owner>/paper-shorts-inbox),
   and/or an email via SMTP (ALERT_EMAIL_USER / ALERT_EMAIL_APP_PASSWORD / ALERT_EMAIL_TO).
2. A pointer issue in this public repo, opened by the Actions bot (GITHUB_TOKEN), so GitHub
   actually notifies the owner. It holds only counts and links: the private issue and the
   public posts the comments are under. No comment text or names.
Returns True if the owner was notified. Nothing about the comments is logged.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from . import config
from .safelog import ApiError, http, log


def _gh(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _private_issue(title: str, body: str) -> str | None:
    pat = config.env("GH_PAT")
    repo = config.env("ALERT_REPO") or config.GITHUB_REPO.split("/")[0] + "/paper-shorts-inbox"
    if not pat:
        return None
    meta = http("github", "alert repo check", "GET", f"https://api.github.com/repos/{repo}",
                headers=_gh(pat), ok=(200, 404))
    if meta.status_code == 404 or not meta.json().get("private"):
        log("Private alert repo missing or not private; skipped detailed issue")
        return None
    resp = http("github", "create alert issue", "POST", f"https://api.github.com/repos/{repo}/issues",
                headers=_gh(pat), json={"title": title, "body": body})
    return resp.json()["html_url"]


def _smtp(title: str, body: str) -> bool:
    user, pw, to = (config.env(k) for k in ("ALERT_EMAIL_USER", "ALERT_EMAIL_APP_PASSWORD", "ALERT_EMAIL_TO"))
    if not (user and pw and to):
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = title, user, to
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL(config.env("SMTP_HOST", "smtp.gmail.com"), 465, timeout=60) as s:
            s.login(user, pw)
            s.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        log(f"SMTP alert failed ({type(exc).__name__})")
        return False
    return True


def _pointer(count: int, private_url: str | None, post_links: list[str]) -> bool:
    token = config.env("GITHUB_TOKEN")
    if not token:
        return False
    lines = [f"有 {count} 則留言需要你親自處理（沒有自動回覆）。{count} comment(s) need you."]
    if private_url:
        lines.append(f"\n詳細內容與建議回覆（私人）：{private_url}")
    lines.append("\n留言所在的貼文 Posts:\n" + "\n".join(f"- {u}" for u in sorted(set(post_links))))
    lines.append("\n處理完把這則關掉即可。Close this when done.")
    http("github", "create pointer issue", "POST",
         f"https://api.github.com/repos/{config.GITHUB_REPO}/issues", headers=_gh(token),
         json={"title": f"[留言] {count} 則需要你處理", "body": "\n".join(lines),
               "assignees": [config.GITHUB_REPO.split("/")[0]]})
    return True


def alert(title: str, body: str, count: int, post_links: list[str]) -> bool:
    """Email first. Only if email is not configured or fails, use the private issue + public pointer."""
    if _smtp(title, body):
        return True
    private_url = None
    try:
        private_url = _private_issue(title, body)
    except ApiError as exc:
        log(f"Private alert failed: {exc}")
    # The pointer only names the posts, never the comments, so it is safe even without a private channel.
    try:
        return _pointer(count, private_url, post_links)
    except ApiError as exc:
        log(f"Pointer issue failed: {exc}")
        return False
