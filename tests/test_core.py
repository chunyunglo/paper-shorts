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


def test_wrap_does_not_split_accented_words():
    f = fonts.font("regular", 54)
    text = "Assista ao nosso vídeo sobre a pecuária e a opinião pública no Brasil"
    for width in range(300, 900, 10):
        lines = fonts.wrap(text, f, width, max_lines=99)
        assert " ".join(lines).split() == text.split(), width


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
    monkeypatch.setenv("REVIEW_REQUIRED", "true")  # the opt-in owner-review mode

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
    for visual in ("icons", "crowd", "pipeline", "contrast", "bars", "journey", "spotlight", "funnel",
                   "waffle", "gauge", "counter", "clusters", "heatmap", "experiment", "feed", "magnify", "survey"):
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


def test_new_visuals_draw_with_and_without_data():
    from shorts import visuals

    ctx = {"seed": 3, "t": 2.0, "lang": "en"}
    bare = render.SceneView("x", "THE DATA", [], [], "", ["x"], [])
    full = render.SceneView("x", "THE DATA", ["Control", "Labelled"], [12, 0.4], "Do you trust the news?", ["x"],
                            ["user", "tag"])
    for visual in ("waffle", "gauge", "counter", "clusters", "heatmap", "experiment", "feed", "magnify", "survey",
                   "race", "cascade", "balance", "chat", "geo", "ranking", "swipe", "clock", "echo", "predict"):
        for view in (bare, full):
            view.visual = visual
            for p in (0.0, 0.5, 1.0):
                assert visuals.draw(view, p, ctx).size == (visuals.VW, visuals.VH)


def test_threads_publish_retries_when_container_not_found_yet(monkeypatch):
    from shorts.publish import meta
    from shorts.safelog import ApiError

    calls = []

    def fake_th(method, path, what, **params):
        calls.append(what)
        if what == "container status":
            return {"status": "FINISHED"}
        if calls.count("publish") == 1:
            raise ApiError("threads", "publish", 400, "24/4279009/OAuthException")
        return {"id": "123"}

    monkeypatch.setattr(meta, "th", fake_th)
    monkeypatch.setattr(meta.time, "sleep", lambda s: None)
    monkeypatch.setenv("THREADS_USER_ID", "1")
    assert meta.th_publish("c1") == "123"
    assert calls.count("publish") == 2


def test_threads_publish_does_not_retry_other_errors(monkeypatch):
    import pytest
    from shorts.publish import meta
    from shorts.safelog import ApiError

    def fake_th(method, path, what, **params):
        if what == "container status":
            return {"status": "FINISHED"}
        raise ApiError("threads", "publish", 400, "190/463/OAuthException")

    monkeypatch.setattr(meta, "th", fake_th)
    monkeypatch.setattr(meta.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("slept")))
    monkeypatch.setenv("THREADS_USER_ID", "1")
    with pytest.raises(ApiError):
        meta.th_publish("c1")


def test_write_shortens_a_script_over_the_narration_budget(monkeypatch):
    from shorts import script as sm

    long_line = sm.Line(zh="這" * 22, en=" ".join(["word"] * 12))
    short_line = sm.Line(zh="這" * 10, en="a short line")

    def scene(visual, line):
        return sm.Scene(visual=visual, heading_zh="發現", heading_en="FINDING", labels=[], labels_en=[],
                        values=[], big_text="", big_text_en="", lines=[line, line])

    def draft(line):
        return sm.ScriptDraft(title_zh="t", title_en="t", paper_title_zh="t",
                              scenes=[scene("hook", line), scene("paper", line)] +
                                     [scene("icons", line) for _ in range(4)] + [scene("takeaway", line)],
                              description_zh="d", description_en="d", hashtags=["a"],
                              method_summary="m", limitations="l")

    monkeypatch.setattr(sm.llm, "ask", lambda *a, **k: sm.PaperOutput(script=draft(long_line)))
    asked = []

    def fake_revise(paper, script, feedback):
        asked.append(feedback)
        return sm.Script(**draft(short_line).model_dump()), ""

    monkeypatch.setattr(sm, "revise", fake_revise)
    paper = type("P", (), {"title": "t", "authors": [], "venue": "v", "published": "2026", "url": "u",
                           "abstract": "a", "pdf_url": ""})()
    out = sm.write(paper)
    assert len(asked) == 1 and "Too long" in asked[0]
    assert sm.length(out)[0] <= sm.MAX_ZH


def test_claude_cost_counts_input_output_and_cache_reads():
    from types import SimpleNamespace
    from shorts import llm

    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=100_000,
                            cache_creation_input_tokens=0, cache_read_input_tokens=1_000_000)
    assert abs(llm.cost("claude-opus-5-5", usage) - (4.0 + 2.0 + 0.2)) < 1e-9


