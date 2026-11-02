from concept_show import show


def episode(n_lines=90, chars=40):
    lines = [show.Line(spk="K" if i % 2 == 0 else "A", text="維" * chars + "。") for i in range(n_lines)]
    return show.Episode(title="t", one_liner="o", lines=lines, description="d", examples=["假設：一家店"])


def test_strategy_prompt_and_history(tmp_path):
    import json
    st = show.strategy()
    assert st["theme"] and st["why"] and st["principles"]
    p = show.plan_prompt(st)
    assert show.SHOW in p and "{" not in p
    assert show.history(tmp_path / "none") == ([], "")
    for tag, created, notes in [("concept-demo-2", "2026-11-01T10:00", "old"), ("concept-demo-5", "2026-11-08T10:00", "new")]:
        (tmp_path / tag).mkdir()
        (tmp_path / tag / "meta.json").write_text(json.dumps({"created": created, "title": tag, "plan_reason": "r"}))
        (tmp_path / tag / "strategy.md").write_text(notes)
    (tmp_path / "old-demo").mkdir()
    (tmp_path / "old-demo" / "meta.json").write_text(json.dumps({"created": "2026-11-09", "title": "fixed list"}))
    metas, notes = show.history(tmp_path)
    assert [m["title"] for m in metas] == ["concept-demo-2", "concept-demo-5"] and notes == "new"


def test_valid_episode_has_no_errors():
    assert show.validate(episode()) == []


def test_length_and_opening_are_checked():
    assert any("spoken length" in e for e in show.validate(episode(n_lines=80, chars=10)))
    ep = episode()
    ep.lines[0].spk = "A"
    assert any("opens" in e for e in show.validate(ep))


def test_unsourced_claims_and_tts_hostile_text_are_flagged():
    ep = episode()
    ep.lines[3].text = "研究顯示百分之 80 的人都這樣"
    ep.lines[5].text = "請看 https://example.com（附錄）"
    errs = show.validate(ep)
    assert any("line 3" in e for e in errs) and any("line 5" in e for e in errs)


def test_prompt_and_show_file():
    topic, theme = show.Topic(id="ep01", title="什麼是隨機變數", idea="不確定的事可以用一個數字描述"), show.strategy()["theme"]
    p = show.system_prompt(topic, theme)
    assert topic.title in p and "{" not in p
    s = show.to_show(episode(), topic)
    assert s["lang"] == "zh" and set(s["hosts"]) == {"K", "A"}
    assert all(len(r) == 3 and r[0] in "KA" for r in s["lines"])
    md = show.script_md(episode(), topic)
    assert f"**{show.K}**" in md and f"**{show.A}**" in md


def test_voice_groups_lines_into_few_paced_requests():
    import json
    from concept_show import voice
    lines = [["K" if i % 2 == 0 else "A", "維" * 26, {"gap": 0.35}] for i in range(145)]
    parts = voice.chunks(lines)
    assert len(parts) <= 10 and sum(len(c) for c in parts) == 145
    assert all(sum(len(t) for _, t in c) <= voice.CHUNK_CHARS for c in parts)
    b = json.loads(voice.body(parts[0], show.HOSTS))
    names = {v["speaker"] for v in b["generationConfig"]["speechConfig"]["multiSpeakerVoiceConfig"]["speakerVoiceConfigs"]}
    assert names == {"Kai", "Anne"} and b["contents"][0]["parts"][0]["speech_metadata"]["speaker"] == "Kai"
