# DynamoDB Specification Notes

The table uses single-table design with `pk` and `sk` string keys.

## Existing Item Families

Messages:

```text
pk = CHAT#{chat_id}
sk = MSG#{timestamp_padded}#{message_id_padded}
```

Settings:

```text
pk = CHAT#{chat_id}
sk = SETTINGS
```

Chat index:

```text
pk = CHATS
sk = CHAT#{chat_id}
```

Owner active chat:

```text
pk = OWNER#{user_id}
sk = ACTIVE_CHAT
```

Usage:

```text
pk = CHAT#{chat_id}
sk = USAGE#{timestamp_padded}#{unique_suffix}
```

Memory snapshots:

```text
pk = CHAT#{chat_id}
sk = MEMORY#{start_timestamp_padded}#{end_timestamp_padded}
```

Attributes include `version`, `created_at`, `start_ts`, `end_ts`,
`message_count`, `summary`, and structured `items`. Rebuilding the same source
range is idempotent.

## Planned Item Families

Quota warnings:

```text
pk = CHAT#{chat_id}
sk = QUOTA_WARN#{provider}#{model}#{date}
```

Provider settings may live in the existing `SETTINGS` item if compatible.

## Rules

- Preserve compatibility with existing items.
- Handle DynamoDB pagination when reading potentially large sets.
- Scope message retrieval to one `CHAT#{chat_id}` partition and use `MSG#`
  timestamp key bounds where provided.
- Keep returned-result limits separate from scanned-message limits so keyword
  searches remain cost-bounded.
- Do not require table migrations for small settings additions if an item attribute is enough.
- Use TTL for data that should expire.
