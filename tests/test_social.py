from datetime import datetime, timezone

from shorts import social
from shorts.social import Plan, Post, Slide


def _post(platform, eps=("ep1",), slides=None, text="hi"):
    return Post(platform=platform, lang="zh", kind="follow_up", episodes=list(eps), news_index=5, text=text,
                slides=slides or [], why="x")


def test_room_counts_today_and_week():
    now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    h = [{"platform": "threads", "posted": "2026-10-27T01:00:00+00:00"},
         {"platform": "threads", "posted": "2026-10-26T01:00:00+00:00"},
         {"platform": "instagram", "posted": "2026-10-23T01:00:00+00:00"},
         {"platform": "instagram", "posted": "2026-10-01T01:00:00+00:00"}]
    assert social.room(h, now) == {"threads": 1, "instagram": 2}


def test_validate_enforces_caps_and_shape():
    s = Slide(kind="cover", heading="h", big="", lines=[])
    plan = Plan(posts=[_post("threads"), _post("threads"), _post("threads", eps=("nope",)),
                       _post("instagram"), _post("instagram", slides=[s]), _post("threads", slides=[s])])
    out = social.validate(plan, {"ep1": {}}, {"threads": 1, "instagram": 3}, n_news=2)
    assert [p.platform for p in out.posts] == ["threads", "instagram"]
    assert all(p.news_index == -1 for p in out.posts)


def test_slide_image_size():
    img = social.slide_image(Slide(kind="stat", heading="變長了", big="+49%", lines=["一行", "two"]), 1, 3, "zh")
    assert img.size == (1080, 1350)


def test_failed_slide_drops_only_its_post(monkeypatch, tmp_path):
    from shorts import analytics, llm, look, news

    s = Slide(kind="cover", heading="h", big="", lines=["one"])
    plan = Plan(posts=[_post("threads"), _post("instagram", slides=[s, s]), _post("instagram", slides=[s])])
    monkeypatch.setattr(social, "load", lambda: [])
    monkeypatch.setattr(social, "OUT", tmp_path)
    monkeypatch.setattr(social, "max_ig_per_week", lambda: 3)
    monkeypatch.setattr(social, "recent_episodes", lambda: [{"episode": "ep1", "paper": {"title": "t", "venue": "v"}}])
    monkeypatch.setattr(news, "headlines", lambda: [])
    monkeypatch.setattr(news, "listing", lambda h: "")
    monkeypatch.setattr(analytics, "guidance", lambda: "")
    monkeypatch.setattr(llm, "ask", lambda model, *a, **k: plan if model is Plan else social.Check(problems=[]))
    # frames 0-1 are post 1's slides, frame 2 is post 2's: fail post 2 only
    monkeypatch.setattr(look, "check_images", lambda images, ctx: ["frame 2: text cut off"])
    folder = social.make(datetime(2026, 10, 27, 12, tzinfo=timezone.utc))
    import json
    kept = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    assert [(r["platform"], len(r["images"])) for r in kept] == [("threads", 0), ("instagram", 2)]


def test_failed_frames_parses_look_output():
    assert social.failed_frames(["frame 0: x", "frame 12: y", "odd"]) == {0, 12}


def test_feedback_saved_and_read_back(tmp_path, monkeypatch):
    from shorts import comments

    monkeypatch.setattr(comments, "STATE_DIR", tmp_path)
    monkeypatch.setattr(comments, "FEEDBACK_FILE", tmp_path / "feedback.jsonl")
    today = datetime.now(timezone.utc).date().isoformat()
    comments.save_feedback([{"day": today, "episode": "e1", "platform": "youtube", "note": "wants sleep research"},
                            {"day": "2020-01-01", "episode": "e0", "platform": "threads", "note": "old"}])
    assert [r["note"] for r in comments.recent_feedback()] == ["wants sleep research"]
