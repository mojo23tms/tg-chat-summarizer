# Personal Cloud Archive

Personal cloud storage is useful for archive and backup, not live bot runtime.

## Google Drive

Good for:

- weekly or monthly Markdown digests;
- memory snapshot JSON exports;
- quote archives;
- generated reports;
- manual browsing and search;
- disaster recovery exports.

Avoid using Google Drive for live `/ask` retrieval because it adds latency, credentials complexity, and reliability risk.

## NordLocker

Good for:

- encrypted backups;
- manual disaster recovery archives;
- sensitive raw exports if needed.

If API integration is impractical, prefer a documented manual/export workflow instead of forcing it into the app.

## Architecture Rule

Cloud archive providers must not be in the live Telegram request path.

A clean future abstraction could be:

```python
class ArchiveStorage:
    def write_digest(...): ...
    def write_memory_export(...): ...
    def write_backup_manifest(...): ...
```

Runtime still uses AWS and DynamoDB.
