"""Send a private alert to the owner about a comment that needs a human.

Two channels, used in this order:
  1. An issue in a PRIVATE repo (ALERT_REPO, default <owner>/paper-shorts-inbox) via GH_PAT.
     GitHub emails the owner about new issues there, and nobody else can read them.
  2. SMTP (ALERT_EMAIL_USER / ALERT_EMAIL_APP_PASSWORD / ALERT_EMAIL_TO), e.g. a Gmail app password.
Returns True if at least one channel delivered. Nothing about the comment is ever logged.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from . import config
from .safelog import ApiError, http, log


def _issue(title: str, body: str) -> bool:
    pat = config.env("GH_PAT")
    repo = config.env("ALERT_REPO", config.GITHUB_REPO.split("/")[0] + "/paper-shorts-inbox")
    if not pat:
        return False
    meta = http("github", "alert repo check", "GET", f"https://api.github.com/repos/{repo}",
                headers=_gh(pat), ok=(200, 404))
    if meta.status_code == 404 or not meta.json().get("private"):
        log("Alert repo missing or not private; skipped issue alert")
        return False
    http("github", "create alert issue", "POST", f"https://api.github.com/repos/{repo}/issues",
         headers=_gh(pat), json={"title": title, "body": body, "labels": ["needs-you"]})
    return True


def _gh(pat: str) -> dict:
    return {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


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


def alert(title: str, body: str) -> bool:
    try:
        if _issue(title, body):
            return True
    except ApiError as exc:
        log(f"Issue alert failed: {exc}")
    return _smtp(title, body)
