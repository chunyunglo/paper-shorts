"""YouTube Data API v3: OAuth refresh, resumable upload, and the comment calls used by comments.py."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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


def upload(video: Path, title: str, description: str, tags: list[str], lang: str = "zh",
           publish_at: str | None = None) -> str:
    """publish_at (RFC 3339, UTC): upload as private and let YouTube make it public then."""
    language = {"zh": ("zh-Hant", "zh-TW"), "en": ("en", "en"), "pt": ("pt-BR", "pt-BR")}[lang]
    status = {"privacyStatus": config.env("YOUTUBE_PRIVACY", "public"),
              "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
    if publish_at:
        status |= {"privacyStatus": "private", "publishAt": publish_at}
    meta = {
        "snippet": {"title": title, "description": description, "tags": tags[:15], "categoryId": "27",
                    "defaultLanguage": language[0], "defaultAudioLanguage": language[1]},
        "status": status,
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


def comment(video_id: str, text: str) -> None:
    """A top-level comment from the channel (used for the citation under each video)."""
    http("youtube", "commentThreads.insert", "POST", f"{API}/commentThreads", params={"part": "snippet"},
         headers=_auth(), json={"snippet": {"videoId": video_id,
                                            "topLevelComment": {"snippet": {"textOriginal": text}}}})


def search_videos(q: str, lang: str, days: int = 30, limit: int = 10) -> list[dict]:
    """Recent public videos for a search phrase (100 quota units per call)."""
    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    resp = http("youtube", "search.list", "GET", f"{API}/search", headers=_auth(),
                params={"part": "snippet", "q": q, "type": "video", "maxResults": limit, "order": "relevance",
                        "publishedAfter": after, "safeSearch": "strict",
                        "relevanceLanguage": {"zh": "zh-Hant", "en": "en"}.get(lang, lang)})
    return [{"id": it["id"]["videoId"], "title": it["snippet"].get("title", ""),
             "description": it["snippet"].get("description", ""), "channel": it["snippet"].get("channelId", "")}
            for it in resp.json().get("items", []) if it.get("id", {}).get("videoId")]


def delete(video_id: str) -> None:
    http("youtube", "videos.delete", "DELETE", f"{API}/videos", params={"id": video_id},
         headers=_auth(), ok=(204,))


def reply(parent_id: str, text: str) -> None:
    http("youtube", "comments.insert", "POST", f"{API}/comments", params={"part": "snippet"},
         headers=_auth(), json={"snippet": {"parentId": parent_id, "textOriginal": text}})


def hide(comment_id: str) -> None:
    # "heldForReview" removes it from public view but keeps it in YouTube Studio for a manual check.
    http("youtube", "comments.setModerationStatus", "POST", f"{API}/comments/setModerationStatus",
         headers=_auth(), params={"id": comment_id, "moderationStatus": "heldForReview"}, ok=(200, 204))


def set_thumbnail(video_id: str, image: Path) -> None:
    """Needs a phone-verified channel; callers treat a failure as non-fatal."""
    http("youtube", "thumbnails.set", "POST", "https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
         params={"videoId": video_id}, headers=_auth() | {"Content-Type": "image/jpeg"}, data=image.read_bytes())


def video_stats(video_ids: list[str]) -> dict[str, dict]:
    """Public counters (views, likes, comments) and length, by video id. Any YouTube scope works."""
    out: dict[str, dict] = {}
    for i in range(0, len(video_ids), 50):
        resp = http("youtube", "videos.list", "GET", f"{API}/videos", headers=_auth(),
                    params={"part": "statistics,contentDetails,status,snippet", "id": ",".join(video_ids[i:i + 50]),
                            "maxResults": 50})
        for v in resp.json().get("items", []):
            st = v.get("statistics", {})
            out[v["id"]] = {"views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                            "comments": int(st.get("commentCount", 0)),
                            "duration": v.get("contentDetails", {}).get("duration"),
                            "privacy": v.get("status", {}).get("privacyStatus"),
                            "published": v.get("snippet", {}).get("publishedAt")}
    return out


def channel_stats() -> dict:
    resp = http("youtube", "channels.list", "GET", f"{API}/channels", headers=_auth(),
                params={"part": "statistics", "mine": "true"})
    st = resp.json()["items"][0].get("statistics", {})
    return {k: int(st.get(k, 0)) for k in ("subscriberCount", "viewCount", "videoCount")}


ANALYTICS_METRICS = ("views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                     "likes,comments,shares,subscribersGained")


def analytics_by_video(video_ids: list[str], start: str, end: str) -> dict[str, dict] | None:
    """YouTube Analytics (watch time, retention, subscribers gained) per video.
    Returns None when the refresh token was made without the yt-analytics.readonly scope."""
    out: dict[str, dict] = {}
    for i in range(0, len(video_ids), 200):
        resp = http("youtube", "analytics reports", "GET", "https://youtubeanalytics.googleapis.com/v2/reports",
                    headers=_auth(), ok=(200, 401, 403),
                    params={"ids": "channel==MINE", "startDate": start, "endDate": end, "dimensions": "video",
                            "metrics": ANALYTICS_METRICS, "filters": "video==" + ",".join(video_ids[i:i + 200]),
                            "maxResults": 200})
        if resp.status_code in (401, 403):
            return None
        data = resp.json()
        names = [h["name"] for h in data.get("columnHeaders", [])]
        for row in data.get("rows", []):
            rec = dict(zip(names, row))
            out[rec.pop("video")] = rec
    return out
