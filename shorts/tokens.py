"""Keep long-lived tokens and schedules alive.

refresh_all: Instagram and Threads long-lived tokens last 60 days. Refreshing returns a new
60-day token, which we store back into the repo's Actions secrets with GH_PAT (a fine-grained
token with Secrets: read and write on this repo). Run a few times a week.

keepalive: GitHub disables scheduled workflows in public repos after 60 days without repo
activity. Re-enabling them through the API resets that clock.
"""
from __future__ import annotations

import base64

from . import config
from .safelog import ApiError, http, log, mask

WORKFLOWS = ["publish.yml", "comments.yml", "maintenance.yml"]


def _gh(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def set_secret(name: str, value: str) -> None:
    from nacl import encoding, public

    pat = config.require("GH_PAT")
    base = f"https://api.github.com/repos/{config.GITHUB_REPO}/actions/secrets"
    key = http("github", "secrets public key", "GET", f"{base}/public-key", headers=_gh(pat)).json()
    box = public.SealedBox(public.PublicKey(key["key"].encode(), encoding.Base64Encoder()))
    sealed = base64.b64encode(box.encrypt(value.encode())).decode()
    http("github", f"set secret {name}", "PUT", f"{base}/{name}", headers=_gh(pat),
         json={"encrypted_value": sealed, "key_id": key["key_id"]}, ok=(201, 204))


def refresh_instagram() -> str:
    token = config.require("IG_ACCESS_TOKEN")
    if token.startswith("IG"):
        resp = http("instagram", "token refresh", "GET", "https://graph.instagram.com/refresh_access_token",
                    params={"grant_type": "ig_refresh_token", "access_token": token})
    else:
        resp = http("instagram", "token exchange", "GET",
                    f"https://graph.facebook.com/{config.GRAPH_VERSION}/oauth/access_token",
                    params={"grant_type": "fb_exchange_token", "client_id": config.require("META_APP_ID"),
                            "client_secret": config.require("META_APP_SECRET"), "fb_exchange_token": token})
    return resp.json()["access_token"]


def refresh_threads() -> str:
    resp = http("threads", "token refresh", "GET", "https://graph.threads.net/refresh_access_token",
                params={"grant_type": "th_refresh_token", "access_token": config.require("THREADS_ACCESS_TOKEN")})
    return resp.json()["access_token"]


def refresh_all() -> None:
    if not config.env("GH_PAT"):
        raise SystemExit("GH_PAT secret is missing, so refreshed tokens cannot be saved. Add a fine-grained "
                         "token with Secrets: read and write on this repo as GH_PAT.")
    failed = []
    for secret, fn in (("IG_ACCESS_TOKEN", refresh_instagram), ("THREADS_ACCESS_TOKEN", refresh_threads)):
        try:
            new = fn()
            mask(new)
            set_secret(secret, new)
            log(f"{secret}: refreshed and saved")
        except (ApiError, SystemExit, KeyError) as exc:
            log(f"{secret}: refresh FAILED - {exc}")
            failed.append(secret)
    if failed:
        raise SystemExit(f"Token refresh failed for {', '.join(failed)}; they expire 60 days after the last refresh")


def keepalive() -> None:
    token = config.env("GITHUB_TOKEN") or config.require("GH_PAT")
    for wf in WORKFLOWS:
        url = f"https://api.github.com/repos/{config.GITHUB_REPO}/actions/workflows/{wf}/enable"
        try:
            http("github", f"enable {wf}", "PUT", url, headers=_gh(token), ok=(204,))
            log(f"{wf}: enabled")
        except ApiError as exc:
            log(f"{wf}: keepalive failed - {exc}")
