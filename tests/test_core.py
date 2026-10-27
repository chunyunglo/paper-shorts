import json
from pathlib import Path

import pytest

from shorts import comments, fonts, safelog
from shorts import render, script as scriptmod
from shorts.publish import captions, citation, first_comment

FIX = Path(__file__).parent / "fixtures"


def test_wrap_keeps_punctuation_off_line_start():
    f = fonts.font("bold", 60)
    lines = fonts.wrap("等於把另一邊的聲音，直接放進動態牆。", f, 560)
    assert len(lines) >= 2
    assert all(not ln.startswith(("，", "。")) for ln in lines)


def test_wrap_does_not_split_english_words():
    f = fonts.font("regular", 38)
    lines = fonts.wrap("The other side's voices went straight into their feed", f, 400)
    words = "The other side's voices went straight into their feed".split()
    assert " ".join(lines).split() == words


def test_http_error_hides_url_and_body(monkeypatch):
    import requests

    class Resp:
        status_code = 400
        def json(self):
            return {"error": {"code": 190, "type": "OAuthException", "message": "secret comment text"}}

    monkeypatch.setattr(requests, "request", lambda *a, **k: Resp())
    with pytest.raises(safelog.ApiError) as exc:
        safelog.http("instagram", "reply", "POST", "https://graph.instagram.com/x?access_token=TOKEN123")
    msg = str(exc.value)
    assert "TOKEN123" not in msg and "secret comment" not in msg
    assert "190" in msg


def test_captions_fit_platform_limits():
    ep = {"script": json.loads((FIX / "script.json").read_text()),
          "paper": json.loads((FIX / "paper.json").read_text())}
    for lang in ("zh", "en", "pt"):
        cap = captions(ep, lang)
        assert cap["yt_title"].endswith("#Shorts") and len(cap["yt_title"]) <= 100
        assert len(cap["threads"]) <= 500
        assert "AI" in cap["long"] or "IA" in cap["long"]


def test_unclassified_comments_go_to_the_owner(monkeypatch):
    ep = {"script": json.loads((FIX / "script.json").read_text()),
          "paper": json.loads((FIX / "paper.json").read_text())}
    cs = [comments.Comment("youtube", str(i), "hi", "a", "l") for i in range(3)]
    monkeypatch.setattr(comments.llm, "ask", lambda *a, **k: comments.Triage(decisions=[
        comments.Decision(index=0, category="praise", reply="Thanks!", note="")]))
    out = comments.triage(ep, cs)
    assert [d.category for d in out] == ["praise", "sensitive", "sensitive"]


def test_threads_skips_own_and_answered(monkeypatch):
    items = [
        {"id": "1", "text": "q1", "username": "u"},
        {"id": "2", "text": "q2", "username": "u"},
        {"id": "3", "text": "ours", "username": "me", "is_reply_owned_by_me": True, "replied_to": {"id": "2"}},
        {"id": "4", "text": "spam", "username": "s", "hide_status": "HIDDEN"},
    ]
    monkeypatch.setattr(comments.meta, "th_replies", lambda pid: items)
    assert [c.id for c in comments.threads_new("p", "link")] == ["1"]


def test_state_stores_hashes_not_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(comments, "STATE_DIR", tmp_path)
    monkeypatch.setattr(comments, "STATE_FILE", tmp_path / "comments.json")
    c = comments.Comment("youtube", "UgxCOMMENTID", "t", "a", "l")
    comments.save_done({comments.digest(c)})
    raw = (tmp_path / "comments.json").read_text()
    assert "UgxCOMMENTID" not in raw
    assert comments.digest(c) in comments.load_done()


@pytest.mark.parametrize("text,ok", [("OK", True), ("ok!", True), ("沒問題", True), ("沒問題～", True),
                                     ("可以", True), ("👍", True), ("不可以", False),
                                     ("ok 但標題改一下", False), ("標題要改", False)])
def test_review_approval_words(text, ok):
    from shorts import review
    assert review.is_approval(text) is ok


def test_portuguese_follows_the_scene_plan():
    script = scriptmod.Script.model_validate_json((FIX / "script.json").read_text())
    views = render.localize(script, "pt")
    assert [len(v.lines) for v in views] == [len(s.lines) for s in script.scenes]
    assert views[1].heading == "O ESTUDO"
    bad = script.pt.model_copy(deep=True)
    bad.scenes[0].lines.pop()
    with pytest.raises(RuntimeError):
        scriptmod.check_localized(script, bad)


