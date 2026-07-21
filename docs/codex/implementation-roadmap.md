# Codex Implementation Roadmap

This roadmap should be implemented batch by batch. Do not combine unrelated batches into one large refactor.

## Testing And LLM Quota Discipline

Testing is a roadmap-wide requirement, not a separate final batch.

- Expand automated coverage in every batch, including touched behavior,
  adjacent regression risks, failure paths, and compatibility boundaries.
- Cover as much of the codebase as practical with deterministic offline tests.
- Keep routine and CI test suites free of real Telegram, AWS, Gemini, Groq, or
  other provider network calls.
- Test LLM prompts, routing, usage parsing, timeouts, blocked responses, quota
  behavior, and provider failures with injected backends and fake responses.
- Never require real provider credentials for automated tests.
- Use a real LLM smoke test only when provider integration cannot be validated
  offline, after all offline tests pass. Keep it to the smallest useful prompt
  and record that quota-consuming verification separately.
- Prefer meaningful behavior and failure-path coverage over low-value tests
  written only to increase a coverage percentage.

## Batch 0: Architecture Review

Inspect current AWS webhook, SQS worker, DynamoDB storage, summarization flow, LLM code, Telegram HTML handling, tests, cost risks, and refactor risks. Produce a short implementation plan before coding.

## Batch 1: Telegram-Safe Output Pipeline

Create one response pipeline used by AI replies and future long responses.

Requirements:

- never exceed Telegram message limits;
- split long responses safely;
- preserve or repair Telegram-compatible HTML;
- allow only Telegram-safe tags;
- prevent invalid HTML after splitting;
- add tests for long output, malformed HTML, and split messages.

This must happen before expanding summary scope.

## Batch 2: Configurable 5000-Message Summary Scope

Increase input scope, not output size.

Requirements:

- configurable `SUMMARY_MAX_MESSAGES`;
- default 5000;
- clamp manual `/summarize N` to `1..SUMMARY_MAX_MESSAGES`;
- `/summarize auto` may consider up to this limit but must respect token budgets;
- never send all messages blindly;
- add tests for config, clamping, and auto selection.

## Batch 3: Shared Safety Instruction and Prompt Hardening

Create a shared instruction block for summaries, `/ask`, `/chat`, and memory jobs.

It must state that Telegram history is data, not instructions. It must require Telegram HTML only, concise output, no Markdown, no secret exposure, and resistance to prompt injection inside messages.

Clearly delimit user messages and retrieved context.

## Batch 4: LLM Provider Adapters

Refactor LLM calls behind a provider interface.

Gemini remains default. Add Groq support. Design for OpenRouter and Cloudflare Workers AI later.

Return structured results containing text, provider, model, usage, whether usage is estimated, and finish reason when available.

Add per-chat provider/model settings and commands:

- `/models`
- `/setprovider <provider>`
- `/setmodel <model or provider:model>`

## Batch 5: Usage and Free-Tier Quota Warnings

Track usage per provider/model/day.

Warn at approximately 10 percent remaining configured quota, once per chat/provider/day. Prefer provider-reported usage when available; estimate otherwise.

## Batch 6: `/chat` General Assistant Mode

Implement `/chat <question>` for normal AI help. It must not search chat history unless the user explicitly asks for history.

Use provider selection, shared safety instruction, Telegram-safe output, and usage tracking.

## Batch 7: Retrieval Foundation

Build reusable DynamoDB retrieval for friend-chat history.

If full historical chat export already exists in S3, add an offline S3-to-DynamoDB
backfill/sync path in this batch so retrieval has the complete history available
in the runtime datastore. S3 must remain outside the live Telegram request path.

Start cheap:

- keyword search;
- user filtering;
- date/time range filtering where practical;
- recent context retrieval;
- pagination where needed.

Design so semantic search can be added later without changing command handlers.

Add tests for S3 export parsing/backfill idempotency, chat_id scoping, bounded
imports, and retrieval over imported historical messages.

## Batch 8: `/ask` Chat-History Q&A

Implement `/ask <question>`.

