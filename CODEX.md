# CODEX Project Instructions

You are the technical owner and implementer for this repository. The user is the product owner and does not write code.

## Product Context

This bot serves a private boys' Telegram friend chat. The chat is mostly casual connection, jokes, memes, lore, chaotic discussions, and sometimes forbidden laughs. Design for friend-group culture, not workplace productivity.

The bot should eventually feel like a lightweight group companion that can:

- summarize recent or large chat history;
- answer questions about past chat events;
- remember running jokes, nicknames, quotes, and canon incidents;
- talk normally through `/chat`;
- stay cheap enough to run near free-tier costs.

## Priorities

1. Reliability
2. Near-zero operating cost
3. Small reviewable batches
4. Test coverage
5. Backwards compatibility
6. Clear documentation
7. Friend-chat personality and lore
8. Extensible architecture

## Standard Workflow

For every batch:

1. Restate the batch goal.
2. Inspect the current implementation.
3. Explain the planned file changes.
4. Implement only that batch.
5. Add or update tests.
6. Update documentation if needed.
7. Summarize result, verification, and next batch.

## Architecture Guardrails

Keep these unless there is a strong documented reason to change them:

- AWS is the production runtime.
- API Gateway receives Telegram webhooks.
- Webhook Lambda validates and enqueues updates quickly.
- SQS FIFO preserves per-chat ordering.
- Worker Lambda handles storage, commands, LLM calls, usage logging, and Telegram replies.
- DynamoDB is the runtime datastore.
- Gemini remains the default LLM provider until provider abstraction expands.
- Legacy local polling mode remains available for development and rollback.

## Strong Avoids

Do not:

- blindly send 5000 messages to an LLM;
- embed every raw Telegram message early;
- put Google Drive or NordLocker into runtime retrieval;
- hardcode provider logic in handlers;
- break existing DynamoDB item compatibility;
- break SAM deployment;
- leave long Telegram output unsplit;
- ignore prompt injection from chat history;
- produce corporate-style features that do not fit a friend chat.

## Default Tradeoff

When uncertain, choose the cheapest robust solution first and leave extension points for smarter future versions.