def test_citation_comment():
    paper = json.loads((FIX / "paper.json").read_text())
    ref = citation(paper)
    assert paper["title"] in ref and paper["published"][:4] in ref and ref.split()[-1].startswith("http")
    assert first_comment({"paper": paper}, "pt").startswith("📄 Artigo")


@pytest.mark.parametrize("text,kind", [("OK", "approve"), ("沒問題", "approve"), ("不要上", "reject"),
                                       ("第三段講太快", "feedback"), ("ok 但標題要改", "feedback")])
def test_review_comment_kind(text, kind):
    from shorts import review
    assert review.kind(text) == kind


def test_latest_owner_comment_decides(monkeypatch):
    from shorts import review

    class Resp:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    def thread(*bodies):
        return [{"user": {"login": who}, "body": b} for who, b in bodies]

    monkeypatch.setenv("GITHUB_TOKEN", "x")
    for comments, ok in [
        (thread(("chunyunglo", "OK")), True),
        (thread(("chunyunglo", "OK"), ("chunyunglo", "標題改短一點")), False),
        (thread(("chunyunglo", "標題改短一點"), ("github-actions[bot]", "新版本"), ("chunyunglo", "沒問題")), True),
        (thread(("someone", "OK")), False),
    ]:
        monkeypatch.setattr(review, "http", lambda *a, c=comments, **k: Resp(c))
        assert review._is_approved({"comments_url": "u"}) is ok


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Big AI chatbot story - Example News</title><source url="https://x">Example News</source>
<pubDate>Fri, 23 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>Old story - Example News</title><source url="https://x">Example News</source>
<pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_news_parse_strips_source_and_drops_old():
    from calendar import timegm
    from shorts import news
    now = timegm((2026, 10, 25, 3, 0, 0))
    items = news.parse(RSS, "US", now=now)
    assert [h.title for h in items] == ["Big AI chatbot story"]
    assert items[0].source == "Example News" and items[0].published == "2026-10-23"
    assert "<0> [US] Big AI chatbot story" in news.listing(items)


def test_news_hook_in_review_and_script(tmp_path):
    from shorts import pipeline, review
    n = {"title": "Big AI chatbot story", "source": "Example News", "published": "2026-10-23",
         "region": "US", "link": "The paper measures how people trust chatbot advice."}
    assert "Big AI chatbot story" in review.news_md(n) and "trust" in review.news_md(n)
    assert "沒有" in review.news_md(None)
    meta = json.loads((FIX / "script.json").read_text(encoding="utf-8"))
    ep = {"script": meta, "paper": {"title": "T", "url": "u", "venue": "V", "published": "2026"},
          "pick_reason": "r", "news": n, "videos": {}}
    assert "Big AI chatbot story" in pipeline.script_markdown(ep)


def test_suggest_replies_filters_posts_and_never_posts(monkeypatch):
    from datetime import datetime, timezone
    from shorts import engage
    from shorts.safelog import ApiError
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
    found = [{"id": "1", "text": "我的動態全是同一邊", "username": "a", "timestamp": now, "permalink": "p1"},
             {"id": "1", "text": "dup", "username": "a", "timestamp": now},
             {"id": "4", "text": "english only", "username": "c", "timestamp": now},
             {"id": "2", "text": "ours", "username": "me", "timestamp": now},
             {"id": "3", "text": "old", "username": "b", "timestamp": "2020-01-01T00:00:00+0000"}]
    monkeypatch.setattr(engage, "search", lambda q, limit=15: found)
    q = engage.Queries(zh=["演算法 同溫層"], en=["my feed"], pt=["algoritmo bolha"])
    posts, ok = engage.find_posts(q, "me")
    assert ok and [(p["id"], p["query_lang"]) for p in posts] == [("1", "zh"), ("4", "en")]

    def denied(q, limit=15):
        raise ApiError("threads", "keyword search", 400, "10")
    monkeypatch.setattr(engage, "search", denied)
    assert engage.find_posts(q, "me") == ([], False)

    ep = {"script": {"title_zh": "標題", "title_en": "Title"}}
    plan = engage.Plan(suggestions=[engage.Suggestion(index=0, why="相關", reply="Nice point!"),
                                    engage.Suggestion(index=-1, why="通用", reply="草稿")])
    body = engage.email_body(ep, posts, plan, q, available=False)
    assert "Nice point!" in body and "p1" in body and "threads_keyword_search" in body
    assert "threads.com/search?q=" in body


