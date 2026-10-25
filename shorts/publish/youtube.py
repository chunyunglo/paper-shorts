"""YouTube Data API v3: OAuth refresh, resumable upload, and the comment calls used by comments.py."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .. import config
from ..safelog import ApiError, http, log

API = "https://www.googleapis.com/youtube/v3"


@lru_cache(maxsize=1)
def access_token() -> str:
    try:
        resp = http("youtube", "token refresh", "POST", "https://oauth2.googleapis.com/token", data={
            "client_id": config.require("YOUTUBE_CLIENT_ID"),
            "client_secret": config.require("YOUTUBE_CLIENT_SECRET"),
            "refresh_token": config.require("YOUTUBE_REFRESH_TOKEN"),
            "grant_type": "refresh_token",
        }, retries=1)
    except ApiError as exc:
        if exc.code == "invalid_grant":
            raise SystemExit("YouTube refresh token was rejected (invalid_grant). It may have expired "
                             "(tokens made while the OAuth app was in Testing last 7 days). Re-run the "
                             "YouTube login script and update the YOUTUBE_REFRESH_TOKEN secret.") from None
        raise
    return resp.json()["access_token"]


def _auth() -> dict:
    return {"Authorization": f"Bearer {access_token()}"}


def upload(video: Path, title: str, description: str, tags: list[str], lang: str = "zh") -> str:
    language = {"zh": ("zh-Hant", "zh-TW"), "en": ("en", "en")}[lang]
    meta = {
        "snippet": {"title": title, "description": description, "tags": tags[:15], "categoryId": "27",
                    "defaultLanguage": language[0], "defaultAudioLanguage": language[1]},
        "status": {"privacyStatus": config.env("YOUTUBE_PRIVACY", "public"),
                   "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
    }
    size = video.stat().st_size
    start = http("youtube", "upload init", "POST",
                 "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                 headers=_auth() | {"Content-Type": "application/json; charset=UTF-8",
                                    "X-Upload-Content-Type": "video/mp4",
                                    "X-Upload-Content-Length": str(size)},
                 data=json.dumps(meta, ensure_ascii=False).encode("utf-8"))
    session = start.headers["Location"]
    with video.open("rb") as fh:
        done = http("youtube", "upload bytes", "PUT", session, timeout=900,
                    headers={"Content-Type": "video/mp4", "Content-Length": str(size)}, data=fh)
    video_id = done.json()["id"]
    log(f"YouTube: uploaded video {video_id}")
    return video_id


@lru_cache(maxsize=1)
def my_channel_id() -> str:
    resp = http("youtube", "channels.list", "GET", f"{API}/channels",
                params={"part": "id", "mine": "true"}, headers=_auth())
    return resp.json()["items"][0]["id"]


def comment_threads(video_id: str) -> list[dict]:
    """Top-level comments with their replies (newest first, up to 100)."""
    resp = http("youtube", "commentThreads.list", "GET", f"{API}/commentThreads", headers=_auth(),
                params={"part": "snippet,replies", "videoId": video_id, "maxResults": 100,
                        "order": "time", "textFormat": "plainText"}, ok=(200, 403))
    if resp.status_code == 403:
        reasons = [e.get("reason") for e in resp.json().get("error", {}).get("errors", [])]
        if "commentsDisabled" in reasons:
            return []
        raise ApiError("youtube", "commentThreads.list", 403, ",".join(r for r in reasons if r) or None)
    return resp.json().get("items", [])


def reply(parent_id: str, text: str) -> None:
    http("youtube", "comments.insert", "POST", f"{API}/comments", params={"part": "snippet"},
         headers=_auth(), json={"snippet": {"parentId": parent_id, "textOriginal": text}})


def hide(comment_id: str) -> None:
    # "heldForReview" removes it from public view but keeps it in YouTube Studio for a manual check.
    http("youtube", "comments.setModerationStatus", "POST", f"{API}/comments/setModerationStatus",
         headers=_auth(), params={"id": comment_id, "moderationStatus": "heldForReview"}, ok=(200, 204))
