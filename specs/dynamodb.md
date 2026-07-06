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

## Planned Item Families

Memory snapshots:

```text
pk = CHAT#{chat_id}
sk = MEMORY#{timestamp_or_sequence}
```

Quota warnings:

```text
pk = CHAT#{chat_id}
sk = QUOTA_WARN#{provider}#{model}#{date}
```

Provider settings may live in the existing `SETTINGS` item if compatible.

## Rules

- Preserve compatibility with existing items.
- Handle DynamoDB pagination when reading potentially large sets.
- Do not require table migrations for small settings additions if an item attribute is enough.
- Use TTL for data that should expire.
