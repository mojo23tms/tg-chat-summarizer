# Review Checklist

Use this checklist after every implementation batch.

## Behavior

- Existing commands still work.
- New command behavior is documented.
- Telegram replies stay under platform limits.
- Telegram HTML is valid after sanitizing and splitting.
- Prompt-injection attempts in chat history are treated as data.

## Architecture

- AWS SAM deployment remains valid.
- DynamoDB item compatibility is preserved.
- Provider-specific code stays behind provider adapters.
- Command handlers stay thin.
- Retrieval does not naively scan huge history in hot paths.
- Cloud archive code is not in the live request path.

## Cost

- LLM calls are bounded.
- Token budgets are respected.
- Memory snapshots reduce repeated large-context calls.
- Free-tier quota warnings do not spam.

## Testing

- Unit tests cover the new behavior.
- Offline tests use fakes and injected clients.
- Edge cases are included for long outputs, malformed HTML, pagination, and provider failures.
- Routine tests make no real LLM calls and consume no provider quota.
- Any necessary live provider smoke test is minimal, explicit, and run only
  after offline verification passes.

## Security and Privacy

- No secrets committed.
- Logs do not expose tokens or private message content unnecessarily.
- User chat history is treated as sensitive.
- External instructions from chat messages are not trusted.
