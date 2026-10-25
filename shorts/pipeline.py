"""make: pick a paper -> script -> voiceover -> video, all into out/<episode>/."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import brand, papers, render, script as scriptmod, tts
from .config import OUT
from .safelog import log
from .state import load_history

LANGS = ("zh", "en")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "episode"


def make(script_json: Path | None = None, paper_json: Path | None = None, preview_every: int = 0) -> Path:
    history = load_history()
    if paper_json:
        paper = papers.Paper.model_validate_json(paper_json.read_text(encoding="utf-8"))
        reason = "given"
    else:
        paper, reason = papers.pick(papers.candidates(history), history)
    if script_json:
        script = scriptmod.Script.model_validate_json(script_json.read_text(encoding="utf-8"))
        scriptmod.validate(script)
    else:
        script = scriptmod.write(paper)

    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    ep_id = f"{date}-{slug(paper.title)}"
    out = OUT / ep_id
    out.mkdir(parents=True, exist_ok=True)

    videos = {}
    for lang in LANGS:
        audio = out / f"voice_{lang}.wav"
        lines = [[l.zh if lang == "zh" else l.en for l in s.lines] for s in script.scenes]
        timings, total = tts.voiceover(lines, audio, lang)
        log(f"Voiceover ({lang}): {total:.1f}s")
        r = render.Renderer(script, paper.model_dump(), timings, total, lang)
        render.encode(r, audio, out / f"video_{lang}.mp4", preview_every=preview_every)
        cover_at = brand.INTRO + timings[1 if len(timings) > 1 else 0].start + 1.2
        r.frame(int(cover_at * 30)).convert("RGB").save(out / f"cover_{lang}.jpg", quality=90)
        videos[lang] = {"file": f"video_{lang}.mp4", "duration": round(r.duration, 2),
                        "cover_offset_ms": int(cover_at * 1000), "tts": " ".join(tts.choose(lang)).strip()}

    meta = {
        "episode": ep_id,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "paper": paper.model_dump(),
        "pick_reason": reason,
        "script": script.model_dump(),
        "videos": videos,
    }
    (out / "episode.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "script.md").write_text(script_markdown(meta), encoding="utf-8")
    log(f"Episode ready: {out.relative_to(OUT.parent)}")
    return out


def script_markdown(meta: dict) -> str:
    s, p = meta["script"], meta["paper"]
    lines = [f"# {s['title_zh']} / {s['title_en']}", "",
             "Videos: " + ", ".join(f"{k} {v['duration']}s ({v['tts']})" for k, v in meta["videos"].items()), "",
             f"**Paper:** [{p['title']}]({p['url']}), {p['venue']} ({p['published']})", "",
             f"**Why this paper:** {meta['pick_reason']}", ""]
    for i, sc in enumerate(s["scenes"], 1):
        lines.append(f"## {i:02d} {sc['heading_zh']} / {sc['heading_en']} ({sc['visual']})")
        for ln in sc["lines"]:
            lines.append(f"- {ln['zh']}  \n  _{ln['en']}_")
        lines.append("")
    lines += ["## Captions", "", s["description_zh"], "", s["description_en"], "",
              " ".join("#" + h for h in s["hashtags"]), "",
              "## Method summary (used for replies)", "", s["method_summary"], "",
              "## Limitations", "", s["limitations"], ""]
    return "\n".join(lines)
