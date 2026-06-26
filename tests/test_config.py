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


def test_int_env_parsing(monkeypatch):
    monkeypatch.setenv("EXAMPLE_INT", "42")
    assert config._int_env("EXAMPLE_INT", 1) == 42

    monkeypatch.setenv("EXAMPLE_INT", "")
    assert config._int_env("EXAMPLE_INT", 1) == 1


def test_owner_ids_parsing(monkeypatch):
    monkeypatch.setenv("EXAMPLE_IDS", "1, 2,3")
    assert config._int_set_env("EXAMPLE_IDS") == {1, 2, 3}
