import pytest

from telegram_summarizer import config
from telegram_summarizer import historical_backfill


SETTINGS = {
    "style": "concise",
    "filter_level": "clean",
    "language": "auto",
    "provider": "gemini",
    "model": "gemini-test",
}


class BackfillStorage:
    def __init__(self, messages_by_chat):
        self.messages_by_chat = messages_by_chat
        self.checkpoint = None
        self.saved = []
        self.usage = []

    def get_settings(self, chat_id):
        return dict(SETTINGS)

    def chronological_message_page(
        self,
        chat_id,
        *,
        start_ts,
        end_ts,
        limit,
        exclusive_start_key=None,
    ):
        rows = [
            message
            for message in self.messages_by_chat.get(chat_id, [])
            if start_ts <= message["ts"] <= end_ts
        ]
        offset = int(exclusive_start_key or 0)
        page = rows[offset : offset + limit]
        next_offset = offset + len(page)
        cursor = next_offset if next_offset < len(rows) else None
        return page, cursor

    def save_memory_snapshot(self, chat_id, snapshot):
        self.saved.append((chat_id, snapshot))

    def message_cursor(self, chat_id, message):
        rows = self.messages_by_chat.get(chat_id, [])
        return rows.index(message) + 1

    def get_backfill_checkpoint(self, chat_id, job_name):
        return dict(self.checkpoint) if self.checkpoint else None

    def save_backfill_checkpoint(self, chat_id, checkpoint, job_name):
        self.checkpoint = dict(checkpoint)

    def clear_backfill_checkpoint(self, chat_id, job_name):
        self.checkpoint = None

    def log_usage(self, chat_id, usage, messages_count, ts=None):
        self.usage.append((chat_id, usage, messages_count, ts))

    def usage_totals(self, chat_id, since_ts=None, provider=None, model=None):
        matching = [
            usage
            for logged_chat_id, usage, _count, ts in self.usage
            if logged_chat_id == chat_id
            and (since_ts is None or ts >= since_ts)
            and (provider is None or usage.get("provider") == provider)
            and (model is None or usage.get("model") == model)
        ]
        return {
            "total_tokens": sum(item.get("total_tokens", 0) for item in matching)
        }


def messages(count, *, prefix="m"):
    return [
        {
            "msg_id": index + 100,
            "user_id": 10,
            "user_name": "Alice",
            "text": f"{prefix}{index}",
            "ts": index + 1,
        }
        for index in range(count)
    ]


def memory_backend(prompt):
    return (
        '{"summary":"chunk lore","items":[{"kind":"running_joke",'
        '"title":"Chunk","details":"A remembered chunk",'
        '"people":["Alice"],"keywords":["chunk"],'
        '"source_timestamps":[1],"source_message_ids":[100]}]}'
    )


def test_dry_run_estimates_chunks_cost_and_never_calls_provider_or_writes():
    storage = BackfillStorage({1: messages(5), 2: messages(20, prefix="wrong")})
    calls = []

    report = historical_backfill.run_backfill(
        storage,
        1,
        chunk_size=2,
        max_messages=5,
        max_input_tokens=2000,
        output_tokens=100,
        input_cost_per_million=1.0,
        output_cost_per_million=2.0,
        dry_run=True,
        backend_fn=lambda prompt: calls.append(prompt),
    )

    assert report["status"] == "complete"
    assert report["processed_messages"] == 5
    assert report["processed_chunks"] == 3
    assert report["estimated_input_tokens"] > 0
    assert report["estimated_output_tokens"] == 300
    assert report["estimated_cost"] > 0
    assert calls == []
    assert storage.saved == []
    assert storage.checkpoint is None


