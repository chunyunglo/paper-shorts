from concept_show import show


def episode(n_lines=90, chars=40):
    lines = [show.Line(spk="K" if i % 2 == 0 else "A", text="維" * chars + "。") for i in range(n_lines)]
    return show.Episode(title="t", one_liner="o", lines=lines, description="d", examples=["假設：一家店"])


def test_topics_load_and_are_unique():
    theme, ts = show.topics()
    assert theme and len(ts) >= 8
    assert len({t.id for t in ts}) == len(ts)
    assert show.pick(None)[0].id == ts[0].id and show.pick("s1e03")[0].title == ts[2].title


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
    topic, theme = show.pick("s1e01")
    p = show.system_prompt(topic, theme)
    assert topic.title in p and "{" not in p
    s = show.to_show(episode(), topic)
    assert s["lang"] == "zh" and set(s["hosts"]) == {"K", "A"}
    assert all(len(r) == 3 and r[0] in "KA" for r in s["lines"])
    md = show.script_md(episode(), topic)
    assert "**阿凱**" in md and "**安妮**" in md


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
