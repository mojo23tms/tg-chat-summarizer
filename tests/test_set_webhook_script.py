import subprocess

from scripts import set_webhook as script


def test_load_secret_with_aws_cli_uses_region(monkeypatch):
    calls = []

    def fake_run(command, check, capture_output, text):
        calls.append(
            {
                "command": command,
                "check": check,
                "capture_output": capture_output,
                "text": text,
            }
        )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"TELEGRAM_TOKEN":"token","TELEGRAM_WEBHOOK_SECRET":"secret"}',
        )

    monkeypatch.setattr(script.subprocess, "run", fake_run)

    assert script._load_secret_with_aws_cli(
        "telegram-summarizer/prod", "eu-central-1"
    ) == {
        "TELEGRAM_TOKEN": "token",
        "TELEGRAM_WEBHOOK_SECRET": "secret",
    }
    assert calls == [
        {
            "command": [
                "aws",
                "secretsmanager",
                "get-secret-value",
                "--secret-id",
                "telegram-summarizer/prod",
                "--query",
                "SecretString",
                "--output",
                "text",
                "--region",
                "eu-central-1",
            ],
            "check": True,
            "capture_output": True,
            "text": True,
        }
    ]


def test_load_secret_returns_empty_without_secret_id():
    assert script._load_secret("", "aws-cli", "eu-central-1") == {}
