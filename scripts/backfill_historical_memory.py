#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telegram_summarizer import config
from telegram_summarizer import historical_backfill
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
            "Build resumable historical memory snapshots from messages already "
            "imported into DynamoDB. This command never reads S3."
        )
    )
    parser.add_argument("--chat-id", required=True, type=int)
    parser.add_argument("--table-name", default=config.DDB_TABLE_NAME)
    parser.add_argument("--region", default=default_region())
    parser.add_argument("--chunk-size", type=int, default=250)
    parser.add_argument("--max-messages", type=int, default=5000)
    parser.add_argument("--start-ts", type=int, default=0)
    parser.add_argument("--end-ts", type=int, default=99_999_999_999)
    parser.add_argument("--max-input-tokens", type=int, default=12000)
    parser.add_argument("--output-tokens", type=int, default=800)
    parser.add_argument("--provider", choices=("gemini", "groq"))
    parser.add_argument("--model")
    parser.add_argument("--input-cost-per-million", type=float, default=0.0)
    parser.add_argument("--output-cost-per-million", type=float, default=0.0)
    parser.add_argument(
        "--max-estimated-cost",
        type=float,
        help="Stop before a chunk would push this run above the estimated cost cap.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Estimate remaining chunks, tokens, and cost without provider calls or writes.",
    )
    parser.add_argument(
        "--reset-checkpoint",
        action="store_true",
        help="Delete the chat's historical-memory checkpoint before starting.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required for provider calls, checkpoint writes, and reset operations.",
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
    if args.reset_checkpoint and args.dry_run:
        raise SystemExit("--reset-checkpoint cannot be combined with --dry-run.")
    if not args.dry_run and not args.yes:
        raise SystemExit("Refusing provider calls without --yes. Run --dry-run first.")
    if args.reset_checkpoint and not args.yes:
        raise SystemExit("--reset-checkpoint requires --yes.")
    storage_factory = storage_factory or build_storage
    storage = storage_factory(args.table_name, args.region)
    if args.reset_checkpoint:
        storage.clear_backfill_checkpoint(
            args.chat_id, job_name=historical_backfill.JOB_NAME
        )
        report = {"status": "checkpoint_reset", "chat_id": args.chat_id}
        print(json.dumps(report, indent=2, sort_keys=True))
        return report
    try:
        report = historical_backfill.run_backfill(
            storage,
            args.chat_id,
            chunk_size=args.chunk_size,
            max_messages=args.max_messages,
            start_ts=args.start_ts,
            end_ts=args.end_ts,
            max_input_tokens=args.max_input_tokens,
            output_tokens=args.output_tokens,
            provider=args.provider,
            model=args.model,
            input_cost_per_million=args.input_cost_per_million,
            output_cost_per_million=args.output_cost_per_million,
            max_estimated_cost=args.max_estimated_cost,
            dry_run=args.dry_run,
        )
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


if __name__ == "__main__":
    main()
