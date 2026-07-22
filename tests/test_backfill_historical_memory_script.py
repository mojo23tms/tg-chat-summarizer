import pytest

from scripts import backfill_historical_memory as script


class EmptyStorage:
    def __init__(self):
        self.cleared = False

    def get_settings(self, chat_id):
        return {
            "style": "concise",
            "filter_level": "clean",
            "language": "auto",
            "provider": "gemini",
            "model": "gemini-test",
        }

    def get_backfill_checkpoint(self, chat_id, job_name):
        return None

    def chronological_message_page(self, chat_id, **kwargs):
        return [], None

    def clear_backfill_checkpoint(self, chat_id, job_name):
        self.cleared = True


def test_cli_requires_confirmation_before_provider_calls():
    with pytest.raises(SystemExit, match="without --yes"):
        script.main(
            ["--chat-id", "1", "--table-name", "table"],
            storage_factory=lambda *_args: EmptyStorage(),
        )


def test_cli_dry_run_uses_no_provider_or_checkpoint_writes(capsys):
    report = script.main(
        [
            "--chat-id",
            "1",
            "--table-name",
            "table",
            "--dry-run",
            "--chunk-size",
            "100",
            "--max-messages",
            "500",
        ],
        storage_factory=lambda *_args: EmptyStorage(),
    )

    assert report["status"] == "complete"
    assert report["processed_messages"] == 0
    assert '"dry_run": true' in capsys.readouterr().out


def test_cli_reset_is_explicit_and_exits_without_backfill(capsys):
    storage = EmptyStorage()

    report = script.main(
        [
            "--chat-id",
            "1",
            "--table-name",
            "table",
            "--reset-checkpoint",
            "--yes",
        ],
        storage_factory=lambda *_args: storage,
    )

    assert storage.cleared is True
    assert report == {"status": "checkpoint_reset", "chat_id": 1}
    assert "checkpoint_reset" in capsys.readouterr().out


def test_cli_dry_run_cannot_reset_checkpoint():
    with pytest.raises(SystemExit, match="cannot be combined"):
        script.main(
            [
                "--chat-id",
                "1",
                "--table-name",
                "table",
                "--reset-checkpoint",
                "--dry-run",
                "--yes",
            ],
            storage_factory=lambda *_args: EmptyStorage(),
        )
