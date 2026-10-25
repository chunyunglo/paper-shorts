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

LANGS = ("zh", "en", "pt")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "episode"


def spoken(script: scriptmod.Script, lang: str) -> list[list[str]]:
    if lang == "pt":
        return [s.lines for s in script.pt.scenes]
    return [[l.zh if lang == "zh" else l.en for l in s.lines] for s in script.scenes]


def make(script_json: Path | None = None, paper_json: Path | None = None, preview_every: int = 0,
         episode_json: Path | None = None) -> Path:
    """episode_json: remake the videos of an existing episode (same paper and script)."""
    history = load_history()
    now = datetime.now(timezone.utc)
    if episode_json:
        old = json.loads(episode_json.read_text(encoding="utf-8"))
        paper, reason = papers.Paper(**old["paper"]), old.get("pick_reason", "remake")
        script = scriptmod.Script(**old["script"])
        ep_id = f"{old['episode']}-r{now:%H%M}"  # a new id, so it gets its own release and review
    else:
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
        ep_id = f"{now:%Y%m%d}-{slug(paper.title)}"
    if "pt" in LANGS and not script.pt:
        script.pt = scriptmod.translate_pt(script)
    return build(ep_id, paper, script, reason, preview_every)


def revise(episode_json: Path, feedback: str) -> tuple[Path, str]:
    """Apply the owner's review feedback: Claude rewrites the script, then every video is
    re-rendered under the same episode id (so the same release and review issue)."""
    old = json.loads(episode_json.read_text(encoding="utf-8"))
    paper = papers.Paper(**old["paper"])
    script, changes = scriptmod.revise(paper, scriptmod.Script(**old["script"]), feedback)
    return build(old["episode"], paper, script, old.get("pick_reason", ""), 0), changes


def build(ep_id: str, paper: papers.Paper, script: scriptmod.Script, reason: str, preview_every: int) -> Path:
    out = OUT / ep_id
    out.mkdir(parents=True, exist_ok=True)

    videos = {}
    for lang in LANGS:
        audio = out / f"voice_{lang}.wav"
        timings, total = tts.voiceover(spoken(script, lang), audio, lang)
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
    pt = s.get("pt")
    lines = [f"# {s['title_zh']} / {s['title_en']}" + (f" / {pt['title']}" if pt else ""), "",
             "Videos: " + ", ".join(f"{k} {v['duration']}s ({v['tts']})" for k, v in meta["videos"].items()), "",
             f"**Paper:** [{p['title']}]({p['url']}), {p['venue']} ({p['published']})", "",
             f"**Why this paper:** {meta['pick_reason']}", ""]
    for i, sc in enumerate(s["scenes"], 1):
        lines.append(f"## {i:02d} {sc['heading_zh']} / {sc['heading_en']} ({sc['visual']})")
        pt_lines = pt["scenes"][i - 1]["lines"] if pt else []
        for k, ln in enumerate(sc["lines"]):
            extra = f"  \n  🇧🇷 {pt_lines[k]}" if k < len(pt_lines) else ""
            lines.append(f"- {ln['zh']}  \n  _{ln['en']}_{extra}")
        lines.append("")
    lines += ["## Captions", "", s["description_zh"], "", s["description_en"], "",
              *([pt["description"], ""] if pt else []),
              " ".join("#" + h for h in s["hashtags"]), "",
              "## Method summary (used for replies)", "", s["method_summary"], "",
              "## Limitations", "", s["limitations"], ""]
    return "\n".join(lines)
