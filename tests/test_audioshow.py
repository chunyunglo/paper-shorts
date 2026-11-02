from shorts import audioshow
from shorts.papers import Paper

PAPER = Paper(id="arxiv:1", title="Shoppers in many dimensions", abstract="a" * 300, authors=["A One", "B Two"],
              venue="arXiv cs.HC", url="https://arxiv.org/abs/1", doi=None, published="2026-10-14", source="arxiv")


def episode(n_lines=80, chars=45):
    lines = [audioshow.Line(spk="K" if i % 2 == 0 else "A", text="資" * chars + "。") for i in range(n_lines)]
    return audioshow.Episode(title="t", lines=lines, description="d", exploration="e", automation="探索自動化")


def test_valid_episode_has_no_errors():
    assert audioshow.validate(episode()) == []


def test_length_and_opening_are_checked():
    assert any("spoken length" in e for e in audioshow.validate(episode(n_lines=60, chars=10)))
    ep = episode()
    ep.lines[0].spk = "A"
    assert any("opens" in e for e in audioshow.validate(ep))


def test_tts_hostile_text_is_flagged():
    ep = episode()
    ep.lines[3].text = "請看 https://example.com（附錄）"
    assert any("line 3" in e for e in audioshow.validate(ep))


def test_show_file_matches_build_audio_format():
    show = audioshow.to_show(episode(), PAPER)
    assert show["lang"] == "zh" and set(show["hosts"]) == {"K", "A"}
    assert all(len(r) == 3 and r[0] in "KA" for r in show["lines"])
    assert show["paper"]["venue"] == "arXiv cs.HC · 2026"
    md = audioshow.script_md(episode(), PAPER)
    assert "**阿凱**" in md and "**安妮**" in md
