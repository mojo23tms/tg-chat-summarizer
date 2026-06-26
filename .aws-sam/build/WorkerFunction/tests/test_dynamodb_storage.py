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
        prefix = kwargs["ExpressionAttributeValues"][":prefix"]
        limit = kwargs.get("Limit")
        items = [
            item for item in self.items
            if item["pk"] == pk and item["sk"].startswith(prefix)
        ]
        items.sort(key=lambda item: item["sk"], reverse=not kwargs["ScanIndexForward"])
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
