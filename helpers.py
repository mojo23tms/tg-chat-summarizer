import html
import re

import config


def parse_count(arg):
    try:
        n = int(arg)
    except (TypeError, ValueError):
        return config.DEFAULT_COUNT
    return max(1, min(n, config.MAX_COUNT))


def format_mention(user_id, name):
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


def scrub(text, filter_level, wordlist):
    if filter_level == "off" or not wordlist:
        return text

    def mask(match):
        return "*" * len(match.group(0))

    pattern = r"\b(" + "|".join(re.escape(w) for w in wordlist) + r")\b"
    return re.sub(pattern, mask, text, flags=re.IGNORECASE)
