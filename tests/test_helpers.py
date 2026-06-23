import config
import helpers


def test_parse_count_default_and_clamp():
    assert helpers.parse_count(None) == config.DEFAULT_COUNT
    assert helpers.parse_count("abc") == config.DEFAULT_COUNT
    assert helpers.parse_count("0") == 1
    assert helpers.parse_count("5") == 5
    assert helpers.parse_count(str(config.MAX_COUNT + 50)) == config.MAX_COUNT


def test_format_mention_escapes_html():
    out = helpers.format_mention(42, "A&B <x>")
    assert out == '<a href="tg://user?id=42">A&amp;B &lt;x&gt;</a>'


def test_scrub_masks_only_when_filtering():
    wl = {"darn"}
    assert helpers.scrub("oh darn", "off", wl) == "oh darn"
    assert helpers.scrub("oh DARN it", "clean", wl) == "oh **** it"
    assert helpers.scrub("darning socks", "strict", wl) == "darning socks"  # whole word only
