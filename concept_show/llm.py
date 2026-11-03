"""Structured Claude calls for the concept show. Kept separate from shorts/ so the two lines don't
depend on each other. Logs token counts and cost only, never prompt or output text."""
from __future__ import annotations

import atexit
import os
from typing import TypeVar

import anthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
PRICE = (4.0, 20.0)  # US$ per million input, output tokens
MAX_TOKENS = 20000  # higher values make the SDK insist on streaming
_spent = {"calls": 0, "usd": 0.0}
_client: anthropic.Anthropic | None = None


@atexit.register
def _report() -> None:
    if _spent["calls"]:
        print(f"Claude cost this run: {_spent['calls']} calls, about US${_spent['usd']:.2f}", flush=True)


def ask(schema: type[T], system: str, text: str, *, effort: str = "high") -> T:
    global _client
    _client = _client or anthropic.Anthropic(max_retries=4)
    try:
        resp = _client.messages.parse(
            model=MODEL, max_tokens=MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": [{"type": "text", "text": text}]}],
            output_format=schema, output_config={"effort": effort})
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Claude API error status={exc.status_code}") from None
    except anthropic.APIConnectionError:
        raise RuntimeError("Claude API connection error") from None
    u = resp.usage
    usd = ((u.input_tokens or 0) * PRICE[0] + (u.output_tokens or 0) * PRICE[1]) / 1e6
    _spent["calls"] += 1
    _spent["usd"] += usd
    print(f"Claude call: {u.input_tokens} in, {u.output_tokens} out, about US${usd:.3f}", flush=True)
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined the request")
    if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
        raise RuntimeError(f"Claude output incomplete (stop_reason={resp.stop_reason})")
    return resp.parsed_output
