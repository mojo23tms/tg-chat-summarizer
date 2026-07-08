from telegram_summarizer import config
from telegram_summarizer.dynamodb_storage import DynamoDBStorage


class FakeTable:
    def __init__(self):
        self.items = []
        self.updated = []

    def put_item(self, Item):
        self.items.append(Item)

    def query(self, **kwargs):
        pk = kwargs["ExpressionAttributeValues"][":pk"]
        prefix = kwargs["ExpressionAttributeValues"].get(":prefix")
        limit = kwargs.get("Limit")
        items = [item for item in self.items if item["pk"] == pk]
        if prefix is not None:
            items = [item for item in items if item["sk"].startswith(prefix)]
        items.sort(key=lambda item: item["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        return {"Items": items[:limit] if limit else items}

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


def test_settings_defaults_merge_with_stored_overrides():
    storage, _table = adapter()

    storage.set_setting(1, "filter_level", "strict")
    settings = storage.get_settings(1)

    assert settings["filter_level"] == "strict"
    assert settings["style"] == config.DEFAULTS["style"]
    assert settings["language"] == config.DEFAULTS["language"]


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
            "model": "m",
        },
        messages_count=4,
        ts=200,
    )

    totals = storage.usage_totals(1, since_ts=150)

    assert totals["requests"] == 1
    assert totals["messages_count"] == 4
    assert totals["total_tokens"] == 27


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
