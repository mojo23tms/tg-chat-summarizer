import re
import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RetrievalRequest:
    query: str = ""
    user: str | int | None = None
    start_ts: int | None = None
    end_ts: int | None = None
    limit: int = 20
    scan_limit: int = 1000


@dataclass(frozen=True)
class RetrievalResult:
    messages: list[dict] = field(default_factory=list)
    scanned_count: int = 0
    truncated: bool = False


def _keywords(query):
    return tuple(dict.fromkeys(re.findall(r"\w+", str(query).casefold())))


def _user_matches(message, user):
    if user is None or user == "":
        return True
    if isinstance(user, int):
        return int(message.get("user_id", 0)) == user
    value = str(user).strip().casefold()
    if not value:
        return True
    return value in str(message.get("user_name", "")).casefold()


def _keyword_score(message, keywords):
    if not keywords:
        return 1
    text = str(message.get("text", "")).casefold()
    return sum(1 for keyword in keywords if keyword in text)


def rank_memory_snapshots(memories, query, limit):
    keywords = _keywords(query)
    ranked = []
    for index, memory in enumerate(memories):
        search_text = json.dumps(memory, ensure_ascii=False, default=str).casefold()
        score = (
            sum(1 for keyword in keywords if keyword in search_text)
            if keywords
            else 1
        )
        if score:
            ranked.append((score, int(memory.get("created_at", 0)), -index, memory))
    return [
        memory
        for _score, _created_at, _index, memory in sorted(ranked, reverse=True)[
            : int(limit)
        ]
    ]


class ChatHistoryRetriever:
    """Bounded retrieval over a chat-scoped message storage adapter."""

    def __init__(self, storage, page_size=100):
        page_size = int(page_size)
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self.storage = storage
        self.page_size = page_size

    def retrieve(self, chat_id, request=None):
        request = request or RetrievalRequest()
        limit = int(request.limit)
        scan_limit = int(request.scan_limit)
        if limit < 1:
            raise ValueError("limit must be positive")
        if scan_limit < 1:
            raise ValueError("scan_limit must be positive")

        keywords = _keywords(request.query)
        start_ts = 0 if request.start_ts is None else int(request.start_ts)
        end_ts = 99_999_999_999 if request.end_ts is None else int(request.end_ts)
        if start_ts > end_ts:
            return RetrievalResult()

        candidates = []
        scanned_count = 0
        cursor = None
        exhausted = False

        while scanned_count < scan_limit:
            page_limit = min(self.page_size, scan_limit - scanned_count)
            messages, cursor = self.storage.message_page(
                chat_id,
                start_ts=start_ts,
                end_ts=end_ts,
                limit=page_limit,
                exclusive_start_key=cursor,
            )
            scanned_count += len(messages)
            for message in messages:
                if not _user_matches(message, request.user):
                    continue
                score = _keyword_score(message, keywords)
                if score:
                    candidates.append((score, message))

            if cursor is None:
                exhausted = True
                break
            if not keywords and (request.user is None or request.user == ""):
                if len(candidates) >= limit:
                    break

        ranked = sorted(
            candidates,
            key=lambda item: (
                item[0],
                int(item[1].get("ts", 0)),
                int(item[1].get("msg_id", 0)),
            ),
            reverse=True,
        )[:limit]
        messages = sorted(
            (message for _score, message in ranked),
            key=lambda message: (
                int(message.get("ts", 0)),
                int(message.get("msg_id", 0)),
            ),
        )
        return RetrievalResult(
            messages=messages,
            scanned_count=scanned_count,
            truncated=not exhausted and cursor is not None,
        )
