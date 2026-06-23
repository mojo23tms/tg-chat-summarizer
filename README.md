# Telegram Summarizer Bot

Logs chat messages and summarizes the last N on `/summarize`, mentioning the caller.
Free to run: Telegram Bot API + Gemini free tier + Fly.io free allowance.

## Setup
1. Create a bot with @BotFather; copy the token. Run `/setprivacy` → **Disable**
   (or add the bot as a group admin) so it can log group messages.
2. Get a free Gemini API key at https://aistudio.google.com/apikey.
3. Local run:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   export TELEGRAM_TOKEN=... GEMINI_API_KEY=...
   python main.py
   ```
4. Deploy to Fly.io:
   ```bash
   fly launch --no-deploy        # accept generated app name / region
   fly volumes create bot_data --size 1
   fly secrets set TELEGRAM_TOKEN=... GEMINI_API_KEY=...
   fly deploy
   ```

## Commands
- `/summarize [N]` — summarize last N messages (default 30, max 200).
- `/setstyle <text>` · `/setfilter off|clean|strict` · `/setlang <code|auto>` — admins only.
- `/settings` — show current config. `/help` — usage.
