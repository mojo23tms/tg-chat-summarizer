from telegram_summarizer import config


def test_defaults_present():
    assert config.DEFAULT_COUNT == 30
    assert config.MAX_COUNT == 200
    assert config.MESSAGE_TTL_DAYS == 365
    assert config.MAX_INPUT_TOKENS == 25000
    assert config.SUMMARY_OUTPUT_TOKENS == 1500
    assert config.DISK_HEADROOM == 0.10
    assert set(config.DEFAULTS) == {"style", "filter_level", "language"}
    assert config.DEFAULTS["filter_level"] == "clean"
    assert config.DEFAULTS["language"] == "auto"
