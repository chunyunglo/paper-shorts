"""Logging and HTTP helpers that are safe for a public repo's Actions logs.

Rules: logs carry counts, ids of our own posts, and endpoint names only.
Never comment text, commenter names, tokens, or full URLs (Graph API URLs
often carry access_token as a query parameter).
"""
from __future__ import annotations

import os
import sys
import time

import requests


def log(msg: str) -> None:
    print(msg, flush=True)


def mask(value: str | None) -> None:
    """Ask GitHub Actions to redact a value we learned at runtime (e.g. a refreshed token)."""
    if value and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::add-mask::{value}", flush=True)


class ApiError(RuntimeError):
    """An HTTP failure described without URL, query string, or response body."""

    def __init__(self, service: str, what: str, status: int | None, code: str | None = None):
        self.service, self.what, self.status, self.code = service, what, status, code
        super().__init__(f"{service} {what} failed (status={status}, code={code})")


def _error_code(resp: requests.Response) -> str | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        # Graph API: {"error": {"code": 190, "error_subcode": 463, "type": "OAuthException"}}
        parts = [str(err.get(k)) for k in ("code", "error_subcode", "type", "status") if err.get(k)]
        return "/".join(parts) or None
    if isinstance(err, str):
        # Google OAuth: {"error": "invalid_grant"}
        return err
    return None


def http(service: str, what: str, method: str, url: str, *, retries: int = 2,
         ok=(200, 201), **kwargs) -> requests.Response:
    """requests.request that raises ApiError with no secrets or user content in it."""
    kwargs.setdefault("timeout", 120)
    for attempt in range(retries + 1):
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.RequestException as exc:
            if attempt < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            raise ApiError(service, what, None, type(exc).__name__) from None
        if ok == "any" or resp.status_code in ok:
            return resp
        if resp.status_code >= 500 and attempt < retries:
            time.sleep(2 ** (attempt + 1))
            continue
        raise ApiError(service, what, resp.status_code, _error_code(resp)) from None
    raise AssertionError("unreachable")


def install_excepthook(strict: bool = True) -> None:
    """In strict mode (anything that touches comments), print only the exception type,
    file:line, and our own sanitized messages. Non-strict keeps normal tracebacks,
    for jobs that only handle public paper data."""
    if not strict:
        return

    def hook(exc_type, exc, tb):
        if isinstance(exc, (ApiError, SystemExit)):
            print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        else:
            # File/line info helps debugging and holds no user data.
            import traceback

            frames = traceback.extract_tb(tb)
            where = " <- ".join(f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno}" for f in reversed(frames[-6:]))
            print(f"ERROR: {exc_type.__name__} at {where}", file=sys.stderr, flush=True)
        sys.exit(1)

    sys.excepthook = hook
