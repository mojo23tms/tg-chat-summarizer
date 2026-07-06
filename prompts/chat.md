# Chat Prompt Notes

`/chat` is general assistant mode.

Rules:

- do not retrieve chat history by default;
- answer the explicit user question;
- keep replies compact for Telegram;
- use Telegram HTML only;
- track usage;
- follow selected provider/model settings.

If the user explicitly asks to use chat history, route to the retrieval-aware behavior instead of silently mixing modes.