def test_failed_visual_check_fixes_the_text_once_then_stops(monkeypatch, tmp_path):
    import types
    from shorts import pipeline, look
    from shorts import script as scriptmod

    calls = {"build": 0, "revise": []}
    real_build = pipeline.build

    def fake_build(*a, **kw):
        calls["build"] += 1
        return real_build(*a, **kw)

    class R:
        duration = 1.0
        def __init__(self, *a, **k): pass
        def frame(self, i): return types.SimpleNamespace(convert=lambda m: types.SimpleNamespace(save=lambda *a, **k: None))

    monkeypatch.setattr(pipeline, "OUT", tmp_path)
    monkeypatch.setattr(pipeline, "LANGS", ["en"])
    monkeypatch.setattr(pipeline, "build", fake_build)
    monkeypatch.setattr(pipeline.tts, "voiceover", lambda *a: ([types.SimpleNamespace(start=0.0)], 1.0))
    monkeypatch.setattr(pipeline.tts, "choose", lambda lang: ("silent", ""))
    monkeypatch.setattr(pipeline.render, "Renderer", R)
    monkeypatch.setattr(pipeline.render, "encode", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "spoken", lambda s, l: [])
    monkeypatch.setattr(pipeline, "script_markdown", lambda m: "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(look, "check", lambda *a, **k: ["frame 3: heading cut off"])
    script = types.SimpleNamespace(icons=[1], scenes=[1], model_dump=lambda: {})
    monkeypatch.setattr(scriptmod, "revise", lambda p, s, fb, with_paper=True: (calls["revise"].append((fb, with_paper)) or s, ""))
    paper = types.SimpleNamespace(model_dump=lambda: {})

    import pytest
    with pytest.raises(SystemExit):
        pipeline.build("ep", paper, script, "", 0)
    assert len(calls["revise"]) == 1 and "heading cut off" in calls["revise"][0][0] and calls["revise"][0][1] is False
    assert calls["build"] == 2  # the first build and one retry, made with fix_visual=False


def test_claude_cost_bills_cache_writes_at_a_quarter_more():
    from types import SimpleNamespace
    from shorts import llm

    usage = SimpleNamespace(input_tokens=0, output_tokens=0,
                            cache_creation_input_tokens=1_000_000, cache_read_input_tokens=0)
    assert abs(llm.cost("claude-opus-5-5", usage) - 5.0) < 1e-9


def test_paper_calls_share_system_and_a_cached_paper_first(monkeypatch):
    from shorts import papers, script as sm

    monkeypatch.setattr(papers, "_pdfs", {"https://x/p.pdf": b"%PDF-1.7 fake"})
    monkeypatch.setattr(papers, "pdf_text", lambda data: "paper text " * 500)
    seen = []

    def fake_ask(schema, system, content, **kw):
        seen.append((system, content[0], kw.get("effort"), schema))
        return sm.PaperOutput(problems=[])

    monkeypatch.setattr(sm.llm, "ask", fake_ask)
    paper = type("P", (), {"title": "t", "authors": [], "venue": "v", "published": "2026", "url": "u",
                           "abstract": "a", "pdf_url": "https://x/p.pdf"})()
    sm.paper_call(paper, sm.SYSTEM, "write", needs_script=False)
    sm.paper_call(paper, sm.CHECK_SYSTEM, "check", needs_script=False)
    (s1, d1, e1, o1), (s2, d2, e2, o2) = seen
    assert s1 == s2 == sm.PAPER_SYSTEM and d1 == d2 and e1 == e2 and o1 is o2 is sm.PaperOutput
    assert d1["source"]["type"] == "text" and d1["cache_control"] == {"type": "ephemeral"}


def test_pdf_text_is_capped_and_scans_fall_back_to_the_pdf(monkeypatch):
    from shorts import papers

    assert papers.pdf_text(b"not a pdf") == ""
    monkeypatch.setattr(papers, "_pdfs", {"https://x/s.pdf": b"%PDF-1.7 scan"})
    monkeypatch.setattr(papers, "pdf_text", lambda data: "")
    doc = papers.pdf_doc("https://x/s.pdf")
    assert doc["source"]["type"] == "base64" and doc["cache_control"]


def test_pick_again_reuses_the_cached_listing(monkeypatch):
    from shorts import papers

    cands = [papers.Paper(id=str(i), title=f"t{i}", abstract="a", url="u", venue="v", source="arxiv")
             for i in range(3)]
    calls = []

    def fake_ask(schema, system, content, **kw):
        calls.append(content)
        return schema(index=len(calls) - 1, reason="r", signals="", news_index=-1, news_link="")

    monkeypatch.setattr(papers.llm, "ask", fake_ask)
    monkeypatch.setattr(papers, "enrich", lambda p: p)
    monkeypatch.setattr(papers, "attach_full_text", lambda p: p.id == "1")
    paper, _, _ = papers.pick(cands, [])
    assert paper.id == "1" and len(calls) == 2
    assert calls[0][0] == calls[1][0] and calls[0][0]["cache_control"] == {"type": "ephemeral"}
    assert "0" in calls[1][1]["text"]


def test_instagram_reel_retries_once_after_a_processing_error(monkeypatch):
    from shorts.publish import meta

    monkeypatch.setenv("IG_USER_ID", "1")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "IGx")
    statuses = iter(["ERROR", "FINISHED"])
    made = []

    def fake_ig(method, path, what, **params):
        if what == "create reel container":
            made.append(1)
            return {"id": f"c{len(made)}"}
        if what == "container status":
            return {"status_code": next(statuses)}
        if what == "publish reel":
            return {"id": "m1"}
        return {"permalink": "https://ig/p"}

    monkeypatch.setattr(meta, "ig", fake_ig)
    assert meta.ig_publish_reel("https://v", "cap", 0, retry_wait=0) == ("m1", "https://ig/p")
    assert len(made) == 2


