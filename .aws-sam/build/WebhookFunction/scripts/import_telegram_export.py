#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telegram_summarizer import config

try:
    from telegram_summarizer.dynamodb_storage import DynamoDBStorage
except ModuleNotFoundError as exc:
    if exc.name != "boto3":
        raise
    raise SystemExit(
        "boto3 is required for DynamoDB imports. Install dependencies with:\n"
        ".venv/bin/python -m pip install -r requirements.txt"
    ) from exc


def _text_value(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text", "")))
        return "".join(parts).strip()
    return ""


def _timestamp(message):
    value = message.get("date_unixtime")
    if value:
        return int(value)
    value = message.get("date")
    if not value:
        return 0
    return int(datetime.fromisoformat(value).timestamp())


def _numeric_user_id(value):
    if isinstance(value, int):
        return value
    if not value:
        return 0
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else 0


def normalize_message(message):
    if message.get("type") != "message":
        return None
    text = _text_value(message.get("text"))
    if not text:
        return None
    return {
        "msg_id": int(message.get("id", 0)),
        "user_id": _numeric_user_id(message.get("from_id")),
        "user_name": message.get("from") or "unknown",
        "text": text,
        "ts": _timestamp(message),
    }


def load_importable_messages(path):
    with Path(path).open(encoding="utf-8") as fh:
        data = json.load(fh)
    return [
        normalized
        for normalized in (normalize_message(message) for message in data.get("messages", []))
        if normalized is not None
    ]


def select_messages(messages, limit, skip_latest=0):
    if skip_latest < 0:
        raise ValueError("--skip-latest must be >= 0")
    if limit < 0:
        raise ValueError("--limit must be >= 0")
    available = messages[:-skip_latest] if skip_latest else messages
    return available[-limit:] if limit > 0 else available


def import_messages(messages, chat_id, storage, expires_at=None, progress_every=500):
    for index, message in enumerate(messages, start=1):
        storage.log_message(
            chat_id,
            message["msg_id"],
            message["user_id"],
            message["user_name"],
            message["text"],
            message["ts"],
            expires_at=expires_at,
        )
        if progress_every and index % progress_every == 0:
            print(f"imported {index} messages", file=sys.stderr)


def _chat_pk(chat_id):
    return f"CHAT#{chat_id}"


def _message_sk(ts, msg_id):
    return f"MSG#{int(ts):020d}#{int(msg_id):020d}"


def dynamodb_item(chat_id, message, expires_at):
    return {
        "pk": {"S": _chat_pk(chat_id)},
        "sk": {"S": _message_sk(message["ts"], message["msg_id"])},
        "msg_id": {"N": str(int(message["msg_id"]))},
        "user_id": {"N": str(int(message["user_id"]))},
        "user_name": {"S": message["user_name"]},
        "text": {"S": message["text"]},
        "ts": {"N": str(int(message["ts"]))},
        "expires_at": {"N": str(int(expires_at))},
    }


def _chunks(items, size):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def import_messages_with_aws_cli(
    messages, chat_id, table_name, region, expires_at, progress_every=500
):
    imported = 0
    for batch in _chunks(messages, 25):
        request = {
            table_name: [
                {"PutRequest": {"Item": dynamodb_item(chat_id, message, expires_at)}}
                for message in batch
            ]
        }
        result = subprocess.run(
            [
                "aws",
                "dynamodb",
                "batch-write-item",
                "--request-items",
                json.dumps(request),
                "--region",
                region,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise SystemExit(f"aws dynamodb batch-write-item failed:\n{detail}")
        response = json.loads(result.stdout or "{}")
        unprocessed = response.get("UnprocessedItems") or {}
        if unprocessed:
            raise SystemExit(
                "DynamoDB returned unprocessed items. Retry the import with a lower limit."
            )
        imported += len(batch)
        if progress_every and imported % progress_every == 0:
            print(f"imported {imported} messages", file=sys.stderr)


def default_region():
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "eu-central-1"


def build_storage(table_name, ttl_days, region):
    import boto3

    return DynamoDBStorage(
        table_name=table_name,
        dynamodb_resource=boto3.resource("dynamodb", region_name=region),
        ttl_days=ttl_days,
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Import Telegram Desktop JSON export messages into DynamoDB."
    )
    parser.add_argument("--file", required=True, help="Path to Telegram result.json")
    parser.add_argument(
        "--chat-id",
        required=True,
        type=int,
        help="Telegram chat id used by the bot, for example -1001234567890.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Import only the latest N importable text messages. Default: 5000.",
    )
    parser.add_argument(
        "--skip-latest",
        type=int,
        default=0,
        help="Skip the latest N importable messages before applying --limit.",
    )
    parser.add_argument(
        "--table-name",
        default=config.DDB_TABLE_NAME,
        help="DynamoDB table name. Defaults to DDB_TABLE_NAME.",
    )
    parser.add_argument(
        "--ttl-days",
        type=int,
        default=config.MESSAGE_TTL_DAYS,
        help="Message retention in days. Default: MESSAGE_TTL_DAYS.",
    )
    parser.add_argument(
        "--region",
        default=default_region(),
        help="AWS region. Defaults to AWS_REGION, AWS_DEFAULT_REGION, then eu-central-1.",
    )
    parser.add_argument(
        "--writer",
        choices=("aws-cli", "boto3"),
        default="aws-cli",
        help="DynamoDB writer. Default: aws-cli, which reuses AWS CLI login credentials.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report counts without writing to DynamoDB.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required for real DynamoDB writes.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    messages = load_importable_messages(args.file)
    try:
        selected = select_messages(messages, args.limit, args.skip_latest)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print(f"importable text messages: {len(messages)}")
    print(f"skipped latest messages: {args.skip_latest}")
    print(f"selected for import: {len(selected)}")
    if selected:
        print(f"oldest selected ts: {selected[0]['ts']}")
        print(f"newest selected ts: {selected[-1]['ts']}")

    if args.dry_run:
        return
    if not args.yes:
        raise SystemExit("Refusing to write without --yes. Run --dry-run first.")
    if not args.table_name:
        raise SystemExit("DDB_TABLE_NAME or --table-name is required.")

    expires_at = int(time.time()) + args.ttl_days * 86400
    if args.writer == "aws-cli":
        import_messages_with_aws_cli(
            selected,
            args.chat_id,
            args.table_name,
            args.region,
            expires_at,
        )
    else:
        storage = build_storage(args.table_name, args.ttl_days, args.region)
        import_messages(selected, args.chat_id, storage, expires_at=expires_at)


if __name__ == "__main__":
    main()
