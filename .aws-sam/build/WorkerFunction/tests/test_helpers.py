from telegram_summarizer import config
from telegram_summarizer import helpers


def test_parse_count_default_and_clamp():
    assert helpers.parse_count(None) == config.DEFAULT_COUNT
    assert helpers.parse_count("abc") == config.DEFAULT_COUNT
    assert helpers.parse_count("0") == 1
    assert helpers.parse_count("5") == 5
    assert helpers.parse_count(str(config.MAX_COUNT + 50)) == config.MAX_COUNT


def test_format_mention_escapes_html():
    out = helpers.format_mention(42, "A&B <x>")
    assert out == '<a href="tg://user?id=42">A&amp;B &lt;x&gt;</a>'


def test_escape_html_text_escapes_summary_content():
    assert helpers.escape_html_text("2 < 3 & ok") == "2 &lt; 3 &amp; ok"


def test_render_summary_html_allows_safe_telegram_tags_and_escapes_text():
    out = helpers.render_summary_html("<b>Win</b> 2 < 3 <script>x</script>")
    assert out == "<b>Win</b> 2 &lt; 3 x"


def test_render_summary_html_converts_markdown_bold_as_fallback():
    assert helpers.render_summary_html("**Important**") == "<b>Important</b>"


def test_scrub_masks_only_when_filtering():
    wl = {"darn"}
    assert helpers.scrub("oh darn", "off", wl) == "oh darn"
    assert helpers.scrub("oh DARN it", "clean", wl) == "oh **** it"
    assert helpers.scrub("darning socks", "strict", wl) == "darning socks"  # whole word only