def _plan_script(sm, n=7):
    line = sm.Line(zh="這是配對的中文", en="the English line")
    scenes = [sm.Scene(visual=v, heading_zh="發現", heading_en="FINDING", labels=["甲", "乙"] if v == "contrast" else [],
                       labels_en=["A", "B"] if v == "contrast" else [], values=[], big_text="",
                       big_text_en="", lines=[line, line])
              for v in ["hook", "paper"] + ["contrast"] * (n - 3) + ["takeaway"]]
    return sm.Script(title_zh="t", title_en="t", paper_title_zh="t", scenes=scenes, description_zh="d",
                     description_en="d", hashtags=["a"], method_summary="m", limitations="l")


_PAPER = type("P", (), {"title": "t", "authors": [], "venue": "v", "published": "2026", "url": "u",
                        "abstract": "a", "pdf_url": ""})()


def test_chinese_video_is_written_on_its_own_and_used_everywhere(monkeypatch):
    from shorts import pipeline, render, script as sm

    script = _plan_script(sm)
    seen = []

    def fake_ask(schema, system, content, **kw):
        seen.append(content[-1]["text"])
        return sm.PaperOutput(zh=sm.ZhVersion(title="中文標題", description="說明", scenes=[
            sm.ZhScene(heading="重點", labels=["一", "二"] if s.labels else [], big_text="", lines=["你以為呢？"])
            for s in script.scenes]))

    monkeypatch.setattr(sm.llm, "ask", fake_ask)
    out = sm.write_zh(_PAPER, script)
    assert "Do NOT translate" in seen[0] and "the English line" in seen[0] and "這是配對的中文" not in seen[0]
    assert out.title_zh == "中文標題" and out.scenes[2].labels == ["一", "二"]
    assert pipeline.spoken(out, "zh") == [["你以為呢？"]] * 7          # one line per scene, not the paired two
    assert pipeline.spoken(out, "en")[0] == ["the English line"] * 2
    assert sm.length(out)[0] == 5 * 7
    view = sm.review_view(out)
    assert view["scenes"][0]["lines_zh"] == ["你以為呢？"] and view["scenes"][0]["lines_en"] == ["the English line"] * 2
    assert render.localize(out, "zh")[0].lines == ["你以為呢？"]
    md = pipeline.script_markdown({"script": out.model_dump(), "paper": {"title": "t", "url": "u", "venue": "v",
                                   "published": "p"}, "pick_reason": "", "videos": {}})
    assert "- 你以為呢？" in md and "這是配對的中文" not in md


def test_chinese_video_that_misses_scenes_falls_back_to_paired_lines(monkeypatch):
    from shorts import script as sm

    script = _plan_script(sm)
    monkeypatch.setattr(sm.llm, "ask", lambda *a, **k: sm.PaperOutput(zh=sm.ZhVersion(
        title="x", description="y", scenes=[sm.ZhScene(heading="h", labels=[], big_text="", lines=["一句"])])))
    out = sm.write_zh(_PAPER, script)
    assert out.zh_lines == [] and sm.spoken_zh(out)[0] == ["這是配對的中文"] * 2 and out.title_zh == "t"


