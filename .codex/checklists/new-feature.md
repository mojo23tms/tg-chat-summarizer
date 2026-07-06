# New Feature Checklist

Before finishing a feature batch, verify:

- [ ] Existing behavior still works.
- [ ] New behavior has focused tests.
- [ ] Telegram output limit is handled.
- [ ] Telegram HTML remains valid.
- [ ] LLM calls are bounded by token/context limits.
- [ ] Cost impact is understood.
- [ ] DynamoDB compatibility is preserved.
- [ ] Provider-specific logic stays behind adapters.
- [ ] Docs are updated.
- [ ] No secrets are committed.
