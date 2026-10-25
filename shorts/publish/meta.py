"""Instagram (Reels) and Threads publishing and comment calls.

Instagram tokens from "Instagram API with Instagram Login" start with IGAA and use
graph.instagram.com; Facebook-login tokens (EAA...) use graph.facebook.com. Both
take the same parameters for the calls used here.
"""
from __future__ import annotations

import time

from .. import config
from ..safelog import ApiError, http, log


# ---------------------------------------------------------------- Instagram

def ig_base() -> str:
    token = config.require("IG_ACCESS_TOKEN")
    host = "graph.instagram.com" if token.startswith("IG") else "graph.facebook.com"
    return f"https://{host}/{config.GRAPH_VERSION}"


def ig(method: str, path: str, what: str, **params) -> dict:
    params["access_token"] = config.require("IG_ACCESS_TOKEN")
    kw = {"params": params} if method == "GET" else {"data": params}
    return http("instagram", what, method, f"{ig_base()}/{path}", **kw).json()


def _wait(check, service: str, timeout: int = 900) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = check()
        if status in ("FINISHED", "PUBLISHED"):
            return
        if status in ("ERROR", "EXPIRED"):
            raise ApiError(service, "media processing", None, status)
        time.sleep(10)
    raise ApiError(service, "media processing", None, "timeout")


def ig_publish_reel(video_url: str, caption: str, thumb_offset_ms: int) -> tuple[str, str]:
    uid = config.require("IG_USER_ID")
    container = ig("POST", f"{uid}/media", "create reel container", media_type="REELS",
                   video_url=video_url, caption=caption, share_to_feed="true",
                   thumb_offset=str(thumb_offset_ms))["id"]
    _wait(lambda: ig("GET", container, "container status", fields="status_code").get("status_code"),
          "instagram")
    media_id = ig("POST", f"{uid}/media_publish", "publish reel", creation_id=container)["id"]
    link = ig("GET", media_id, "permalink", fields="permalink").get("permalink", "")
    log(f"Instagram: published reel {media_id}")
    return media_id, link


def ig_username() -> str:
    return ig("GET", config.require("IG_USER_ID"), "username", fields="username")["username"]


def ig_comments(media_id: str) -> list[dict]:
    data = ig("GET", f"{media_id}/comments", "list comments", limit=50,
              fields="id,text,timestamp,username,hidden,replies{id,username}")
    return data.get("data", [])


def ig_reply(comment_id: str, text: str) -> None:
    ig("POST", f"{comment_id}/replies", "reply", message=text)


def ig_hide(comment_id: str) -> None:
    ig("POST", comment_id, "hide comment", hide="true")


# ---------------------------------------------------------------- Threads

THREADS = f"https://graph.threads.net/{config.THREADS_VERSION}"


def th(method: str, path: str, what: str, **params) -> dict:
    params["access_token"] = config.require("THREADS_ACCESS_TOKEN")
    kw = {"params": params} if method == "GET" else {"data": params}
    return http("threads", what, method, f"{THREADS}/{path}", **kw).json()


def th_publish(container: str) -> str:
    _wait(lambda: th("GET", container, "container status", fields="status").get("status"), "threads")
    return th("POST", f"{config.require('THREADS_USER_ID')}/threads_publish", "publish",
              creation_id=container)["id"]


def th_publish_video(video_url: str, text: str) -> tuple[str, str]:
    uid = config.require("THREADS_USER_ID")
    container = th("POST", f"{uid}/threads", "create video container", media_type="VIDEO",
                   video_url=video_url, text=text)["id"]
    post_id = th_publish(container)
    link = th("GET", post_id, "permalink", fields="permalink").get("permalink", "")
    log(f"Threads: published post {post_id}")
    return post_id, link


def th_username() -> str:
    return th("GET", "me", "username", fields="username")["username"]


def th_replies(post_id: str) -> list[dict]:
    """Whole conversation under our post, flattened (includes our own replies)."""
    data = th("GET", f"{post_id}/conversation", "list replies", reverse="false",
              fields="id,text,timestamp,username,hide_status,replied_to,is_reply_owned_by_me")
    return data.get("data", [])


def th_reply(reply_to: str, text: str) -> None:
    uid = config.require("THREADS_USER_ID")
    container = th("POST", f"{uid}/threads", "create reply", media_type="TEXT", text=text,
                   reply_to_id=reply_to)["id"]
    th_publish(container)


def th_hide(reply_id: str) -> None:
    th("POST", f"{reply_id}/manage_reply", "hide reply", hide="true")
