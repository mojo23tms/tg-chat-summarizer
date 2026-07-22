import json

from scripts import import_telegram_export as importer
from telegram_summarizer.retrieval import (
    ChatHistoryRetriever,
    RetrievalRequest,
    rank_memory_snapshots,
)


class MemoryMessageStorage:
    def __init__(self):
        self.messages = {}
        self.requested_chat_ids = []

    def log_message(
        self, chat_id, msg_id, user_id, user_name, text, ts, expires_at=None
    ):
        self.messages[(int(chat_id), int(ts), int(msg_id))] = {
            "msg_id": int(msg_id),
            "user_id": int(user_id),
            "user_name": user_name,
            "text": text,
            "ts": int(ts),
        }

    def message_page(
        self,
        chat_id,
        *,
        start_ts,
        end_ts,
        limit,
        exclusive_start_key=None,
    ):
        self.requested_chat_ids.append(chat_id)
        rows = [
            message
            for (stored_chat_id, ts, _msg_id), message in self.messages.items()
            if stored_chat_id == int(chat_id) and start_ts <= ts <= end_ts
        ]
        rows.sort(key=lambda item: (item["ts"], item["msg_id"]), reverse=True)
        offset = int(exclusive_start_key or 0)
        page = rows[offset : offset + limit]
        next_offset = offset + len(page)
        cursor = next_offset if next_offset < len(rows) else None
        return page, cursor


def _log(storage, chat_id, msg_id, user_id, user_name, text, ts):
    storage.log_message(chat_id, msg_id, user_id, user_name, text, ts)


def test_retrieval_filters_keywords_user_and_dates_with_chat_isolation():
    storage = MemoryMessageStorage()
    _log(storage, 1, 1, 10, "Alice", "Ibiza plan started", 100)
    _log(storage, 1, 2, 20, "Bob", "unrelated lunch", 110)
    _log(storage, 1, 3, 10, "Alice", "Ibiza hotel joke", 120)
    _log(storage, 2, 4, 10, "Alice", "Ibiza wrong chat", 115)
    retriever = ChatHistoryRetriever(storage, page_size=2)

    result = retriever.retrieve(
        1,
        RetrievalRequest(
            query="Ibiza",
            user="ali",
            start_ts=105,
            end_ts=125,
            limit=5,
            scan_limit=10,
        ),
    )

    assert [message["text"] for message in result.messages] == ["Ibiza hotel joke"]
    assert storage.requested_chat_ids == [1]
    assert result.truncated is False


def test_retrieval_is_bounded_and_reports_truncation():
    storage = MemoryMessageStorage()
    for index in range(10):
        _log(storage, 1, index, 10, "Alice", f"old lore {index}", index)
    retriever = ChatHistoryRetriever(storage, page_size=2)

    result = retriever.retrieve(
        1,
        RetrievalRequest(query="missing", limit=3, scan_limit=5),
    )

    assert result.messages == []
    assert result.scanned_count == 5
    assert result.truncated is True
    assert len(storage.requested_chat_ids) == 3


def test_recent_retrieval_returns_latest_messages_in_chronological_order():
    storage = MemoryMessageStorage()
    for index in range(6):
        _log(storage, 1, index, 10, "Alice", f"m{index}", index)

    result = ChatHistoryRetriever(storage, page_size=3).retrieve(
        1,
        RetrievalRequest(limit=3, scan_limit=10),
    )

    assert [message["text"] for message in result.messages] == ["m3", "m4", "m5"]
    assert result.scanned_count == 3


def test_empty_memory_query_samples_across_full_history_without_embeddings():
    memories = [
        {"start_ts": index * 10, "end_ts": index * 10 + 9, "created_at": index}
        for index in range(10)
    ]

    selected = rank_memory_snapshots(memories, "", limit=4)

    assert [memory["start_ts"] for memory in selected] == [0, 30, 60, 90]


def test_s3_backfill_is_idempotent_bounded_and_retrievable():
    export = {
        "messages": [
            {
                "id": index,
                "type": "message",
                "date_unixtime": str(100 + index),
                "from": "Alice",
                "from_id": "user10",
                "text": f"archive lore {index}",
            }
            for index in range(6)
        ]
    }

    class Result:
        returncode = 0
        stdout = json.dumps(export)
        stderr = ""

    messages = importer.load_s3_importable_messages(
        "s3://private-chat/result.json",
        "eu-central-1",
        command_runner=lambda *args, **kwargs: Result(),
    )
    selected = importer.select_messages(messages, limit=3)
    storage = MemoryMessageStorage()

    importer.import_messages(selected, -1001, storage, progress_every=0)
    importer.import_messages(selected, -1001, storage, progress_every=0)

    assert len(storage.messages) == 3
    result = ChatHistoryRetriever(storage).retrieve(
        -1001,
        RetrievalRequest(query="archive", limit=10, scan_limit=10),
    )
    assert [message["msg_id"] for message in result.messages] == [3, 4, 5]
