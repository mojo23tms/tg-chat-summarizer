import html
import re
from html.parser import HTMLParser

from . import config


def parse_count(arg):
    try:
        n = int(arg)
    except (TypeError, ValueError):
        return config.DEFAULT_COUNT
    return max(1, min(n, config.SUMMARY_MAX_MESSAGES))


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

TELEGRAM_MESSAGE_LIMIT = 4096


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


def render_telegram_html(text):
    parser = _TelegramHtmlSanitizer()
    parser.feed(_markdown_bold_to_html(text))
    parser.close()
    parser.close_open_tags()
    return "".join(parser.parts)


def render_summary_html(text):
    return render_telegram_html(text)


_HTML_TOKEN_RE = re.compile(r"(<[^>]+>|&(?:[A-Za-z][A-Za-z0-9]+|#[0-9]+|#x[0-9A-Fa-f]+);)")
_START_TAG_RE = re.compile(r"<([A-Za-z][A-Za-z0-9]*)(?:\s[^>]*)?>")
_END_TAG_RE = re.compile(r"</([A-Za-z][A-Za-z0-9]*)>")


def _html_units(text):
    pos = 0
    for match in _HTML_TOKEN_RE.finditer(text):
        if match.start() > pos:
            yield from text[pos : match.start()]
        yield match.group(0)
        pos = match.end()
    if pos < len(text):
        yield from text[pos:]


def _closing_tags(stack):
    return "".join(f"</{tag}>" for tag in reversed(stack))


def _opening_tags(stack):
    return "".join(f"<{tag}>" for tag in stack)


def _stack_after_unit(stack, unit):
    start = _START_TAG_RE.fullmatch(unit)
    if start:
        tag = start.group(1).lower()
        return [*stack, tag]
    end = _END_TAG_RE.fullmatch(unit)
    if end:
        tag = end.group(1).lower()
        if tag not in stack:
            return list(stack)
        next_stack = list(stack)
        while next_stack:
            open_tag = next_stack.pop()
            if open_tag == tag:
                break
        return next_stack
    return list(stack)


def split_telegram_html(safe_html, limit=TELEGRAM_MESSAGE_LIMIT):
    if limit < 1:
        raise ValueError("limit must be positive")
    if not safe_html:
        return []

    chunks = []
    current = ""
    stack = []

    for unit in _html_units(safe_html):
        next_stack = _stack_after_unit(stack, unit)
        if len(current + unit + _closing_tags(next_stack)) <= limit:
            current += unit
            stack = next_stack
            continue

        if current:
            chunks.append(current + _closing_tags(stack))
            current = _opening_tags(stack)

        if len(current + unit + _closing_tags(next_stack)) <= limit:
            current += unit
            stack = next_stack
            continue

        if _START_TAG_RE.fullmatch(unit) or _END_TAG_RE.fullmatch(unit):
            if current:
                chunks.append(current + _closing_tags(stack))
                current = ""
            if len(unit) <= limit:
                chunks.append(unit)
            else:
                chunks.extend(unit[i : i + limit] for i in range(0, len(unit), limit))
            stack = next_stack
            continue

        while unit:
            suffix = _closing_tags(stack)
            capacity = limit - len(current) - len(suffix)
            if capacity <= 0:
                if current:
                    chunks.append(current + suffix)
                current = _opening_tags(stack)
                capacity = limit - len(current) - len(suffix)
            if capacity <= 0:
                stack = []
                current = ""
                capacity = limit
            current += unit[:capacity]
            unit = unit[capacity:]
            if unit:
                chunks.append(current + _closing_tags(stack))
                current = _opening_tags(stack)

    if current:
        chunks.append(current + _closing_tags(stack))
    return chunks


def scrub(text, filter_level, wordlist):
    if filter_level == "off" or not wordlist:
        return text

    def mask(match):
        return "*" * len(match.group(0))

    pattern = r"\b(" + "|".join(re.escape(w) for w in wordlist) + r")\b"
    return re.sub(pattern, mask, text, flags=re.IGNORECASE)
