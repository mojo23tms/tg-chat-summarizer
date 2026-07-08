#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telegram_summarizer.telegram_api import set_webhook


def _load_secret_with_aws_cli(secret_id, region):
    command = [
        "aws",
        "secretsmanager",
        "get-secret-value",
        "--secret-id",
        secret_id,
        "--query",
        "SecretString",
        "--output",
        "text",
    ]
    if region:
        command.extend(["--region", region])
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout or "{}")


def _load_secret_with_boto3(secret_id):
    import boto3

    response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
    return json.loads(response.get("SecretString") or "{}")


def _load_secret(secret_id, loader, region):
    if not secret_id:
        return {}
    if loader == "boto3":
        return _load_secret_with_boto3(secret_id)
    return _load_secret_with_aws_cli(secret_id, region)


def main():
    parser = argparse.ArgumentParser(description="Register the Telegram webhook URL.")
    parser.add_argument("webhook_url", help="Deployed API Gateway URL ending in /telegram")
    parser.add_argument(
        "--secret-id",
        default=os.environ.get("APP_SECRET_ID", ""),
        help="AWS Secrets Manager secret id. Defaults to APP_SECRET_ID.",
    )
    parser.add_argument(
        "--secret-loader",
        choices=("aws-cli", "boto3"),
        default="aws-cli",
        help="How to read --secret-id locally. Defaults to aws-cli.",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "")),
        help="AWS region for aws-cli secret reads.",
    )
    args = parser.parse_args()

    app_secret = _load_secret(args.secret_id, args.secret_loader, args.region)
    token = os.environ.get("TELEGRAM_TOKEN") or app_secret.get("TELEGRAM_TOKEN")
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET") or app_secret.get(
        "TELEGRAM_WEBHOOK_SECRET"
    )
    if not token or not secret:
        raise SystemExit(
            "TELEGRAM_TOKEN and TELEGRAM_WEBHOOK_SECRET are required via env "
            "or --secret-id/APP_SECRET_ID."
        )

    result = set_webhook(token, args.webhook_url, secret)
    if not result.get("ok"):
        raise SystemExit(f"setWebhook failed: {result}")
    print("Webhook registered.")


if __name__ == "__main__":
    sys.exit(main())
