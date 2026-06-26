#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telegram_summarizer.telegram_api import set_webhook


def main():
    parser = argparse.ArgumentParser(description="Register the Telegram webhook URL.")
    parser.add_argument("webhook_url", help="Deployed API Gateway URL ending in /telegram")
    args = parser.parse_args()

    token = os.environ.get("TELEGRAM_TOKEN")
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if not token or not secret:
        raise SystemExit("TELEGRAM_TOKEN and TELEGRAM_WEBHOOK_SECRET are required.")

    result = set_webhook(token, args.webhook_url, secret)
    if not result.get("ok"):
        raise SystemExit(f"setWebhook failed: {result}")
    print("Webhook registered.")


if __name__ == "__main__":
    sys.exit(main())
