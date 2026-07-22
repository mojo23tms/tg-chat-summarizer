# Retrieval Design

Retrieval should start simple, cheap, and reliable.

## Current Foundation

`telegram_summarizer.retrieval.ChatHistoryRetriever` is the reusable boundary
between future history-aware commands and message storage. Callers provide a
`RetrievalRequest` with:

- optional keyword text;
- optional user id or partial display name;
- optional Unix timestamp bounds;
- a result limit;
- a separate scan limit.

The retriever requests newest-first, chat-scoped DynamoDB pages through
`DynamoDBStorage.message_page`. It filters and ranks matches without exposing
DynamoDB details to command handlers, then returns selected evidence in
chronological order.

`RetrievalResult` reports both `scanned_count` and `truncated`. `/ask` uses those
fields to tell the model when a bounded search did not cover all history.

## `/ask` Integration

`telegram_summarizer.history_qa.ask_history` is shared by the AWS worker and
legacy SQLite polling mode. It:

- removes common question filler before keyword retrieval;
- falls back to recent context when no useful keyword remains;
- searches only the current `chat_id`;
- caps returned evidence and scanned messages independently;
- trims selected evidence to the configured LLM input-token budget;
- retrieves up to five relevant snapshots from a bounded 500-memory scan;
- budgets compact memories together with raw messages;
- makes no provider call when both evidence sources are absent;
- passes truncation context to the evidence-grounded ask prompt.

The prompt requires answers to stay within retrieved evidence, include
names/timestamps when useful, and admit ambiguity or weak support.

## Initial Retrieval Modes

- recent context: implemented;
- keyword search: implemented with case-insensitive term matching;
- user filtering: implemented for exact numeric ids and partial display names;
- date or time range filtering: implemented with DynamoDB sort-key bounds;
- memory snapshot lookup: implemented with bounded keyword ranking.

## Cost Boundaries

- Every read is scoped to one `chat_id` partition.
- `limit` controls returned evidence.
- `scan_limit` independently caps evaluated messages.
- Memory lookup is independently capped at five results from 500
  snapshots.
- DynamoDB pagination is followed only until the scan budget is exhausted.
- Keyword matching currently favors simplicity over a secondary index. A query
  can therefore return `truncated=True` when relevant older evidence may exist.
- No retrieval path reads S3, Google Drive, or NordLocker.

## Design Goal

Command handlers should not know whether context came from keyword search, memory snapshots, or future semantic search. Put retrieval behind a reusable component.

## Avoid

- scanning huge history in hot paths without limits;
- sending raw whole-history context to an LLM;
- making Google Drive or NordLocker runtime dependencies;
- adding embeddings before memory snapshots prove useful.

Historical memory lookup paginates across the bounded snapshot scan and ranks
deterministic lexical metadata. Empty lore queries sample snapshots across the
available source timeline instead of selecting only the newest slice. After
selecting a small memory set, retrieval fetches at most three raw supporting
messages from each selected source range, with a 50-message scan cap per range.
The final answer still uses one bounded LLM generation call.

## Friend-Chat Queries To Support

- Who started this joke?
- Why do we call someone a nickname?
- When did a saga begin?
- What were the funniest moments last month?
- Give best quotes from a person.
- Summarize the history of a recurring argument.
