import json

from shorts import config, journal
from shorts.papers import with_signals


def test_with_signals_skips_none():
    assert with_signals("Strong study.", "none") == "Strong study."
    assert with_signals("Strong study.", "Viewers asked for AI topics.") == \
        "Strong study. Signals: Viewers asked for AI topics."


def test_log_lists_every_post_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    (tmp_path / "history.json").write_text(json.dumps([{
        "episode": "e1", "created": "2026-10-28T06:00:00+00:00", "pick_reason": "Fits the channel.",
        "paper": {"title": "P1", "url": "https://x/p1", "venue": "arXiv"},
        "script": {"title_zh": "中", "title_en": "En"},
        "posts": {"zh": {"youtube": {"id": "1", "url": "https://yt/1"}}}}]))
    (tmp_path / "social_history.json").write_text(json.dumps([{
        "posted": "2026-10-29T01:00:00+00:00", "platform": "threads", "lang": "en", "kind": "question",
        "episodes": ["e1"], "text": "Hello", "news": None, "id": "9", "url": "https://th/9"}]))
    md = journal.render()
    assert md.index("## 2026-10-29") < md.index("## 2026-10-28")
    assert "Fits the channel." in md and "https://yt/1" in md
    assert journal.MISSING in md  # the free post has no reason recorded


def test_digest_covers_free_posts_and_own_comments():
    from shorts.analytics import summary

    report = {"collected_at": "2026-10-29", "posts": [
        {"kind": "social", "platform": "threads", "lang": "zh", "title": "t", "metrics": {"views": 5}}]}
    text = summary(report)
    assert "social on threads" in text and "paper citation" in text