def test_backfill_resumes_without_gaps_and_completed_rerun_is_free():
    storage = BackfillStorage({1: messages(5)})
    calls = []

    first = historical_backfill.run_backfill(
        storage,
        1,
        chunk_size=2,
        max_messages=4,
        max_input_tokens=2000,
        output_tokens=100,
        backend_fn=lambda prompt: calls.append(prompt) or memory_backend(prompt),
        now_fn=lambda: 500,
    )
    second = historical_backfill.run_backfill(
        storage,
        1,
        chunk_size=2,
        max_messages=4,
        max_input_tokens=2000,
        output_tokens=100,
        backend_fn=lambda prompt: calls.append(prompt) or memory_backend(prompt),
        now_fn=lambda: 501,
    )
    third = historical_backfill.run_backfill(
        storage,
        1,
        chunk_size=2,
        max_messages=4,
        max_input_tokens=2000,
        output_tokens=100,
        backend_fn=lambda prompt: calls.append(prompt) or memory_backend(prompt),
    )
    storage.messages_by_chat[1].append(messages(6)[-1])
    fourth = historical_backfill.run_backfill(
        storage,
        1,
        chunk_size=2,
        max_messages=4,
        max_input_tokens=2000,
        output_tokens=100,
        backend_fn=lambda prompt: calls.append(prompt) or memory_backend(prompt),
        now_fn=lambda: 502,
    )

    assert first["status"] == "in_progress"
    assert second["status"] == "complete"
    assert third["processed_messages"] == 0
    assert fourth["processed_messages"] == 1
    assert len(calls) == 4
    assert [
        (snapshot["start_ts"], snapshot["end_ts"], snapshot["message_count"])
        for _chat_id, snapshot in storage.saved
    ] == [(1, 2, 2), (3, 4, 2), (5, 5, 1), (6, 6, 1)]
    assert storage.checkpoint["processed_messages"] == 6
    assert storage.checkpoint["status"] == "complete"
    assert all(chat_id == 1 for chat_id, _snapshot in storage.saved)


def test_provider_failure_keeps_last_checkpoint_and_resume_retries_failed_chunk():
    storage = BackfillStorage({1: messages(4)})
    calls = []

    def fails_second_chunk(prompt):
        calls.append(prompt)
        if len(calls) == 2:
            raise RuntimeError("provider down")
        return memory_backend(prompt)

    with pytest.raises(RuntimeError, match="provider down"):
        historical_backfill.run_backfill(
            storage,
            1,
            chunk_size=2,
            max_messages=4,
            max_input_tokens=2000,
            output_tokens=100,
            backend_fn=fails_second_chunk,
            now_fn=lambda: 500,
        )

    assert storage.checkpoint["processed_messages"] == 2
    assert [(item[1]["start_ts"], item[1]["end_ts"]) for item in storage.saved] == [
        (1, 2)
    ]

    historical_backfill.run_backfill(
        storage,
        1,
        chunk_size=2,
        max_messages=4,
        max_input_tokens=2000,
        output_tokens=100,
        backend_fn=memory_backend,
        now_fn=lambda: 501,
    )

    assert [(item[1]["start_ts"], item[1]["end_ts"]) for item in storage.saved] == [
        (1, 2),
        (3, 4),
    ]


def test_backfill_rejects_range_change_until_checkpoint_is_reset():
    storage = BackfillStorage({1: messages(3)})
    storage.checkpoint = {
        "status": "in_progress",
        "start_ts": 0,
        "end_ts": 100,
        "processed_messages": 1,
        "processed_chunks": 1,
        "cursor": 1,
    }

    with pytest.raises(
        historical_backfill.BackfillConfigurationError,
        match="different time range",
    ):
        historical_backfill.run_backfill(
            storage,
            1,
            start_ts=5,
            end_ts=100,
            dry_run=True,
        )


def test_cost_cap_stops_before_provider_call_or_checkpoint():
    storage = BackfillStorage({1: messages(2)})
    calls = []

    with pytest.raises(
        historical_backfill.BackfillConfigurationError,
        match="max-estimated-cost",
    ):
        historical_backfill.run_backfill(
            storage,
            1,
            chunk_size=2,
            max_messages=2,
            max_input_tokens=2000,
            output_tokens=100,
            input_cost_per_million=1000,
            output_cost_per_million=1000,
            max_estimated_cost=0.01,
            backend_fn=lambda prompt: calls.append(prompt),
        )

    assert calls == []
    assert storage.checkpoint is None


def test_report_warns_when_configured_daily_quota_threshold_is_reached(monkeypatch):
    storage = BackfillStorage({1: messages(1)})
    monkeypatch.setitem(config.DAILY_TOKEN_QUOTAS, "gemini", 1)

    report = historical_backfill.run_backfill(
        storage,
        1,
        chunk_size=1,
        max_messages=1,
        max_input_tokens=2000,
        output_tokens=100,
        backend_fn=memory_backend,
        now_fn=lambda: 100,
    )

    assert report["configured_daily_quota"] == 1
    assert report["quota_total_tokens"] > 1
    assert report["quota_warning"] is True
