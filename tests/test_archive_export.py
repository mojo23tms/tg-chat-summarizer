import hashlib
import json
from decimal import Decimal

import pytest

from scripts import import_telegram_export
from telegram_summarizer import archive_export


class PagedArchiveStorage:
    def __init__(self, messages_by_chat, memories_by_chat):
        self.messages_by_chat = messages_by_chat
        self.memories_by_chat = memories_by_chat
        self.message_calls = []
        self.memory_calls = []

    def chronological_message_page(
        self,
        chat_id,
        *,
        start_ts,
        end_ts,
        limit,
        exclusive_start_key=None,
    ):
        self.message_calls.append((chat_id, limit))
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

    def memory_page(
        self,
        chat_id,
        *,
        limit,
        exclusive_start_key=None,
    ):
        self.memory_calls.append((chat_id, limit))
        rows = self.memories_by_chat.get(chat_id, [])
        offset = int(exclusive_start_key or 0)
        page = rows[offset : offset + limit]
        next_offset = offset + len(page)
        cursor = next_offset if next_offset < len(rows) else None
        return page, cursor


def messages(count):
    return [
        {
            "msg_id": index + 10,
            "user_id": index + 20,
            "user_name": "Alice <Admin>" if index == 0 else "Bob",
            "text": "<script>not markup</script>" if index == 0 else f"message {index}",
            "ts": index + 100,
        }
        for index in range(count)
    ]


def memories(count):
    return [
        {
            "version": Decimal("1"),
            "created_at": Decimal(str(index + 200)),
            "start_ts": Decimal(str(index + 100)),
            "end_ts": Decimal(str(index + 100)),
            "message_count": Decimal("1"),
            "summary": f"Lore <{index}>",
            "items": [],
        }
        for index in range(count)
    ]


def test_dry_run_is_bounded_chat_scoped_and_creates_no_files(tmp_path):
    storage = PagedArchiveStorage(
        {1: messages(5), 2: messages(20)},
        {1: memories(3), 2: memories(10)},
    )
    output = tmp_path / "archive"

    report = archive_export.create_personal_archive(
        storage,
        1,
        output,
        page_size=2,
        max_messages=3,
        dry_run=True,
    )

    assert report == {
        "status": "dry_run",
        "dry_run": True,
        "chat_id": 1,
        "output_dir": str(output),
        "message_count": 3,
        "memory_count": 3,
        "oldest_message_ts": 100,
        "newest_message_ts": 102,
        "message_truncated": True,
    }
    assert not output.exists()
    assert all(chat_id == 1 for chat_id, _limit in storage.message_calls)
    assert all(limit <= 2 for _chat_id, limit in storage.message_calls)
    assert all(chat_id == 1 for chat_id, _limit in storage.memory_calls)


def test_export_is_readable_restore_compatible_and_checksummed(tmp_path):
    storage = PagedArchiveStorage(
        {1: messages(3), 2: messages(5)},
        {1: memories(2), 2: memories(4)},
    )
    output = tmp_path / "archive"

    report = archive_export.create_personal_archive(
        storage,
        1,
        output,
        archive_name="Friends & Lore",
        page_size=2,
        now_fn=lambda: 500,
    )

    restored = import_telegram_export.load_importable_messages(output / "result.json")
    exported_memories = json.loads(
        (output / "memory-snapshots.json").read_text(encoding="utf-8")
    )
    history = (output / "chat-history.md").read_text(encoding="utf-8")
    memory_markdown = (output / "memory-snapshots.md").read_text(encoding="utf-8")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

    assert report["status"] == "exported"
    assert [message["text"] for message in restored] == [
        "<script>not markup</script>",
        "message 1",
        "message 2",
    ]
    assert len(exported_memories) == 2
    assert exported_memories[0]["version"] == 1
    assert "&lt;script&gt;not markup&lt;/script&gt;" in history
    assert "Alice &lt;Admin&gt;" in history
    assert "Lore &lt;0&gt;" in memory_markdown
    assert manifest["created_at"] == 500
    assert manifest["chat_id"] == 1
    assert manifest["message_count"] == 3
    assert manifest["memory_count"] == 2
    for name, metadata in manifest["files"].items():
        content = (output / name).read_bytes()
        assert metadata["bytes"] == len(content)
        assert metadata["sha256"] == hashlib.sha256(content).hexdigest()


def test_export_refuses_to_replace_existing_directory(tmp_path):
    storage = PagedArchiveStorage({1: []}, {1: []})
    output = tmp_path / "archive"
    output.mkdir()

    with pytest.raises(FileExistsError, match="already exists"):
        archive_export.create_personal_archive(storage, 1, output)


def test_timestamp_range_filters_messages_and_overlapping_memories(tmp_path):
    storage = PagedArchiveStorage({1: messages(5)}, {1: memories(5)})

    report = archive_export.create_personal_archive(
        storage,
        1,
        tmp_path / "archive",
        start_ts=101,
        end_ts=102,
        page_size=2,
        dry_run=True,
    )

    assert report["message_count"] == 2
    assert report["oldest_message_ts"] == 101
    assert report["newest_message_ts"] == 102
    assert report["memory_count"] == 2


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"page_size": 0}, "page_size"),
        ({"page_size": 501}, "page_size"),
        ({"max_messages": -1}, "max_messages"),
        ({"start_ts": 2, "end_ts": 1}, "start_ts"),
    ],
)
def test_export_validates_bounded_options(tmp_path, kwargs, message):
    storage = PagedArchiveStorage({1: []}, {1: []})

    with pytest.raises(ValueError, match=message):
        archive_export.create_personal_archive(
            storage, 1, tmp_path / "archive", dry_run=True, **kwargs
        )
