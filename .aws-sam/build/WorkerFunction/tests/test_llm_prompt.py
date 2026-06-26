from telegram_summarizer import llm


def test_prompt_includes_transcript_and_style():
    msgs = [{"user_name": "alice", "text": "ship it"},
            {"user_name": "bob", "text": "lgtm"}]
    settings = {"style": "one short paragraph", "filter_level": "off", "language": "auto"}
    p = llm.build_prompt(msgs, settings)
    assert "alice: ship it" in p
    assert "bob: lgtm" in p
    assert "one short paragraph" in p


def test_prompt_filter_levels_differ():
    msgs = [{"user_name": "a", "text": "x"}]
    base = {"style": "s", "language": "auto"}
    clean = llm.build_prompt(msgs, {**base, "filter_level": "clean"})
    strict = llm.build_prompt(msgs, {**base, "filter_level": "strict"})
    off = llm.build_prompt(msgs, {**base, "filter_level": "off"})
    assert llm.FILTER_INSTRUCTIONS["clean"] in clean
    assert llm.FILTER_INSTRUCTIONS["strict"] in strict
    assert llm.FILTER_INSTRUCTIONS["off"] in off
    assert clean != strict


def test_prompt_language_explicit():
    msgs = [{"user_name": "a", "text": "x"}]
    p = llm.build_prompt(msgs, {"style": "s", "filter_level": "off", "language": "uk"})
    assert "uk" in p
