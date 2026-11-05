"""Thin wrapper over the Anthropic SDK for structured (Pydantic) outputs."""
from __future__ import annotations

from typing import TypeVar

import anthropic
from pydantic import BaseModel

from . import config
from .safelog import log

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None

# US$ per million tokens (input, output, cache read), for the cost line in each run's log
PRICES = {"claude-opus-5-5": (4.0, 20.0, 0.20)}
_spent = {"calls": 0, "usd": 0.0}


def cost(model: str, usage) -> float:
    """Cache writes (5-minute) bill at 1.25x input, cache reads at the cache rate."""
    inp, out, cached = PRICES.get(model, PRICES["claude-opus-5-5"])
    written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return ((usage.input_tokens or 0) * inp + written * inp * 1.25 + (usage.output_tokens or 0) * out
            + (getattr(usage, "cache_read_input_tokens", 0) or 0) * cached) / 1e6


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
    usd = cost(config.MODEL, resp.usage)
    _spent["calls"] += 1
    _spent["usd"] += usd
    # No summary line at exit: some workflows read the last line of output as the episode folder.
    u = resp.usage
    cached = (f" (+{getattr(u, 'cache_read_input_tokens', 0) or 0} cached, "
              f"{getattr(u, 'cache_creation_input_tokens', 0) or 0} cache write)")
    log(f"Claude call: {u.input_tokens} in{cached}, {u.output_tokens} out, about US${usd:.3f} "
        f"(run so far: {_spent['calls']} calls, US${_spent['usd']:.2f})")
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined the request")
    if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
        raise RuntimeError(f"Claude output incomplete (stop_reason={resp.stop_reason})")
    return resp.parsed_output
