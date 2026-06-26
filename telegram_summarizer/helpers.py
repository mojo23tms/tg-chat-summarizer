import html
import re
from html.parser import HTMLParser

from . import config


def parse_count(arg):
    try:
        n = int(arg)
    except (TypeError, ValueError):
        return config.DEFAULT_COUNT
    return max(1, min(n, config.MAX_COUNT))


def format_mention(user_id, name):
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


def escape_html_text(text):
    return html.escape(text)


ALLOWED_TELEGRAM_HTML_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "s",
    "code",
    "pre",
    "blockquote",
}


class _TelegramHtmlSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag not in ALLOWED_TELEGRAM_HTML_TAGS:
            return
        self.parts.append(f"<{tag}>")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag not in self.stack:
            return
        while self.stack:
            open_tag = self.stack.pop()
            self.parts.append(f"</{open_tag}>")
            if open_tag == tag:
                break

    def handle_data(self, data):
        self.parts.append(html.escape(data))

    def close_open_tags(self):
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")


def _markdown_bold_to_html(text):
    return re.sub(r"\*\*([^*\n][\s\S]*?)\*\*", r"<b>\1</b>", text)


def render_summary_html(text):
    parser = _TelegramHtmlSanitizer()
    parser.feed(_markdown_bold_to_html(text))
    parser.close()
    parser.close_open_tags()
    return "".join(parser.parts)


def scrub(text, filter_level, wordlist):
    if filter_level == "off" or not wordlist:
        return text

    def mask(match):
        return "*" * len(match.group(0))

    pattern = r"\b(" + "|".join(re.escape(w) for w in wordlist) + r")\b"
    return re.sub(pattern, mask, text, flags=re.IGNORECASE)
