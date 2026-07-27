# Command Specification

Existing commands must remain compatible unless a change is explicitly documented.

## Existing/Core

- `/help` or `/start`: show usage.
- `/whoami`: show user id, chat id, and chat type.
- `/settings`: show current or selected chat settings.
- `/summarize [N|auto]`: summarize recent messages.
- `/chat <question>`: general assistant without history retrieval.
- `/ask <question>`: answer from bounded current-chat history evidence.
- `/remember [N|auto]`: admin-only compact memory snapshot generation.
- `/lore`: show established lore using bounded raw history and memories.
- `/insidejoke <term>`: explain a known running joke.
- `/bestof [today|week|month|year|all]`: notable or funny moments; defaults to month.
- `/quotes [user]`: evidence-backed memorable quotes for the group or a person.
- `/recap [today|week|month|year|all]`: period digest; defaults to month.
- `/usage [today|month|all]`: show usage totals.
- `/setstyle <text>`: admin-only summary style change.
- `/setfilter off|clean|strict`: admin-only filtering-mode change.
- `/setlang <code|auto>`: admin-only response-language change.
- `/models`: list supported providers and starter models.
- `/setprovider gemini|groq`: admin-only provider selection.
- `/setmodel <model|provider:model>`: admin-only model selection.
- `/chats`: owner DM command to list known chats.
- `/usechat <chat_id>`: owner DM command to select target chat.

## Menu Behavior

- `/menu`, `/help`, and `/start` install a one-row persistent `☰ Menu` launcher
  below the Telegram text field.
- The launcher opens compact inline submenus containing the complete public
  action set.
- Previously installed button labels continue to route to the same handlers as
  slash commands.
- `/ask`, `/chat`, and `/insidejoke` collect their required free-text
  argument from the user's next message when started without one.
- AWS webhook and legacy local polling modes share the menu layout and callback
  behavior.

## Command Design Rules

- Commands should be thin routing functions.
- AI replies must use the universal Telegram-safe output pipeline.
- History-aware commands must retrieve bounded context first.
- General `/chat` must not retrieve history unless explicitly requested.
- Admin/owner rules must be preserved.
