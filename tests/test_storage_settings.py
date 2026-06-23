import config
import storage


def test_get_settings_returns_defaults_when_empty():
    conn = storage.connect(":memory:")
    assert storage.get_settings(conn, 1) == config.DEFAULTS


def test_set_and_get_setting_override():
    conn = storage.connect(":memory:")
    storage.set_setting(conn, 1, "filter_level", "strict")
    storage.set_setting(conn, 1, "style", "formal paragraphs")
    s = storage.get_settings(conn, 1)
    assert s["filter_level"] == "strict"
    assert s["style"] == "formal paragraphs"
    assert s["language"] == config.DEFAULTS["language"]  # untouched default


def test_set_setting_is_upsert():
    conn = storage.connect(":memory:")
    storage.set_setting(conn, 1, "filter_level", "off")
    storage.set_setting(conn, 1, "filter_level", "strict")
    assert storage.get_settings(conn, 1)["filter_level"] == "strict"
