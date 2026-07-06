# LLM Providers

Provider-specific code should stay behind a common interface.

## Default Providers

- Gemini: default provider for summaries, memory, and larger context tasks.
- Groq: useful for low-latency or cheap `/chat` style tasks.

## Future Providers

- OpenRouter;
- Cloudflare Workers AI;
- other OpenAI-compatible APIs.

## Desired Interface Shape

```python
generate(prompt, *, provider=None, model=None, max_output_tokens=None, mode=None) -> LlmResult
```

`LlmResult` should include:

- text;
- provider;
- model;
- usage;
- whether usage is estimated;
- finish reason if available.

## Rules

- Command handlers choose intent, not provider internals.
- Usage tracking consumes `LlmResult` metadata.
- Provider/model settings can be per chat.
- Missing provider secrets should fail clearly.