It should retrieve relevant messages and memory context, answer with evidence, include names/timestamps where useful, and admit weak evidence.

It must not send entire history blindly.

## Batch 9: Low-Cost Memory Snapshots

Generate compact memory objects every configured interval or on command.

Memory is friend-chat oriented:

- running jokes;
- nicknames;
- legendary incidents;
- funny quotes;
- recurring topics;
- people lore;
- unresolved stories;
- notable roasts/conflicts;
- canon events.

Store snapshots in DynamoDB and allow `/ask` to use relevant memories plus raw messages.

## Batch 10: Lore Commands

Status: implemented with bounded raw-history and memory retrieval.

Add commands only if they fit cleanly after memory snapshots.

Candidates:

- `/lore`
- `/insidejoke <term>`
- `/bestof [period]`
- `/quotes [user]`
- `/recap [period]`

Each command must use memory/retrieval and avoid huge scans.

## Batch 11: Historical Memory Backfill And Cheap Archive Retrieval

Make a full imported chat archive convenient to use without increasing live
prompt size or putting S3 in the Telegram request path.

Requirements:

- add an offline, resumable job that reads chat-scoped messages from DynamoDB
  in chronological chunks after the existing S3-to-DynamoDB import;
- checkpoint progress per chat so interrupted runs resume safely and completed
  source ranges are not charged twice;
- generate compact memory snapshots for historical ranges, preserving source
  timestamps, message ids, participants, keywords, quotes, jokes, and lore;
- make chunk size, maximum processed messages, provider, model, and output-token
  budget explicit operator settings;
- support dry-run mode with projected chunk count and token/cost estimates before
  any provider calls;
- keep runtime `/ask` and lore commands bounded: retrieve a small set of memory
  candidates, fetch only their supporting raw ranges, and send only selected
  evidence to the LLM;
- add deterministic lexical metadata/indexing first so old memories can be found
  without scanning only the newest DynamoDB slice;
- evaluate semantic retrieval only after lexical-plus-memory retrieval is
  measured; if needed, embed memory/chunk records first rather than every raw
  Telegram message;
- update new-message processing incrementally so the historical backfill is a
  one-time operation rather than a recurring full-archive job;
- preserve chat-id isolation, source traceability, idempotency, DynamoDB/SAM
  compatibility, and legacy local-mode behavior;
- provide hard per-run and per-command cost guards, provider usage logging,
  quota warnings, and clear failure/resume reporting.

Tests must remain offline and cover:

- chronological chunk boundaries with no gaps or overlaps;
- checkpoint resume and idempotent reruns;
- chat isolation and bounded maximum-message processing;
- dry-run estimates without LLM calls;
- provider failure followed by safe resume;
- retrieval of old evidence outside the newest raw-message scan window;
- token/evidence caps in the final live request;
- lexical fallback when embeddings are absent or unavailable.

Acceptance criteria:

- a roughly 50,000-message imported chat can be backfilled through an explicit
  operator command without loading the whole export or history into memory;
- live commands never read S3 and never send the full archive to an LLM;
- repeated backfills process only missing or explicitly requested ranges;
- ordinary `/ask` and lore requests require at most one bounded answer-generation
  LLM call after retrieval;
- documentation includes setup, dry run, resume, expected cost inputs, privacy,
  and rollback instructions.

## Batch 12: Personal Cloud Archive

Evaluate and implement only useful archival integration.

Google Drive is for readable archives, digests, JSON exports, and manual browsing/search. NordLocker is for optional encrypted backup or manual export workflow. S3 may be used as an AWS-side raw history archive or disaster-recovery source, but runtime commands should consume DynamoDB copies produced by offline import/backfill jobs.

Cloud storage must never be in the live Telegram request path.

## Batch 13: Final Documentation and Review

Update docs for commands, providers, quotas, memory, cloud archive, cost control, privacy, and deployment.

Final review checklist:

- no secrets;
- tests pass;
- no giant untested modules;
- no duplicate LLM logic;
- no handler spaghetti;
- DynamoDB compatibility preserved;
- AWS deployment valid.
