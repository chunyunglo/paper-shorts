import json
from datetime import datetime, timezone

from shorts import analytics, podcast
from shorts.papers import Paper

PAPER = Paper(id="doi:10.1/x", title="A study of petitions", abstract="a" * 300, authors=["A One", "B Two", "C Three", "D Four", "E Five"],
              venue="Nature Human Behaviour", url="https://doi.org/10.1/x", doi="10.1/x", published="2026-10-14", source="journal")


def line(spk, text, card="", **kw):
    base = dict(spk=spk, text=text, sub="", emo="none", gest="none", gap=0.3, laugh=0, applause=0, back="",
                to_camera=False, card=card)
    return podcast.DLine(**(base | kw))


def card(cid, type_, **kw):
    base = dict(id=cid, type=type_, kicker=cid.upper(), big="", sub="", rows=[], stats=[], text="")
    return podcast.Card(**(base | kw))


def episode(n_words=800):
    filler = " ".join(["word"] * 19) + "."
    lines = [line("K", "Good evening! Welcome to the show.", applause=3.0, to_camera=True, gest="both"),
             line("A", "Thanks, Kai. Tonight's paper is about petitions.", card="paper"),
             line("K", "How much data?", card="data", sub="How much data?!"),
             line("A", "One and a half million petitions.", laugh=0.6, back="Wow."),
             line("A", "The takeaway is simple.", card="takeaway")]
    while podcast.words(podcast.Episode(title="t", affil="", cards=[], lines=lines, description="", tags=[],
                                        method_summary="", limitations="")) < n_words:
        lines.insert(-1, line("K" if len(lines) % 2 else "A", filler))
    cards = [card("paper", "paper"), card("data", "big", big="1.5M", sub="petitions", rows=["2023"]),
             card("takeaway", "quote", text="Outputs changed, outcomes did not.")]
    return podcast.Episode(title="The AI button", affil="Cornell", cards=cards, lines=lines,
                           description="d", tags=["ai", "petitions"], method_summary="m", limitations="l")


def test_valid_episode_has_no_errors():
    assert podcast.validate(episode()) == []


def test_validate_catches_bad_cards_and_length():
    ep = episode(200)
    ep.lines[2].card = "nope"
    errs = " ".join(podcast.validate(ep))
    assert "unknown card 'nope'" in errs and "words" in errs and "never shown: data" in errs


def test_to_show_matches_renderer_format():
    show = podcast.to_show(episode(), PAPER)
    assert show["lines"][0] == ["SFX", "sting", {"dur": 3.2}]
    first = show["lines"][1]
    assert first[0] == "K" and first[2]["applause"] == 3.0 and first[2]["toCamera"] and first[2]["gest"] == "both"
    assert "emo" not in first[2]
    assert show["lines"][3][2]["sub"] == "How much data?!"
    assert show["lines"][4][2] == {"gap": 0.3, "laugh": 0.6, "back": "Wow."}
    assert show["cards"]["data"] == {"type": "big", "kicker": "DATA", "big": "1.5M", "sub": "petitions", "rows": ["2023"]}
    assert show["paper"]["authors"] == "A One, B Two, C Three, D Four et al."
    assert show["paper"]["venue"] == "Nature Human Behaviour · 2026"
    assert set(show["hosts"]) == {"K", "A"}


def test_chapters_need_spacing_and_three_marks():
    cards = {"paper": {"type": "paper"}, "data": {"type": "big", "kicker": "THE DATA"},
             "x": {"type": "list", "kicker": "FINE PRINT · LIMITS"}}
    tl = {"duration": 300, "lines": [{"spk": "K", "start": 0}, {"spk": "A", "start": 20, "card": "paper"},
                                     {"spk": "A", "start": 25, "card": "data"}, {"spk": "A", "start": 120, "card": "x"},
                                     {"spk": "K", "start": 280}]}
    marks = podcast.chapters(tl, cards)
    assert [n for _, n in marks] == ["Cold open", "Tonight's paper", "Fine print", "Good night"]
    assert podcast.stamp(125.7) == "2:05"


def test_next_slot(monkeypatch):
    monkeypatch.setenv("PODCAST_DAY", "4")
    monkeypatch.setenv("PODCAST_HOUR_UTC", "12")
    wed = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
    assert podcast.next_slot(wed) == datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    late = datetime(2026, 10, 30, 13, 0, tzinfo=timezone.utc)  # render finished after the slot
    assert podcast.next_slot(late) is None


def test_analytics_summary_and_guidance(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics, "DIR", tmp_path)
    rep = {"collected_at": "2026-10-27T00:00:00+00:00", "notes": ["YouTube Analytics not authorized"],
           "channel": {"youtube": {"subscriberCount": 10, "viewCount": 500, "videoCount": 20}},
           "posts": [{"kind": "short", "platform": "youtube", "lang": l, "title": f"t{l}", "url": "u", "episode": "e",
                      "id": l, "metrics": {"views": v, "likes": 1, "comments": 0}} for l, v in (("zh", 300), ("en", 100))]}
    text = analytics.summary(rep)
    assert "10 subscribers" in text and "average 200 views" in text and "by language: zh 300, en 100" in text
    (tmp_path / "latest.json").write_text(json.dumps(rep))
    (tmp_path / "strategy.md").write_text("Written 2026-10-27\n\n- zh does best")
    g = analytics.guidance()
    assert "zh does best" in g and "average 200 views" in g
    md = analytics.report_md(rep, "s")
    assert "| short | youtube | zh | 300 |" in md


import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_qa_passes_good_video_and_flags_black_silent_one(tmp_path):
    good, bad = tmp_path / "good.mp4", tmp_path / "bad.mp4"
    common = ["-t", "4", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"]
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30", "-f", "lavfi",
                    "-i", "sine=frequency=300:sample_rate=24000", *common, str(good)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:size=1280x720:rate=30", "-f", "lavfi",
                    "-i", "anullsrc=r=24000", *common, str(bad)], check=True)
    assert podcast.qa(good, 4.0) == []
    errs = " ".join(podcast.qa(bad, 60.0))
    assert "1280x720" in errs and "timeline" in errs and "quiet" in errs and "blank" in errs


def test_shorts_publish_without_review_unless_owner_says_no(monkeypatch):
    from shorts import review

    class R:
        def __init__(self, data): self.data = data
        def json(self): return self.data

    def run(comments, required=""):
        monkeypatch.setenv("REVIEW_REQUIRED", required)
        monkeypatch.setattr(review, "owner", lambda: "me")
        monkeypatch.setattr(review, "http", lambda *a, **k: R([{"user": {"login": u}, "body": b} for u, b in comments]))
        return review._is_approved({"comments_url": "x"})

    assert run([]) is True
    assert run([("me", "第三段講太快")]) is True
    assert run([("me", "不要上")]) is False
    assert run([], "true") is False
    assert run([("me", "OK")], "true") is True
