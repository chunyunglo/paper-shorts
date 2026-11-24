"""The playbook: strategy the weekly review can change, under guardrails."""
import json
from datetime import datetime, timezone

import pytest

from shorts import analytics, playbook as pbm, script as sm, social, stocks, threads_budget

NOW = datetime(2026, 12, 20, 2, tzinfo=timezone.utc)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(pbm, "FILE", tmp_path / "playbook.json")
    monkeypatch.setattr(pbm, "LOG", tmp_path / "playbook_log.md")
    monkeypatch.setattr(analytics, "DIR", tmp_path)
    for var in ("SCRIPT_FORMAT", "THREADS_DAILY_CAP", "MAX_THREADS_PER_DAY", "MAX_IG_PER_WEEK",
                "PLAYBOOK_AUTO", "PLAYBOOK_PINNED"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def change(field, value, revert=False):
    return pbm.Change(field=field, value=json.dumps(value), reason="r", evidence="e", watch="w", revert=revert)


def test_defaults_keep_todays_behaviour(state):
    pb = pbm.load()
    assert pb.script_format == "alternate" and pb.threads_daily_cap == 2 and pb.ig_per_week == 3
    assert pb.stock_slots == ["morning", "noon", "evening"]
    assert pbm.script_notes("classic") == "" and pbm.pick_notes() == ""
    assert threads_budget.daily_cap() == 2 and social.max_threads_per_day() == 2


def test_applied_change_reaches_the_pipelines(state):
    lines = pbm.apply(pbm.Proposal(check="c", changes=[change("ending", "loop"), change("threads_daily_cap", 3)]), NOW)
    assert all(l.startswith("- ✅") for l in lines)
    assert "Do NOT add a line inviting viewers to follow" in pbm.script_notes("answer_first")
    assert threads_budget.daily_cap() == 3
    assert "## 2026-12-20" in (state / "playbook_log.md").read_text(encoding="utf-8")


def test_guardrails(state, monkeypatch):
    p = pbm.Proposal(check="c", changes=[change("threads_daily_cap", 9), change("nope", 1),
                                         change("stock_slots", []), change("ending", "loop"),
                                         change("hook_style", "result"), change("method_depth", "brief")])
    lines = pbm.apply(p, NOW)
    assert [l[:3] for l in lines] == ["- ❌", "- ❌", "- ❌", "- ✅", "- ✅", "- ❌"]  # range, field, empty, max 2
    # cooldown: no new change to the same field within two weeks, but a revert is fine
    later = datetime(2026, 12, 24, tzinfo=timezone.utc)
    assert pbm.apply(pbm.Proposal(check="c", changes=[change("ending", "follow")]), later)[0].startswith("- ❌")
    assert pbm.apply(pbm.Proposal(check="c", changes=[change("ending", "follow", revert=True)]),
                     datetime(2026, 12, 28, tzinfo=timezone.utc))[0].startswith("- ✅")
    monkeypatch.setenv("PLAYBOOK_PINNED", "ig_per_week")
    assert "PLAYBOOK_PINNED" in pbm.apply(pbm.Proposal(check="c", changes=[change("ig_per_week", 1)]), later)[0]


def test_ab_test_is_locked_and_env_vars_still_win(state, monkeypatch):
    early = datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert "2026-12-02" in pbm.apply(pbm.Proposal(check="c", changes=[change("script_format", "classic")]), early)[0]
    monkeypatch.setenv("THREADS_DAILY_CAP", "1")
    assert threads_budget.daily_cap() == 1
    assert "THREADS_DAILY_CAP" in pbm.apply(pbm.Proposal(check="c", changes=[change("threads_daily_cap", 3)]), NOW)[0]
    monkeypatch.setenv("SCRIPT_FORMAT", "classic")
    assert sm.pick_format(NOW) == "classic"


def test_propose_off_only_suggests(state, monkeypatch):
    monkeypatch.setenv("PLAYBOOK_AUTO", "off")
    assert pbm.apply(pbm.Proposal(check="c", changes=[change("ending", "loop")]), NOW)[0].startswith("- 💡")
    assert pbm.load().ending == "follow" and not (state / "playbook.json").exists()


def test_bad_file_falls_back_per_field(state):
    (state / "playbook.json").write_text(json.dumps({"values": {"ending": "loop", "ig_per_week": 99, "x": 1}}))
    pb = pbm.load()
    assert pb.ending == "loop" and pb.ig_per_week == 3


def test_stock_slot_off_skips_before_any_call(state, tmp_path, monkeypatch):
    (state / "playbook.json").write_text(json.dumps({"values": {"stock_slots": ["morning"]}}))
    monkeypatch.setattr(stocks, "load", lambda: [])
    monkeypatch.setattr(stocks, "discover", lambda now: pytest.fail("no work for a paused slot"))
    assert stocks.make("evening", NOW) is None


def test_weekly_runs_once_a_week(state, monkeypatch):
    calls = []
    monkeypatch.setattr(pbm, "propose", lambda *a: calls.append(1) or pbm.Proposal(check="c", changes=[]))
    assert "本週不改" in pbm.weekly({}, "", NOW)
    assert pbm.weekly({}, "", datetime(2026, 12, 22, tzinfo=timezone.utc)) == "" and len(calls) == 1
    assert pbm.weekly({}, "", datetime(2026, 12, 23, tzinfo=timezone.utc)) and len(calls) == 2


def test_format_compare_uses_same_age(state):
    report = {"posts": [{"kind": "short", "format": "classic", "platform": "youtube", "id": "a",
                         "created": "2026-11-26T11:00:00+00:00"},
                        {"kind": "short", "format": "answer_first", "platform": "youtube", "id": "b",
                         "created": "2026-11-25T11:00:00+00:00"}]}
    rows = [{"day": "2026-11-29", "platform": "youtube", "id": "a", "views": 30},
            {"day": "2026-11-28", "platform": "youtube", "id": "b", "views": 50}]
    (state / "history.jsonl").write_text("\n".join(map(json.dumps, rows)))
    out = pbm.format_compare(report)
    assert "youtube classic: day 3 30 (n=1)" in out and "youtube answer_first: day 3 50 (n=1)" in out


def test_pick_notes(state):
    (state / "playbook.json").write_text(json.dumps({"values": {"everyday_relevance": "major",
                                                                "favor_topics": ["dating apps"]}}))
    assert "dating apps" in pbm.pick_notes() and "daily life" in pbm.pick_notes()
