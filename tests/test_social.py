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
