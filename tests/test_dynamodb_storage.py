from telegram_summarizer import config
from telegram_summarizer.dynamodb_storage import DynamoDBStorage


class FakeTable:
    def __init__(self):
        self.items = []
        self.updated = []

    def put_item(self, Item):
        existing = self.get_item({"pk": Item["pk"], "sk": Item["sk"]}).get("Item")
        if existing is None:
            self.items.append(Item)
        else:
            existing.clear()
            existing.update(Item)

    def query(self, **kwargs):
        values = kwargs["ExpressionAttributeValues"]
        pk = values[":pk"]
        prefix = values.get(":prefix")
        range_start = values.get(":start")
        range_end = values.get(":end")
        limit = kwargs.get("Limit")
        items = [item for item in self.items if item["pk"] == pk]
        if prefix is not None:
            items = [item for item in items if item["sk"].startswith(prefix)]
        if range_start is not None:
            items = [item for item in items if range_start <= item["sk"] <= range_end]
        items.sort(key=lambda item: item["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        start_key = kwargs.get("ExclusiveStartKey")
        if start_key is not None:
            for index, item in enumerate(items):
                if item["pk"] == start_key["pk"] and item["sk"] == start_key["sk"]:
                    items = items[index + 1 :]
                    break
        page = items[:limit] if limit else items
        response = {"Items": page}
        if limit and len(items) > len(page):
            response["LastEvaluatedKey"] = {
                "pk": page[-1]["pk"],
                "sk": page[-1]["sk"],
            }
        return response

    def scan(self, **kwargs):
        return {"Items": [{"pk": item["pk"]} for item in self.items]}

    def get_item(self, Key):
        for item in self.items:
            if item["pk"] == Key["pk"] and item["sk"] == Key["sk"]:
                return {"Item": item}
        return {}

    def update_item(self, **kwargs):
        self.updated.append(kwargs)
        key = kwargs["Key"]
        item = self.get_item(key).get("Item")
        if item is None:
            item = {"pk": key["pk"], "sk": key["sk"]}
            self.items.append(item)
        setting_key = kwargs["ExpressionAttributeNames"]["#key"]
        item[setting_key] = kwargs["ExpressionAttributeValues"][":value"]

    def delete_item(self, Key):
        self.items = [
            item
            for item in self.items
            if not (item["pk"] == Key["pk"] and item["sk"] == Key["sk"])
        ]


class FakeResource:
    def __init__(self, table):
        self.table = table

    def Table(self, table_name):
        return self.table


def adapter(table=None, ttl_days=90):
    table = table or FakeTable()
    return DynamoDBStorage("table", FakeResource(table), ttl_days=ttl_days), table


def test_message_writes_are_scoped_by_chat_and_include_ttl():
    storage, table = adapter(ttl_days=2)

    storage.log_message(1, 5, 10, "alice", "hello", ts=100)

    assert table.items[0]["pk"] == "CHAT#1"
    assert table.items[0]["sk"] == "MSG#00000000000000000100#00000000000000000005"
    assert table.items[0]["expires_at"] == 100 + 2 * 86400
    assert table.items[1]["pk"] == "CHATS"
    assert table.items[1]["sk"] == "CHAT#1"


def test_message_write_can_override_expiration_for_imports():
    storage, table = adapter(ttl_days=2)

    storage.log_message(1, 5, 10, "alice", "hello", ts=100, expires_at=999)

    assert table.items[0]["ts"] == 100
    assert table.items[0]["expires_at"] == 999


def test_recent_message_reads_preserve_chronological_output():
    storage, _table = adapter()
    for ts in range(5):
        storage.log_message(1, ts, 10, f"u{ts}", f"m{ts}", ts=ts)
    storage.log_message(2, 1, 10, "other", "other chat", ts=99)

    rows = storage.recent_messages(1, 3)

    assert [row["text"] for row in rows] == ["m2", "m3", "m4"]


def test_message_pages_are_chat_scoped_time_bounded_and_paginated():
    storage, _table = adapter()
    for ts in range(1, 7):
        storage.log_message(1, ts, 10, "alice", f"m{ts}", ts=ts)
    storage.log_message(2, 99, 20, "other", "wrong chat", ts=4)

    first, cursor = storage.message_page(1, start_ts=2, end_ts=5, limit=2)
    second, next_cursor = storage.message_page(
        1,
        start_ts=2,
        end_ts=5,
        limit=2,
        exclusive_start_key=cursor,
    )

    assert [row["text"] for row in first] == ["m5", "m4"]
    assert [row["text"] for row in second] == ["m3", "m2"]
    assert cursor is not None
    assert next_cursor is None
    assert all(row["user_id"] == 10 for row in first + second)


def test_memory_snapshots_are_idempotent_chat_scoped_and_searchable():
    storage, table = adapter()
    snapshot = {
        "version": 1,
        "created_at": 100,
        "start_ts": 10,
        "end_ts": 20,
        "message_count": 5,
        "summary": "The Ibiza hotel joke",
        "items": [
            {
                "kind": "running_joke",
                "title": "Ibiza",
                "details": "Alice started the hotel joke",
                "people": ["Alice"],
                "keywords": ["ibiza", "hotel"],
                "source_timestamps": [12],
            }
        ],
    }

    storage.save_memory_snapshot(1, snapshot)
    storage.save_memory_snapshot(1, {**snapshot, "summary": "Updated Ibiza lore"})
    storage.save_memory_snapshot(2, {**snapshot, "summary": "Wrong chat"})

    rows = storage.search_memories(1, "ibiza alice", limit=5, scan_limit=10)
    memory_items = [item for item in table.items if item["sk"].startswith("MEMORY#")]
    assert len(memory_items) == 2
    assert memory_items[0]["sk"] == (
        "MEMORY#00000000000000000010#00000000000000000020"
    )
    assert len(rows) == 1
    assert rows[0]["summary"] == "Updated Ibiza lore"
    assert "pk" not in rows[0]
    assert storage.search_memories(1, "missing", limit=5, scan_limit=10) == []
    assert storage.search_memories(
        1, "ibiza", start_ts=21, limit=5, scan_limit=10
    ) == []
    assert len(
        storage.search_memories(
            1, "ibiza", start_ts=15, end_ts=30, limit=5, scan_limit=10
        )
    ) == 1


def test_settings_defaults_merge_with_stored_overrides():
    storage, _table = adapter()

    storage.set_setting(1, "filter_level", "strict")
    settings = storage.get_settings(1)

    assert settings["filter_level"] == "strict"
    assert settings["style"] == config.DEFAULTS["style"]
    assert settings["language"] == config.DEFAULTS["language"]
    assert settings["provider"] == config.DEFAULTS["provider"]
    assert settings["model"] == config.DEFAULTS["model"]


def test_owner_active_chat_round_trips():
    storage, _table = adapter()

    storage.set_owner_active_chat(42, -1001)

    assert storage.get_owner_active_chat(42) == -1001


def test_list_chat_ids_returns_distinct_chat_partitions():
    storage, _table = adapter()
    storage.log_message(2, 1, 10, "b", "hi", ts=1)
    storage.log_message(1, 1, 10, "a", "hi", ts=1)
    storage.log_message(1, 2, 10, "a", "again", ts=2)

    assert storage.list_chat_ids() == [1, 2]


def test_list_chat_ids_falls_back_to_scan_for_legacy_tables():
    table = FakeTable()
    table.items = [
        {"pk": "CHAT#2", "sk": "MSG#00000000000000000001#00000000000000000001"},
        {"pk": "CHAT#1", "sk": "MSG#00000000000000000001#00000000000000000001"},
    ]
    storage, _table = adapter(table=table)

    assert storage.list_chat_ids() == [1, 2]


def test_usage_totals_sum_records_after_since():
    storage, _table = adapter()
    storage.log_usage(
        1,
        {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "estimated": True,
            "provider": "gemini",
            "model": "m",
        },
        messages_count=3,
        ts=100,
    )
    storage.log_usage(
        1,
        {
            "input_tokens": 20,
            "output_tokens": 7,
            "total_tokens": 27,
            "estimated": False,
            "provider": "groq",
            "model": "m",
        },
        messages_count=4,
        ts=200,
    )

    totals = storage.usage_totals(1, since_ts=150)

    assert totals["requests"] == 1
    assert totals["messages_count"] == 4
    assert totals["total_tokens"] == 27


def test_usage_totals_can_filter_by_provider_and_model():
    storage, _table = adapter()
    storage.log_usage(
        1,
        {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "estimated": True,
            "provider": "gemini",
            "model": "gemini-model",
        },
        messages_count=3,
        ts=100,
    )
    storage.log_usage(
        1,
        {
            "input_tokens": 20,
            "output_tokens": 7,
            "total_tokens": 27,
            "estimated": False,
            "provider": "groq",
            "model": "groq-model",
        },
        messages_count=4,
        ts=200,
    )

    totals = storage.usage_totals(1, provider="groq", model="groq-model")

    assert totals["requests"] == 1
    assert totals["messages_count"] == 4
    assert totals["total_tokens"] == 27


def test_quota_warning_marker_round_trips():
    storage, table = adapter()

    assert storage.quota_warning_sent(1, "gemini", "2026-07-08") is False

    storage.mark_quota_warning_sent(1, "gemini", "2026-07-08", ts=100)

    assert storage.quota_warning_sent(1, "gemini", "2026-07-08") is True
    assert table.items[-1]["sk"] == "QUOTA_WARN#gemini#2026-07-08"
    assert table.items[-1]["expires_at"] == 100 + 14 * 86400


def test_usage_records_do_not_collide_with_same_second(monkeypatch):
    values = iter([111, 222])
    monkeypatch.setattr(
        "telegram_summarizer.dynamodb_storage.time.time_ns",
        lambda: next(values),
    )
    storage, table = adapter()
    usage = {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "estimated": True,
        "provider": "gemini",
        "model": "m",
    }

    storage.log_usage(1, usage, messages_count=3, ts=100)
    storage.log_usage(1, usage, messages_count=3, ts=100)

    usage_keys = [item["sk"] for item in table.items if item["sk"].startswith("USAGE#")]
    assert len(usage_keys) == 2
    assert len(set(usage_keys)) == 2


def test_pending_input_state_round_trips_with_ttl():
    storage, table = adapter()

    storage.set_pending_input(42, "set_style_custom", -1001, now=100)

    assert table.items[-1] == {
        "pk": "USER#42",
        "sk": "PENDING",
        "action": "set_style_custom",
        "target_chat_id": -1001,
        "created_at": 100,
        "expires_at": 700,
    }
    assert storage.get_pending_input(42, now=200) == {
        "action": "set_style_custom",
        "target_chat_id": -1001,
        "created_at": 100,
        "expires_at": 700,
    }
    assert storage.get_pending_input(42, now=700) is None


def test_pending_input_delete_removes_state():
    storage, _table = adapter()

    storage.set_pending_input(42, "set_lang_custom", 10, now=100)
    storage.delete_pending_input(42)

    assert storage.get_pending_input(42, now=101) is None
