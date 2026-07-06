# Retrieval Design

Retrieval should start simple, cheap, and reliable.

## Initial Retrieval Modes

- recent context;
- keyword search;
- user filtering;
- date or time range filtering where practical;
- memory snapshot lookup.

## Design Goal

Command handlers should not know whether context came from keyword search, memory snapshots, or future semantic search. Put retrieval behind a reusable component.

## Avoid

- scanning huge history in hot paths without limits;
- sending raw whole-history context to an LLM;
- making Google Drive or NordLocker runtime dependencies;
- adding embeddings before memory snapshots prove useful.

## Friend-Chat Queries To Support

- Who started this joke?
- Why do we call someone a nickname?
- When did a saga begin?
- What were the funniest moments last month?
- Give best quotes from a person.
- Summarize the history of a recurring argument.
