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
