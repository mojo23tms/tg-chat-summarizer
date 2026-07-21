from telegram_summarizer import config


def test_defaults_present():
    assert config.DEFAULT_COUNT == 30
    assert config.SUMMARY_MAX_MESSAGES == 5000
    assert config.MAX_COUNT == config.SUMMARY_MAX_MESSAGES
    assert config.MESSAGE_TTL_DAYS == 365
    assert config.MAX_INPUT_TOKENS == 25000
    assert config.SUMMARY_OUTPUT_TOKENS == 1500
    assert config.ASK_OUTPUT_TOKENS == 500
    assert config.MEMORY_OUTPUT_TOKENS == 1000
    assert config.MEMORY_MAX_MESSAGES == 500
    assert config.GEMINI_DAILY_TOKEN_QUOTA == 0
    assert config.GROQ_DAILY_TOKEN_QUOTA == 0
    assert config.QUOTA_WARNING_REMAINING_PERCENT == 10
    assert config.DAILY_TOKEN_QUOTAS == {"gemini": 0, "groq": 0}
    assert config.DISK_HEADROOM == 0.10
    assert set(config.DEFAULTS) == {
        "style",
        "filter_level",
        "language",
        "provider",
        "model",
    }
    assert config.DEFAULTS["filter_level"] == "clean"
    assert config.DEFAULTS["language"] == "auto"
    assert config.DEFAULTS["provider"] == "gemini"
    assert config.DEFAULTS["model"] == ""


def test_int_env_parsing(monkeypatch):
    monkeypatch.setenv("EXAMPLE_INT", "42")
    assert config._int_env("EXAMPLE_INT", 1) == 42

    monkeypatch.setenv("EXAMPLE_INT", "")
    assert config._int_env("EXAMPLE_INT", 1) == 1


def test_owner_ids_parsing(monkeypatch):
    monkeypatch.setenv("EXAMPLE_IDS", "1, 2,3")
    assert config._int_set_env("EXAMPLE_IDS") == {1, 2, 3}


def test_secret_or_env_prefers_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "from-env")
    monkeypatch.setattr(config, "_SECRET_CACHE", {"TELEGRAM_TOKEN": "from-secret"})

    assert config._secret_or_env("TELEGRAM_TOKEN") == "from-env"


def test_secret_or_env_reads_cached_secret(monkeypatch):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.setattr(config, "_SECRET_CACHE", {"TELEGRAM_TOKEN": "from-secret"})

    assert config._secret_or_env("TELEGRAM_TOKEN") == "from-secret"


def test_load_app_secret_from_client():
    class FakeSecrets:
        def get_secret_value(self, SecretId):
            assert SecretId == "secret-id"
            return {"SecretString": '{"TELEGRAM_TOKEN":"token"}'}

    assert config._load_app_secret("secret-id", FakeSecrets()) == {
        "TELEGRAM_TOKEN": "token"
    }
