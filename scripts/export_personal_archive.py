#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telegram_summarizer import archive_export
from telegram_summarizer import config
from telegram_summarizer.dynamodb_storage import DynamoDBStorage


def default_region():
    return (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "eu-central-1"
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Export one DynamoDB chat to a local, portable archive for manual "
            "Google Drive, NordLocker, or S3 backup."
        )
    )
    parser.add_argument("--chat-id", required=True, type=int)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--archive-name")
    parser.add_argument("--table-name", default=config.DDB_TABLE_NAME)
    parser.add_argument("--region", default=default_region())
    parser.add_argument("--page-size", type=int, default=250)
    parser.add_argument(
        "--max-messages",
        type=int,
        default=0,
        help="Maximum messages to export; 0 exports the full selected range.",
    )
    parser.add_argument("--start-ts", type=int, default=0)
    parser.add_argument("--end-ts", type=int, default=99_999_999_999)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count selected records without creating files.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required before creating a local archive.",
    )
    return parser.parse_args(argv)


def build_storage(table_name, region):
    import boto3

    return DynamoDBStorage(
        table_name=table_name,
        dynamodb_resource=boto3.resource("dynamodb", region_name=region),
    )


def main(argv=None, storage_factory=None):
    args = parse_args(argv)
    if not args.table_name:
        raise SystemExit("DDB_TABLE_NAME or --table-name is required.")
    if not args.dry_run and not args.yes:
        raise SystemExit("Refusing to create archive files without --yes.")
    storage_factory = storage_factory or build_storage
    storage = storage_factory(args.table_name, args.region)
    try:
        report = archive_export.create_personal_archive(
            storage,
            args.chat_id,
            args.output_dir,
            archive_name=args.archive_name,
            page_size=args.page_size,
            max_messages=args.max_messages,
            start_ts=args.start_ts,
            end_ts=args.end_ts,
            dry_run=args.dry_run,
        )
    except (FileExistsError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


if __name__ == "__main__":
    main()
