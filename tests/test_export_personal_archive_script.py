import pytest

from scripts import export_personal_archive as script


class EmptyStorage:
    def chronological_message_page(self, chat_id, **kwargs):
        return [], None

    def memory_page(self, chat_id, **kwargs):
        return [], None


def test_cli_requires_confirmation_before_writing(tmp_path):
    with pytest.raises(SystemExit, match="without --yes"):
        script.main(
            [
                "--chat-id",
                "1",
                "--table-name",
                "table",
                "--output-dir",
                str(tmp_path / "archive"),
            ],
            storage_factory=lambda *_args: EmptyStorage(),
        )


def test_cli_dry_run_creates_no_files(tmp_path, capsys):
    output = tmp_path / "archive"

    report = script.main(
        [
            "--chat-id",
            "1",
            "--table-name",
            "table",
            "--output-dir",
            str(output),
            "--dry-run",
        ],
        storage_factory=lambda *_args: EmptyStorage(),
    )

    assert report["status"] == "dry_run"
    assert not output.exists()
    assert '"dry_run": true' in capsys.readouterr().out


def test_cli_creates_archive_after_confirmation(tmp_path):
    output = tmp_path / "archive"

    report = script.main(
        [
            "--chat-id",
            "1",
            "--table-name",
            "table",
            "--output-dir",
            str(output),
            "--yes",
        ],
        storage_factory=lambda *_args: EmptyStorage(),
    )

    assert report["status"] == "exported"
    assert (output / "manifest.json").exists()
