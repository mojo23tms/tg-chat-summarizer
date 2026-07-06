# ADR-002: Prefer Memory Snapshots Before Embedding Raw Messages

## Status

Accepted.

## Context

The bot may eventually need to answer questions across long chat history. A naive approach would embed every Telegram message.

## Decision

Do not embed every raw message at this stage. First implement memory snapshots and cheap retrieval.

## Reasoning

Memory snapshots are cheaper, easier to inspect, and better aligned with friend-chat culture. They preserve lore, jokes, nicknames, and recurring stories in compact form.

## Consequences

Benefits:

- lower LLM and storage cost;
- less operational complexity;
- easier debugging;
- better long-term context quality for social/lore questions.

Tradeoffs:

- exact semantic recall may be weaker initially;
- snapshot quality matters;
- some questions still need raw message retrieval.

## Future

If semantic search is needed, embed memory snapshots first. Raw message embeddings require a separate cost/benefit decision.
