# Memory System

The memory system is the low-cost alternative to repeatedly sending huge message ranges to an LLM.

## Goal

Turn raw chat history into compact, reusable memory objects that preserve friend-group culture.

## Memory Snapshot Contents

A snapshot may contain:

- running jokes;
- nicknames and aliases;
- canon events;
- funny quotes;
- recurring topics;
- people lore;
- unresolved stories;
- notable roasts or conflicts;
- questions the group keeps returning to;
- terms that need explanation later.

## Storage

Runtime memory snapshots should live in DynamoDB. Use explicit key patterns and keep compatibility with existing message/settings/usage records.

Cloud archive copies may later be exported to Google Drive or NordLocker, but those copies must not be needed for live bot replies.

## Cost Strategy

Generate snapshots periodically or on command, then use relevant snapshots plus selected raw messages for `/ask`. This reduces repeated large-context LLM calls.

## Future Extension

Embeddings may be added later for memory snapshots first. Do not embed every raw Telegram message unless there is a clear cost and value justification.
