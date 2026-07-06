# Command Specification

Existing commands must remain compatible unless a change is explicitly documented.

## Existing/Core

- `/help` or `/start`: show usage.
- `/whoami`: show user id, chat id, and chat type.
- `/settings`: show current or selected chat settings.
- `/summarize [N|auto]`: summarize recent messages.
- `/usage [today|month]`: show usage totals.
- `/setstyle <text>`: set summary style.
- `/setfilter off|clean|strict`: set filtering mode.
- `/setlang <code|auto>`: set response language.
- `/chats`: owner DM command to list known chats.
- `/usechat <chat_id>`: owner DM command to select target chat.

## Planned

- `/chat <question>`: general assistant mode, no history retrieval by default.
- `/ask <question>`: answer from chat history and memory.
- `/models`: list supported providers/models.
- `/setprovider <provider>`: set provider for chat.
- `/setmodel <model or provider:model>`: set model for chat.
- `/lore`: show remembered lore.
- `/insidejoke <term>`: explain known running joke.
- `/bestof [period]`: notable or funny moments.
- `/quotes [user]`: memorable quotes.
- `/recap [period]`: digest for a period.

## Command Design Rules

- Commands should be thin routing functions.
- AI replies must use the universal Telegram-safe output pipeline.
- History-aware commands must retrieve bounded context first.
- General `/chat` must not retrieve history unless explicitly requested.
- Admin/owner rules must be preserved.