def test_revise_rewrites_the_chinese_video_too(monkeypatch):
    from shorts import script as sm

    script = _plan_script(sm)
    script.zh_lines = [["舊的"]] * 7
    calls = []

    def fake_ask(schema, system, content, **kw):
        text = content[-1]["text"]
        calls.append(text)
        if "<task>\n" + sm.ZH_SYSTEM in text:
            assert "舊的" in text and "fix the hook" in text
            return sm.PaperOutput(zh=sm.ZhVersion(title="新", description="d", scenes=[
                sm.ZhScene(heading="h", labels=list(s.labels), big_text="", lines=["新的"]) for s in script.scenes]))
        return sm.PaperOutput(script=sm.ScriptDraft(**script.model_dump(exclude={"pt", "icons", "zh_lines"})))

    monkeypatch.setattr(sm.llm, "ask", fake_ask)
    new, _ = sm.revise(_PAPER, script, "fix the hook")
    assert len(calls) == 2 and new.zh_lines == [["新的"]] * 7


def test_a_long_chinese_video_is_cut_once(monkeypatch):
    from shorts import script as sm

    script = _plan_script(sm)
    texts = []

    def fake_ask(schema, system, content, **kw):
        texts.append(content[-1]["text"])
        line = "長" * (50 if len(texts) == 1 else 20)
        return sm.PaperOutput(zh=sm.ZhVersion(title="t", description="d", scenes=[
            sm.ZhScene(heading="h", labels=list(s.labels), big_text="", lines=[line]) for s in script.scenes]))

    monkeypatch.setattr(sm.llm, "ask", fake_ask)
    out = sm.write_zh(_PAPER, script)
    assert len(texts) == 2 and "350 characters" in texts[1] and sm.length(out)[0] == 140


def test_rerender_reuses_spoken_lines_and_records_the_fallback_voice(monkeypatch, tmp_path):
    import numpy as np
    from shorts import tts

    calls = []

    def gemini(text, voice):
        calls.append(text)
        if text == "boom":
            raise RuntimeError("quota")
        return np.ones(2400, dtype=np.float32) * 0.1

    monkeypatch.setattr(tts, "_spoken", {})
    monkeypatch.setattr(tts, "used", {})
    monkeypatch.setitem(tts.SYNTH, "gemini", gemini)
    monkeypatch.setitem(tts.SYNTH, "google", lambda text, voice: np.ones(2400, dtype=np.float32) * 0.1)
    monkeypatch.setattr(tts, "choose", lambda lang: ("gemini", "Achird"))
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "x")
    tts.voiceover([["one", "two"], ["three"]], tmp_path / "a.wav", "en")
    tts.voiceover([["one", "two"], ["three"]], tmp_path / "b.wav", "en")
    # a steady tone has no pauses, so the one-request take can't be cut and each line is voiced once
    assert calls == ["one.\ntwo.\nthree.", "one", "two", "three"] and tts.used["en"] == "gemini Achird"
    tts.voiceover([["one", "boom"]], tmp_path / "c.wav", "en")
    assert tts.used["en"] == "google " + tts.GOOGLE_FALLBACK["en"]


def _speech(*secs, gap=0.3):
    import numpy as np
    from shorts import tts
    out = []
    for i, s in enumerate(secs):
        if i:
            out.append(np.zeros(int(tts.SR * gap), dtype=np.float32))
        out.append((np.sin(np.arange(int(tts.SR * s)) / 5) * 0.3).astype(np.float32))
    return np.concatenate(out)


def test_one_recording_is_cut_at_the_pauses_between_lines():
    from shorts import tts

    parts = tts.split_at_pauses(_speech(1.0, 2.0, 1.0), [10, 20, 10])
    assert len(parts) == 3 and [round(p.size / tts.SR) for p in parts] == [1, 2, 1]
    assert tts.split_at_pauses(_speech(4.0), [10, 20, 10]) is None   # no pauses: can't cut


def test_gemini_voices_each_language_in_one_request(monkeypatch, tmp_path):
    from shorts import tts

    calls = []

    def gemini(text, voice):
        calls.append(text)
        return _speech(*[0.8] * (text.count("\n") + 1))

    monkeypatch.setattr(tts, "_spoken", {})
    monkeypatch.setattr(tts, "used", {})
    monkeypatch.setitem(tts.SYNTH, "gemini", gemini)
    monkeypatch.setattr(tts, "choose", lambda lang: ("gemini", "Achird"))
    timings, _ = tts.voiceover([["你以為呢", "其實不是，"], ["答案在這裡"]], tmp_path / "a.wav", "zh")
    assert calls == ["你以為呢。\n其實不是。\n答案在這裡。"]
    assert [len(s.lines) for s in timings] == [2, 1]
    tts.voiceover([["你以為呢", "其實不是，"], ["答案在這裡"]], tmp_path / "b.wav", "zh")
    assert len(calls) == 1   # the re-render reuses it
