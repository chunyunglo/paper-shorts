"""Thin wrapper over the Anthropic SDK for structured (Pydantic) outputs."""
from __future__ import annotations

from typing import TypeVar

import anthropic
from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=4)
    return _client


def ask(schema: type[T], system: str, content: list | str, *, effort: str = "high",
        max_tokens: int = 16000) -> T:
    """One structured call. Raises RuntimeError (without echoing content) on refusal/truncation."""
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    try:
        resp = client().messages.parse(
            model=config.MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_format=schema,
            output_config={"effort": effort},
            # Server-side refusal fallback: if a safety classifier declines, the API
            # re-runs the request on a fallback model inside the same call.
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={"fallbacks": "default"},
        )
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Claude API error status={exc.status_code}") from None
    except anthropic.APIConnectionError:
        raise RuntimeError("Claude API connection error") from None
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined the request")
    if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
        raise RuntimeError(f"Claude output incomplete (stop_reason={resp.stop_reason})")
    return resp.parsed_output
