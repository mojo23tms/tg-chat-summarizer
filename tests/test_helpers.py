from html.parser import HTMLParser

from telegram_summarizer import config
from telegram_summarizer import helpers


class BalanceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack
        assert self.stack.pop() == tag


def assert_balanced(html):
    parser = BalanceParser()
    parser.feed(html)
    parser.close()
    assert parser.stack == []


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


def test_render_telegram_html_repairs_malformed_html():
    out = helpers.render_telegram_html("<b>one <i>two</b> three")

    assert out == "<b>one <i>two</i></b> three"
    assert_balanced(out)


def test_render_telegram_html_removes_unsupported_tags_and_attributes():
    out = helpers.render_telegram_html(
        '<b class="loud">Win</b> <a href="https://example.com">link</a>'
    )

    assert out == "<b>Win</b> link"


def test_render_summary_html_converts_markdown_bold_as_fallback():
    assert helpers.render_summary_html("**Important**") == "<b>Important</b>"


def test_split_telegram_html_splits_long_plain_text_under_limit():
    chunks = helpers.split_telegram_html("x" * 5000)

    assert len(chunks) == 2
    assert all(len(chunk) <= helpers.TELEGRAM_MESSAGE_LIMIT for chunk in chunks)
    assert "".join(chunks) == "x" * 5000


def test_split_telegram_html_keeps_chunks_balanced():
    safe_html = helpers.render_telegram_html("<b>one <i>two</b> three</i>" * 900)

    chunks = helpers.split_telegram_html(safe_html)

    assert len(chunks) > 1
    assert all(len(chunk) <= helpers.TELEGRAM_MESSAGE_LIMIT for chunk in chunks)
    for chunk in chunks:
        assert_balanced(chunk)


def test_split_telegram_html_closes_and_reopens_open_tags():
    chunks = helpers.split_telegram_html("<b>" + ("x" * 60) + "</b>", limit=25)

    assert len(chunks) > 1
    assert chunks[0].startswith("<b>")
    assert chunks[0].endswith("</b>")
    assert chunks[1].startswith("<b>")
    assert chunks[1].endswith("</b>")
    assert all(len(chunk) <= 25 for chunk in chunks)
    for chunk in chunks:
        assert_balanced(chunk)


def test_scrub_masks_only_when_filtering():
    wl = {"darn"}
    assert helpers.scrub("oh darn", "off", wl) == "oh darn"
    assert helpers.scrub("oh DARN it", "clean", wl) == "oh **** it"
    assert helpers.scrub("darning socks", "strict", wl) == "darning socks"  # whole word only
