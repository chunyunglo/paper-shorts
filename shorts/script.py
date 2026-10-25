"""Turn a paper into a bilingual short-video script with a scene plan."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from . import llm
from .papers import Paper
from .safelog import log

Visual = Literal["hook", "paper", "crowd", "network", "pipeline", "bars", "timeline",
                 "scatter", "contrast", "takeaway"]


class Line(BaseModel):
    zh: str = Field(description="One spoken subtitle line in Traditional Chinese (Taiwan), 6-22 characters")
    en: str = Field(description="Natural English rendering of the same line, at most 60 characters")


class Scene(BaseModel):
    visual: Visual
    heading_zh: str = Field(description="2-6 character label shown above the visual, e.g. 資料、方法、發現")
    heading_en: str = Field(description="1-3 word English label, e.g. THE DATA")
    labels: list[str] = Field(description="0-4 very short on-screen labels (each at most 10 zh characters or 16 latin characters) used by the visual")
    values: list[float] = Field(description="Numbers for bars/contrast/timeline ONLY if stated in the paper, same order as labels; otherwise empty")
    big_text: str = Field(description="Optional big text for hook/contrast/takeaway (a number like '3.2倍' or a short phrase); empty if unused")
    lines: list[Line] = Field(description="1-4 narration lines spoken during this scene")


class Script(BaseModel):
    title_zh: str = Field(description="Catchy Traditional Chinese title, at most 28 characters")
    title_en: str = Field(description="English title, at most 60 characters")
    paper_title_zh: str = Field(description="Faithful Traditional Chinese translation of the paper title, at most 40 characters")
    scenes: list[Scene] = Field(description="6-9 scenes; the second scene must be visual 'paper'; the last must be 'takeaway'")
    description_zh: str = Field(description="2-4 sentence Traditional Chinese video description")
    description_en: str = Field(description="2-4 sentence English video description")
    hashtags: list[str] = Field(description="5-8 hashtags without the # sign, mixing Chinese and English")
    method_summary: str = Field(description="English summary of the method, data, and main findings for answering viewer questions later (120-250 words)")
    limitations: str = Field(description="English summary of limitations / what the paper does NOT show (40-120 words)")


SYSTEM = """You write one-minute vertical explainer videos for "行為解碼 Behavior Decoded". \
Each episode explains HOW one new study used a computational method to learn something about \
human behavior. Audience: curious Taiwanese and international viewers, not specialists.

Narration is spoken in Traditional Chinese (Taiwan usage and vocabulary, e.g. 資料 not 数据, \
網路, 演算法, 影片), with English subtitles under each line. Write the Chinese for the ear: short, \
concrete, conversational, no jargon without a plain-words gloss. The English is a natural \
rendering, not word-for-word.

Structure (about 230-300 Chinese characters of narration in total, roughly 50-60 seconds):
1. hook: a question or surprising fact that makes people stay (big_text = the hook in a few words).
2. paper: who did this study and where it was published (keep it to one line).
3-6. the method, step by step: what data, what the computer did with it, how they tested it. \
This is the heart of the channel; spend the most time here. Pick visuals that fit each step: \
crowd (people/participants/accounts), network (connections, spread, communities), pipeline \
(a 2-4 step process; labels = the step names), bars (comparing groups), timeline (change over \
time), scatter (a relationship between two measures), contrast (A vs B; labels = the two sides, \
big_text = the key difference).
7. the finding, and one honest caveat.
8. takeaway: one sentence to remember (big_text), then invite viewers to follow for two papers a week.

Accuracy rules: use only facts from the provided paper. Never invent numbers, sample sizes, or \
effects; values must be empty unless the exact numbers are in the paper. Do not overstate \
causality. Do not use brain or neuron imagery or metaphors. Keep on-screen labels tiny."""


def write(paper: Paper) -> Script:
    meta = (f"Title: {paper.title}\nAuthors: {', '.join(paper.authors[:12])}\n"
            f"Venue: {paper.venue} ({paper.published})\nURL: {paper.url}\n\nAbstract:\n{paper.abstract}")
    content: list = []
    if paper.pdf_url:
        content.append({"type": "document", "source": {"type": "url", "url": paper.pdf_url}})
    content.append({"type": "text", "text": meta + "\n\nWrite the episode script."})
    try:
        script = llm.ask(Script, SYSTEM, content, effort="high")
    except RuntimeError:
        if not paper.pdf_url:
            raise
        log("Script with full PDF failed; retrying from the abstract only")
        script = llm.ask(Script, SYSTEM, content[1:], effort="high")
    validate(script)
    n = sum(len(l.zh) for s in script.scenes for l in s.lines)
    log(f"Script: {len(script.scenes)} scenes, {n} Chinese characters")
    return script


def validate(script: Script) -> None:
    if not 5 <= len(script.scenes) <= 10:
        raise RuntimeError(f"Script has {len(script.scenes)} scenes")
    for s in script.scenes:
        if not s.lines:
            raise RuntimeError("A scene has no narration")
        s.labels = [l.strip() for l in s.labels if l.strip()][:4]
        if s.values and len(s.values) != len(s.labels):
            s.values = []
    if script.scenes[-1].visual != "takeaway":
        script.scenes[-1].visual = "takeaway"
