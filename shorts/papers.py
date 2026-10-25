"""Find candidate papers and let Claude pick this episode's paper."""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

import feedparser
from pydantic import BaseModel, Field

from . import llm
from .safelog import http, log
from .state import norm_title, seen_keys

ARXIV_CATS = ["cs.SI", "cs.CY", "physics.soc-ph", "econ.GN", "cs.HC"]
ARXIV_URL = ("https://export.arxiv.org/api/query?search_query={q}"
             "&sortBy=submittedDate&sortOrder=descending&max_results=200")

JOURNAL_FEEDS = {
    "Nature Human Behaviour": "https://www.nature.com/nathumbehav.rss",
    "Nature Computational Science": "https://www.nature.com/natcomputsci.rss",
    "PNAS": "https://www.pnas.org/action/showFeed?type=etoc&feed=rss&jc=pnas",
    "Science Advances": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv",
    "EPJ Data Science": "https://epjdatascience.springeropen.com/articles/most-recent/rss.xml",
    "Journal of Computational Social Science": "https://link.springer.com/search.rss?facet-journal-id=42001",
}

UA = {"User-Agent": "paper-shorts/1.0 (+https://github.com/chunyunglo/paper-shorts)"}


class Paper(BaseModel):
    id: str
    title: str
    abstract: str
    authors: list[str] = []
    venue: str
    url: str
    pdf_url: str | None = None
    doi: str | None = None
    published: str = ""
    source: Literal["arxiv", "journal"]


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def fetch_arxiv(days: int = 14) -> list[Paper]:
    q = "+OR+".join(f"cat:{c}" for c in ARXIV_CATS)
    resp = http("arxiv", "query", "GET", ARXIV_URL.format(q=q), headers=UA)
    feed = feedparser.parse(resp.content)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for e in feed.entries:
        try:
            published = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
        except (AttributeError, TypeError):
            continue
        if published < cutoff:
            continue
        arxiv_id = e.id.rsplit("/abs/", 1)[-1]
        base_id = re.sub(r"v\d+$", "", arxiv_id)
        pdf = next((l.href for l in e.get("links", []) if l.get("type") == "application/pdf"), None)
        out.append(Paper(
            id=f"arxiv:{base_id}",
            title=_clean(e.title),
            abstract=_clean(e.summary),
            authors=[a.name for a in e.get("authors", [])],
            venue=f"arXiv {e.get('arxiv_primary_category', {}).get('term', '')}".strip(),
            url=f"https://arxiv.org/abs/{base_id}",
            pdf_url=pdf or f"https://arxiv.org/pdf/{base_id}",
            doi=e.get("arxiv_doi"),
            published=published.date().isoformat(),
            source="arxiv",
        ))
    return out


def fetch_journal(venue: str, url: str) -> list[Paper]:
    resp = http("rss", venue, "GET", url, headers=UA)
    feed = feedparser.parse(resp.content)
    out = []
    for e in feed.entries:
        abstract = _clean(e.get("summary", "") or e.get("description", ""))
        if len(abstract) < 200:  # editorials, news, corrections
            continue
        doi = e.get("prism_doi") or e.get("dc_identifier", "").removeprefix("doi:") or None
        authors = [a.get("name", "") for a in e.get("authors", []) if a.get("name")]
        if not authors and e.get("author"):
            authors = [e.author]
        out.append(Paper(
            id=f"doi:{doi.lower()}" if doi else e.link,
            title=_clean(e.title),
            abstract=abstract,
            authors=authors,
            venue=venue,
            url=e.link,
            doi=doi,
            published=e.get("updated", e.get("published", ""))[:10],
            source="journal",
        ))
    return out


def candidates(history: list[dict]) -> list[Paper]:
    papers: list[Paper] = []
    try:
        papers += fetch_arxiv()
    except Exception as exc:  # one source failing should not stop the episode
        log(f"arXiv fetch skipped: {exc}")
    for venue, url in JOURNAL_FEEDS.items():
        try:
            papers += fetch_journal(venue, url)
        except Exception as exc:
            log(f"{venue} feed skipped: {exc}")
    seen = seen_keys(history)
    fresh, dedupe = [], set()
    for p in papers:
        keys = {p.id.lower(), norm_title(p.title)} | ({p.doi.lower()} if p.doi else set())
        if keys & (seen | dedupe):
            continue
        dedupe |= keys
        fresh.append(p)
    log(f"Candidates: {len(fresh)} new of {len(papers)} fetched")
    return fresh


class Pick(BaseModel):
    index: int = Field(description="Index of the chosen paper in the list")
    reason: str = Field(description="One sentence on why this paper fits best")


PICK_SYSTEM = """You curate papers for "Behavior Decoded / 行為解碼", a short-video channel that \
explains, in one minute, how a new study used computational methods to study human behavior.

Pick the single best paper for the next episode. A great pick:
- studies real human behavior (social media, mobility, cooperation, decisions, language, \
misinformation, health behavior, markets, politics, learning...) with a clearly computational \
method (large-scale data analysis, network science, NLP/LLMs as measurement tools, agent-based \
or generative simulation, causal inference on digital traces, field experiments at scale, ML \
prediction of behavior);
- has a method that can be explained visually in 3-4 steps to a curious non-expert;
- has a concrete, surprising, or useful finding;
- is a research article (not a review, perspective, editorial, dataset-only note, or pure \
engineering/benchmark paper with no behavioral question).
Avoid neuroscience/brain-imaging papers and avoid topics too close to the recent episodes listed. \
Prefer peer-reviewed journal papers when quality is similar, but a strong arXiv preprint is fine."""


def pick(papers: list[Paper], history: list[dict]) -> tuple[Paper, str]:
    if not papers:
        raise SystemExit("No new candidate papers found")
    papers = papers[:220]
    recent = [ep["paper"]["title"] for ep in history[-8:]]
    listing = "\n\n".join(
        f"[{i}] {p.title}\nVenue: {p.venue} ({p.published})\nAbstract: {p.abstract[:700]}"
        for i, p in enumerate(papers)
    )
    prompt = (f"Recent episodes (avoid repeating these topics):\n- " + "\n- ".join(recent or ["(none yet)"])
              + f"\n\nCandidates:\n\n{listing}")
    choice = llm.ask(Pick, PICK_SYSTEM, prompt, effort="medium")
    if not 0 <= choice.index < len(papers):
        raise RuntimeError("Claude picked an index outside the list")
    chosen = papers[choice.index]
    log(f"Picked: {chosen.title} [{chosen.venue}]")
    return chosen, choice.reason
