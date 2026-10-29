import json

from shorts import analytics, comments, config, memory


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr("shorts.state.HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(analytics, "DIR", tmp_path / "an")
    monkeypatch.setattr(analytics, "PODCAST_HISTORY", tmp_path / "podcast_history.json")
    monkeypatch.setattr(memory, "LESSONS", tmp_path / "an" / "lessons.md")
    monkeypatch.setattr(memory, "LESSONS_LOG", tmp_path / "an" / "lessons_log.md")
    monkeypatch.setattr(comments, "FEEDBACK_FILE", tmp_path / "feedback.jsonl")
    monkeypatch.setattr("shorts.social.HISTORY", tmp_path / "social_history.json")
    eps, rows = [], []
    topics = [("AI chatbots change how students learn", "AI 聊天機器人與學習", 400),
              ("Misinformation spreads faster on weekends", "假新聞在週末傳得更快", 30),
              ("Commuting patterns from phone data", "手機數據看通勤", 100),
              ("AI writing help for petitions", "AI 幫忙寫請願書", 120)]
    for i, (en, zh, v) in enumerate(topics):
        eps.append({"episode": f"e{i}", "created": f"2026-10-0{i + 1}T06:00:00+00:00", "pick_reason": f"reason {i}",
                    "paper": {"title": en, "url": "u", "venue": "arXiv"},
                    "script": {"title_zh": zh, "title_en": en,
                               "scenes": [{"lines": [{"zh": "開場", "en": f"Hook {i}"}]}]},
                    "posts": {"zh": {"youtube": {"id": f"y{i}", "url": "u"}}}})
        rows.append({"kind": "short", "lang": "zh", "title": en, "platform": "youtube", "id": f"y{i}", "metrics": {"views": v, "averageViewPercentage": 30.0}})
    (tmp_path / "history.json").write_text(json.dumps(eps))
    (tmp_path / "an").mkdir()
    (tmp_path / "an" / "latest.json").write_text(json.dumps({"posts": rows}))
    (tmp_path / "feedback.jsonl").write_text(json.dumps(
        {"day": "2099-01-01", "episode": "e0", "platform": "youtube", "note": "wants more AI and school topics"}) + "\n")


def test_cases_join_decisions_with_results(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    cs = {c["key"]: c for c in memory.cases()}
    assert cs["e0"]["views"] == 400 and "30% watched" in cs["e0"]["results"]
    assert cs["e0"]["rating"].startswith("above typical")
    assert cs["e1"]["rating"].startswith("below typical")
    assert cs["e0"]["feedback"] == ["wants more AI and school topics"]
    assert cs["e0"]["hook"] == "開場 | Hook 0" and cs["e0"]["why"] == "reason 0"


def test_search_finds_similar_topics_in_both_languages(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    cs = memory.cases()
    assert memory.search(cs, "Do AI chatbots help students?", 1)[0]["key"] == "e0"
    assert memory.search(cs, "假新聞", 1)[0]["key"] == "e1"
    assert memory.search(cs, "", 3) == []


def test_context_shows_similar_then_best_and_worst(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    text = memory.context("phone data commuting", ("short",), k=1, extremes=1)
    assert text.index("Most similar") < text.index("Best results") < text.index("Weakest results")
    assert "Commuting" in text and "AI chatbots" in text and "Misinformation" in text


def test_new_posts_are_not_judged(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    from datetime import datetime, timezone

    cs = memory.cases(now=datetime(2026, 10, 3, 12, tzinfo=timezone.utc))
    assert all(c["rating"] in ("too new to judge", "too few posts to compare") for c in cs)


def test_retrospect_writes_lessons_and_keeps_a_log(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    seen = {}

    def fake_ask(schema, system, prompt, **kw):
        seen["prompt"] = prompt
        return memory.Review(strategy_check="Too early to tell.", experiments=["Try a question hook"], lessons=[
            memory.Lesson(area="topic", lesson="AI-in-school topics travel", evidence="e0 400 views vs median 120",
                          confidence="low", status="new"),
            memory.Lesson(area="script", lesson="Old rule", evidence="contradicted", confidence="low",
                          status="retired")])

    monkeypatch.setattr(memory.llm, "ask", fake_ask)
    memory.retrospect()
    memory.retrospect()
    assert "AI chatbots" in seen["prompt"] and "AI-in-school topics travel" in seen["prompt"]  # sees last lessons
    lessons = memory.lessons()
    assert lessons.startswith("Written ") and "Retired" in lessons and "Try a question hook" in lessons
    assert memory.LESSONS_LOG.read_text().count("## ") == 2
    assert "Lessons from our weekly self-review" in analytics.guidance()
