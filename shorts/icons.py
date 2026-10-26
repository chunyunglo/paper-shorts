"""Topic icons from the open-source Tabler icon set (MIT), so each episode's visuals show its subject.

The script names icons with plain English keywords ("cow", "truck", "gavel"); find() maps a keyword
to an icon by name or tag. The icon package is downloaded once per run. If it can't be fetched or
drawn, every lookup returns None and the visuals fall back to their icon-free versions.
"""
from __future__ import annotations

import io
import json
import re
import tarfile
from functools import lru_cache

from PIL import Image

from .safelog import http, log

VERSION = "3.24.0"
URL = f"https://registry.npmjs.org/@tabler/icons/-/icons-{VERSION}.tgz"

_svgs: dict[str, str] | None = None
_tags: dict[str, list[str]] = {}


def _load() -> dict[str, str]:
    global _svgs
    if _svgs is not None:
        return _svgs
    _svgs = {}
    try:
        data = http("icons", "download", "GET", URL).content
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for m in tar.getmembers():
                if m.name == "package/icons.json":
                    meta = json.load(tar.extractfile(m))
                    _tags.update({k: [str(t).lower() for t in v.get("tags") or []] for k, v in meta.items()})
                elif m.name.startswith("package/icons/outline/") and m.name.endswith(".svg"):
                    _svgs[m.name.rsplit("/", 1)[1][:-4]] = tar.extractfile(m).read().decode()
        log(f"Icons: {len(_svgs)} loaded")
    except Exception as exc:  # icons are decoration; never fail an episode over them
        log(f"Icons unavailable: {exc}")
    return _svgs


def _slug(word: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", word.lower()).strip("-")


@lru_cache(maxsize=256)
def find(keyword: str) -> str | None:
    """Best icon name for a keyword: exact name, then a name starting with it, then a tag match."""
    svgs = _load()
    k = _slug(keyword)
    if not k or not svgs:
        return None
    for cand in (k, k.rstrip("s"), k.split("-")[-1]):
        if cand in svgs:
            return cand
    starts = sorted((n for n in svgs if n.startswith(k + "-") and not n.endswith("-off")), key=len)
    if starts:
        return starts[0]
    words = k.replace("-", " ")
    tagged = sorted((n for n, tags in _tags.items() if n in svgs and not n.endswith("-off")
                     and (words in tags or k in tags)), key=len)
    return tagged[0] if tagged else None


_SKIP = re.compile(r"(-off$|^brand-|-\d+$|^(letter|number|alphabet|square-|circle-|hexagon-|octagon-|"
                   r"pentagon-|triangle-|arrow|chevron|currency-|file-|calendar-|clock-|cloud-|message-|"
                   r"mail-|lock-|bell-|filter-|map-pin-|folder-|database-|shopping-|text-|align-|border-|"
                   r"layout-|table-|player-|box-|columns-|row-|zoom-|tallymark|keyframe|math-|sort-))")


def catalog() -> list[str]:
    """Icon names worth offering to the script writer (drops variants, brands, glyph sets)."""
    return sorted(n for n in _load() if not _SKIP.search(n))


def known(name: str) -> bool:
    return name in _load()


@lru_cache(maxsize=2048)
def image(name: str, size: int, color: tuple[int, int, int], stroke: float = 1.6) -> Image.Image | None:
    svg = _load().get(name)
    if not svg:
        return None
    try:
        import cairosvg

        hexcol = "#%02x%02x%02x" % color
        svg = svg.replace("currentColor", hexcol).replace('stroke-width="2"', f'stroke-width="{stroke}"')
        png = cairosvg.svg2png(bytestring=svg.encode(), output_width=size, output_height=size)
        return Image.open(io.BytesIO(png)).convert("RGBA")
    except Exception as exc:
        log(f"Icon {name} not drawn: {exc}")
        return None
