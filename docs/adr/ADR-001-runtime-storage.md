# ADR-001: Runtime Storage Uses DynamoDB

## Status

Accepted.

## Context

The production bot runs on AWS Lambda and needs low-maintenance storage for Telegram messages, settings, usage records, owner state, and future memory snapshots.

## Decision

Use DynamoDB as the runtime datastore.

## Consequences

Benefits:

- serverless and low maintenance;
- good fit for Lambda;
- cheap at small and moderate scale;
- supports TTL for old message retention;
- already integrated in the current architecture.

Tradeoffs:

- query patterns must be designed carefully;
- ad hoc full-text search is limited;
- pagination must be handled explicitly.

## Notes

Google Drive and NordLocker are archive/backup options, not runtime storage.
