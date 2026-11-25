"""Answer-first scripts (alternating with the classic order) and the shared Threads daily budget."""
import json
from datetime import datetime, timezone

from shorts import config, script as sm, social, stocks, threads_budget


def test_answer_first_has_no_credits_scene_and_both_share_the_length_limit(monkeypatch):
    a, c = sm.system("answer_first"), sm.system("classic")
    assert "2. paper:" in c and "2. paper:" not in a and "Never use the 'paper' visual" in a
    assert "Length rule" in a and "Length rule" in c and "{hook}" not in sm.zh_system("classic")
    monkeypatch.delenv("MAX_SECONDS", raising=False)
    assert sm.budget("answer_first") == sm.budget("classic") == (540, 312)  # 2 minutes
    monkeypatch.setenv("MAX_SECONDS", "60")
    assert sm.budget("classic") == (270, 156)


def test_format_alternates_by_taiwan_day_and_can_be_fixed(monkeypatch):
    monkeypatch.delenv("SCRIPT_FORMAT", raising=False)
    days = {sm.pick_format(datetime(2026, 11, d, 12, tzinfo=timezone.utc)) for d in (25, 26)}
    assert days == {"answer_first", "classic"}
    monkeypatch.setenv("SCRIPT_FORMAT", "classic")
    assert sm.pick_format(datetime(2026, 11, 25, tzinfo=timezone.utc)) == "classic"


def test_script_format_is_read_from_the_scenes():
    assert sm.script_format({"scenes": [{"visual": "hook"}, {"visual": "paper"}]}) == "classic"
    assert sm.script_format({"scenes": [{"visual": "hook"}, {"visual": "funnel"}]}) == "answer_first"


def _write(path, rows):
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_threads_budget_counts_stock_and_free_posts_per_taiwan_day(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.delenv("THREADS_DAILY_CAP", raising=False)
    now = datetime(2026, 11, 25, 5, tzinfo=timezone.utc)  # 13:00 Taiwan
    assert threads_budget.room(now) == 1
    # 2026-11-24 23:30 UTC is already 11-25 in Taiwan; the instagram post does not count
    _write(tmp_path / "stock_history.json", [{"platform": "threads", "posted": "2026-11-24T23:30:00+00:00"}])
    _write(tmp_path / "social_history.json", [{"platform": "instagram", "posted": "2026-11-25T03:00:00+00:00"}])
    assert threads_budget.extras_today(now) == 1 and threads_budget.room(now) == 0
    monkeypatch.setenv("THREADS_DAILY_CAP", "4")
    assert threads_budget.room(now) == 2


def test_stock_slot_is_skipped_before_any_claude_call_when_threads_is_full(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(stocks, "HISTORY", tmp_path / "stock_history.json")
    _write(tmp_path / "social_history.json", [{"platform": "threads", "posted": datetime.now(timezone.utc).isoformat()}])
    monkeypatch.setattr(stocks, "discover", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert stocks.make("noon") is None


def test_free_posts_respect_the_shared_budget_and_languages(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.delenv("PUBLISH_LANGS", raising=False)
    now = datetime(2026, 11, 25, 3, tzinfo=timezone.utc)
    assert social.room([], now)["threads"] == 1
    _write(tmp_path / "stock_history.json", [{"platform": "threads", "posted": "2026-11-25T00:05:00+00:00"}])
    assert social.room([], now)["threads"] == 0
    assert social.langs() == {"zh"}
    post = social.Post(platform="threads", lang="en", kind="follow_up", text="hi", episodes=["e"], why="w",
                       news_index=-1, slides=[])
    zh = post.model_copy(update={"lang": "zh"})
    kept = social.validate(social.Plan(posts=[post, zh]), {"e": {}}, {"threads": 2, "instagram": 0}, 0).posts
    assert [p.lang for p in kept] == ["zh"]


def test_publish_langs_default_to_chinese_only(monkeypatch):
    from shorts import engage, pipeline
    monkeypatch.delenv("PUBLISH_LANGS", raising=False)
    assert config.publish_langs() == ("zh",)
    assert pipeline.langs() == ("zh",) and engage.langs() == ("zh",)
    monkeypatch.setenv("PUBLISH_LANGS", "zh en")
    assert config.publish_langs() == ("zh", "en")
    monkeypatch.setenv("PUBLISH_LANGS", "zh,en,xx")
    assert config.publish_langs() == ("zh", "en")
    monkeypatch.setenv("PUBLISH_LANGS", "")
    assert config.publish_langs() == ("zh",)
