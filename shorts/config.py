"""Shared settings. Everything that differs between runs comes from env vars."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "out"
ASSETS = ROOT / "assets"
HISTORY_FILE = DATA / "history.json"

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

# Brand palette, taken from the avatar.
CREAM = (246, 239, 227)
NAVY = (29, 42, 92)
CORAL = (255, 107, 74)
NAVY_SOFT = (29, 42, 92, 70)
INK_MUTED = (90, 98, 130)

W, H, FPS = 1080, 1920, 30

BRAND_ZH = "行為解碼"
BRAND_EN = "Behavior Decoded"
HANDLE = "@human__behavior__decode"

GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v24.0")
THREADS_VERSION = os.environ.get("THREADS_VERSION", "v1.0")

GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY", "chunyunglo/paper-shorts")


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value if value else default


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing required secret/env: {name}")
    return value
