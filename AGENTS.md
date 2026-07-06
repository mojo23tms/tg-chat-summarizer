# AGENTS

This file is the universal entry point for AI coding agents working on this repository.

Read in this order:

1. `CODEX.md`
2. `docs/codex/implementation-roadmap.md`
3. The current task-specific files and tests

Project identity:

- This is a Telegram bot for a private friends' group chat.
- It is not a corporate productivity assistant.
- The product value is summaries, chat Q&A, long-term memory, lore, jokes, quotes, and keeping the group culture alive.

Working rules:

- Work in one implementation batch at a time.
- Preserve the existing AWS SAM, Lambda, SQS, DynamoDB, Gemini, and legacy local-mode behavior unless a change is explicitly required.
- Before editing code, inspect the current implementation and state the smallest safe plan.
- Every behavior change needs focused tests.
- Update docs when commands, architecture, storage, prompts, providers, deployment, or cost behavior changes.
- Stop after the current batch is complete and summarize what changed.

Never:

- Commit secrets.
- Blindly send thousands of raw messages to an LLM.
- Put Google Drive, NordLocker, or any personal cloud storage in the live Telegram request path.
- Scatter provider-specific code through command handlers.
- Create giant unreviewable refactors.
- Replace existing working architecture without explaining the tradeoff.