def test_latest_episode_needs_recent_posts():
    from datetime import datetime, timezone
    from shorts import engage
    now = datetime.now(timezone.utc).isoformat()
    assert engage.latest_episode([{"created": now, "posts": {}}]) is None
    assert engage.latest_episode([{"created": "2020-01-01T00:00:00+00:00", "posts": {"zh": {}}}]) is None
    assert engage.latest_episode([{"created": now, "posts": {"zh": {}}}])["created"] == now


def test_icon_pick_keeps_only_real_names(monkeypatch):
    from shorts import icons, llm

    script = scriptmod.Script.model_validate_json((FIX / "script.json").read_text())
    monkeypatch.setattr(icons, "catalog", lambda: ["users", "truck", "gavel"])
    monkeypatch.setattr(icons, "known", lambda n: n in {"users", "truck", "gavel"})
    picked = [["truck"]] + [["gavel", "made-up", "truck", "users", "truck"] for _ in script.scenes[1:]]
    monkeypatch.setattr(llm, "ask", lambda *a, **k: scriptmod.IconPick(scenes=picked))
    scriptmod.pick_icons(script)
    assert len(script.icons) == len(script.scenes)
    for sc, ic in zip(script.scenes, script.icons):
        assert "made-up" not in ic
        if sc.visual in ("hook", "paper", "takeaway"):
            assert ic == []
        else:
            assert len(ic) <= max(1, len(sc.labels))


def test_icon_pick_falls_back_to_keywords_when_claude_fails(monkeypatch):
    from shorts import icons, llm

    script = scriptmod.Script.model_validate_json((FIX / "script.json").read_text())
    monkeypatch.setattr(icons, "catalog", lambda: ["users", "truck"])
    calls = []

    def boom(*a, **k):
        calls.append(k.get("effort"))
        raise RuntimeError("Claude output incomplete (stop_reason=max_tokens)")

    monkeypatch.setattr(llm, "ask", boom)
    monkeypatch.setattr(icons, "find", lambda w: "truck")
    scriptmod.pick_icons(script)
    assert calls == ["low", "low"]
    assert len(script.icons) == len(script.scenes)
    assert any(script.icons)
    for sc, ic in zip(script.scenes, script.icons):
        if sc.visual in ("hook", "paper", "takeaway"):
            assert ic == []


def test_scenes_draw_without_icons(monkeypatch):
    from shorts import icons, visuals

    monkeypatch.setattr(icons, "image", lambda *a, **k: None)
    visuals._icon.cache_clear()
    view = render.SceneView("icons", "THE DATA", ["Ranches", "Buyers", "Cattle"], [], "", ["x"],
                            ["tractor", "building-store", "truck"])
    ctx = {"seed": 1, "t": 1.0, "lang": "en"}
    for visual in ("icons", "crowd", "pipeline", "contrast", "bars", "journey", "spotlight", "funnel"):
        view.visual = visual
        assert visuals.draw(view, 0.8, ctx).size == (visuals.VW, visuals.VH)


def test_old_scripts_render_without_icons():
    script = scriptmod.Script.model_validate_json((FIX / "script.json").read_text())
    assert script.icons == []
    assert all(v.icons == [] for v in render.localize(script, "zh"))


def test_garbled_rss_authors_are_dropped():
    from shorts import papers
    blob = "Tara MittelbergMarin E. Skidmoreahttps://ror.org/01y2jtd41Nelson Institute, Urbana, IL 61801"
    assert papers.clean_authors([blob]) == []
    assert papers.clean_authors(["Ada Lovelace", "Alan Turing"]) == ["Ada Lovelace", "Alan Turing"]


def test_slug_never_ends_with_a_hyphen():
    from shorts import pipeline

    s = pipeline.slug("Decredentialed jobs and upward mobility among non-college workers in the USA")
    assert s == "decredentialed-jobs-and-upward-mobility"
    assert not s.endswith("-") and len(s) <= 40
