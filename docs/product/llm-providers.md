# LLM Providers

Provider-specific code stays behind the common interface in
`telegram_summarizer.llm`. Command handlers select intent and per-chat settings;
they do not import provider SDKs or construct provider requests.

## Supported Providers

- Gemini is the default provider. The default model is
  `gemini-2.5-flash-lite`.
- Groq uses its OpenAI-compatible chat-completions endpoint. The default model
  is `llama-3.3-70b-versatile`.

Provider credentials come from environment variables in local mode and from
the configured Secrets Manager JSON object in AWS:

```text
GEMINI_API_KEY
GROQ_API_KEY
```

## Interface

```python
generate(prompt, settings, max_output_tokens=None) -> LLMResult
```

`LLMResult` contains:

- text;
- provider;
- model;
- normalized input, output, and total-token usage;
- whether usage is estimated;
- finish reason when the provider exposes one.

Summaries, `/chat`, `/ask`, lore, and memory jobs call provider-neutral wrapper
functions in the same module. Tests inject fake backends or fake provider
responses; routine tests never call a real provider.

## Chat Settings And Commands

Provider and model are stored per chat in the existing settings record.

- `/models` lists supported providers and starter models.
- `/setprovider <provider>` selects a provider and resets the model to that
  provider's default.
- `/setmodel <model|provider:model>` selects a model and can change provider at
  the same time.

Settings changes are admin-only in groups. Configured bot owners can change a
selected group's settings from a private chat.

## Usage And Quotas

Provider-reported usage is preferred. When it is unavailable, the bot estimates
tokens and marks the usage record as estimated. Optional daily quotas are
configured with `GEMINI_DAILY_TOKEN_QUOTA` and `GROQ_DAILY_TOKEN_QUOTA`; zero
disables warnings. Each chat receives at most one low-quota warning per
provider/day.

## Future Providers

OpenRouter, Cloudflare Workers AI, or another OpenAI-compatible service can be
added inside the LLM module without changing command handlers or stored result
shapes.

## Rules

- Command handlers choose intent, not provider internals.
- Usage tracking consumes `LLMResult` metadata.
- Provider/model settings can be per chat.
- Missing provider secrets should fail clearly.
- Provider calls must respect `LLM_REQUEST_TIMEOUT_SECONDS` and explicit output
  token budgets.
