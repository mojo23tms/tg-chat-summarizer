import json

from scripts import import_telegram_export as importer


def test_default_region_prefers_env(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    assert importer.default_region() == "eu-central-1"

    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    assert importer.default_region() == "us-east-1"

    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    assert importer.default_region() == "eu-west-1"


def test_normalize_message_handles_string_text():
    message = {
        "id": 7,
        "type": "message",
        "date_unixtime": "1710000000",
        "from": "Alice",
        "from_id": "user123",
        "text": "hello",
    }

    assert importer.normalize_message(message) == {
        "msg_id": 7,
        "user_id": 123,
        "user_name": "Alice",
        "text": "hello",
        "ts": 1710000000,
    }


def test_normalize_message_handles_rich_text_and_skips_empty():
    message = {
        "id": 8,
        "type": "message",
        "date_unixtime": "1710000001",
        "from": "Bob",
        "from_id": "user456",
        "text": ["hello ", {"type": "bold", "text": "world"}],
    }

    assert importer.normalize_message(message)["text"] == "hello world"
    assert importer.normalize_message({"type": "message", "text": ""}) is None
    assert importer.normalize_message({"type": "service", "text": "joined"}) is None


def test_load_importable_messages_filters_export(tmp_path):
    export = {
        "messages": [
            {
                "id": 1,
                "type": "service",
                "text": "created group",
            },
            {
                "id": 2,
                "type": "message",
                "date_unixtime": "1710000002",
                "from": "Alice",
                "from_id": "user123",
                "text": "kept",
            },
        ]
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(export), encoding="utf-8")

    messages = importer.load_importable_messages(path)

    assert len(messages) == 1
    assert messages[0]["text"] == "kept"


def test_load_s3_importable_messages_uses_offline_aws_cli_source():
    calls = []
    export = {
        "messages": [
            {
                "id": 2,
                "type": "message",
                "date_unixtime": "1710000002",
                "from": "Alice",
                "from_id": "user123",
                "text": "from s3",
            }
        ]
    }

    def fake_run(command, check, capture_output, text):
        calls.append(command)

        class Result:
            returncode = 0
            stdout = json.dumps(export)
            stderr = ""

        return Result()

    messages = importer.load_s3_importable_messages(
        "s3://private-chat/result.json",
        "eu-central-1",
        command_runner=fake_run,
    )

    assert messages[0]["text"] == "from s3"
    assert calls == [
        [
            "aws",
            "s3",
            "cp",
            "s3://private-chat/result.json",
            "-",
            "--region",
            "eu-central-1",
        ]
    ]


def test_load_s3_importable_messages_rejects_non_s3_source():
    try:
        importer.load_s3_importable_messages("/tmp/result.json", "eu-central-1")
    except ValueError as exc:
        assert "s3://" in str(exc)
    else:
        raise AssertionError("non-S3 source should be rejected")


def test_select_messages_can_skip_latest_before_limit():
    messages = [{"msg_id": index} for index in range(10)]

    assert [m["msg_id"] for m in importer.select_messages(messages, limit=3)] == [7, 8, 9]
    assert [m["msg_id"] for m in importer.select_messages(messages, limit=0, skip_latest=3)] == [
        0,
        1,
        2,
        3,
        4,
        5,
        6,
    ]
    assert [m["msg_id"] for m in importer.select_messages(messages, limit=3, skip_latest=3)] == [
        4,
        5,
        6,
    ]
    assert importer.select_messages(messages, limit=0, skip_latest=99) == []


def test_import_messages_uses_existing_storage_shape():
    calls = []

    class FakeStorage:
        def log_message(self, *args, **kwargs):
            calls.append((args, kwargs))

    importer.import_messages(
        [
            {
                "msg_id": 2,
                "user_id": 123,
                "user_name": "Alice",
                "text": "hello",
                "ts": 1710000002,
            }
        ],
        chat_id=-1001,
        storage=FakeStorage(),
        expires_at=1741536002,
        progress_every=0,
    )

    assert calls == [
        ((-1001, 2, 123, "Alice", "hello", 1710000002), {"expires_at": 1741536002})
    ]


def test_dynamodb_item_matches_live_storage_keys():
    item = importer.dynamodb_item(
        -1001,
        {
            "msg_id": 2,
            "user_id": 123,
            "user_name": "Alice",
            "text": "hello",
            "ts": 1710000002,
        },
        expires_at=1741536002,
    )

    assert item["pk"] == {"S": "CHAT#-1001"}
    assert item["sk"] == {"S": "MSG#00000000001710000002#00000000000000000002"}
    assert item["expires_at"] == {"N": "1741536002"}


def test_dynamodb_chat_index_item_matches_storage_index():
    assert importer.dynamodb_chat_index_item(-1001) == {
        "pk": {"S": "CHATS"},
        "sk": {"S": "CHAT#-1001"},
        "chat_id": {"N": "-1001"},
    }


def test_import_messages_with_aws_cli_batches_without_network(monkeypatch):
    calls = []

    def fake_run(command, check, capture_output, text):
        calls.append(command)

        class Result:
            returncode = 0
            stdout = "{}"
            stderr = ""

        return Result()

    monkeypatch.setattr(importer.subprocess, "run", fake_run)
    importer.import_messages_with_aws_cli(
        [
            {
                "msg_id": index,
                "user_id": 123,
                "user_name": "Alice",
                "text": "hello",
                "ts": 1710000000 + index,
            }
            for index in range(26)
        ],
        chat_id=-1001,
        table_name="table",
        region="eu-central-1",
        expires_at=1741536002,
        progress_every=0,
    )

    assert len(calls) == 3
    assert calls[0][:3] == ["aws", "dynamodb", "batch-write-item"]
    assert "--region" in calls[0]


def test_aws_cli_batch_write_retries_unprocessed_items(monkeypatch):
    calls = []

    def fake_run(command, check, capture_output, text):
        calls.append(command)

        class Result:
            returncode = 0
            stderr = ""

            @property
            def stdout(self):
                if len(calls) == 1:
                    return json.dumps({"UnprocessedItems": {"table": []}})
                return "{}"

        return Result()

    monkeypatch.setattr(importer.subprocess, "run", fake_run)
    monkeypatch.setattr(importer.time, "sleep", lambda seconds: None)

    importer._batch_write_with_retry({"table": []}, "eu-central-1")

    assert len(calls) == 2
