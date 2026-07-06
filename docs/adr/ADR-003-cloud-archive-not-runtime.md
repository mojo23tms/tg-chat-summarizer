# ADR-003: Personal Cloud Storage Is Archive, Not Runtime

## Status

Accepted.

## Context

The user has significant personal cloud storage in Google Drive and NordLocker. These services may help with backups, exports, and long-term archives.

## Decision

Personal cloud storage must not be used in the live Telegram request path.

## Reasoning

Live bot replies need low latency, predictable credentials, and high reliability. AWS + DynamoDB already provides the runtime path. Cloud storage adds too much fragility for request-time operations.

## Allowed Uses

- weekly/monthly digest archive;
- memory snapshot exports;
- quote/lore archives;
- raw history backups if safe;
- disaster recovery.

## Disallowed Uses

- live `/ask` retrieval;
- message-by-message runtime database;
- vector search dependency for live commands;
- required runtime cache.
