### Task 9: Deployment files and README

**Files:**
- Create: `Dockerfile`
- Create: `fly.toml`
- Create: `README.md`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: the full app (Tasks 1–8).
- Produces: a deployable image and documented setup. No automated tests; verified by deploy.

- [ ] **Step 1: Create `.dockerignore`**

```
.venv/
__pycache__/
data/*.db
.git/
tests/
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV DB_PATH=/data/bot.db
CMD ["python", "main.py"]
```

- [ ] **Step 3: Create `fly.toml`** (replace `app` name on first deploy)

```toml
app = "telegram-summarizer-bot"
primary_region = "fra"

[build]

[mounts]
  source = "bot_data"
  destination = "/data"

[[vm]]
  size = "shared-cpu-1x"
  memory = "256mb"
```

- [ ] **Step 4: Create `README.md`**

```markdown
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
```

- [ ] **Step 5: Verify the image builds**

Run: `docker build -t summarizer-bot .`
Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile fly.toml README.md .dockerignore
git commit -m "chore: docker + fly deployment and README"
```

---

## Manual Verification (end-to-end)

After Task 8, run locally against a real test bot and group:

1. **Logging + summarize**: `export TELEGRAM_TOKEN=... GEMINI_API_KEY=...; python main.py`.
   Send several messages in the test group, then `/summarize 10`. Confirm a summary
   posts and it **mentions you** (tappable name).
2. **No-history case**: in a fresh chat, `/summarize` → confirm the "no logged messages"
   reply.
3. **Settings + permissions**: as admin `/setstyle formal paragraphs` and
   `/setfilter strict`; re-run `/summarize` and confirm the output style/cleanliness
   changes. As a non-admin member, attempt `/setfilter off` → confirm denial.
4. **Profanity safety net**: post messages containing wordlist terms, `/setfilter clean`,
   confirm masked output even if the model echoes them.
5. **Retention**: temporarily lower `DISK_HEADROOM` (or point `disk_free_ratio` at a small
   tmpfs), flood messages, and confirm oldest rows are evicted while free space holds.
6. **Deploy**: `fly deploy`, restart the machine (`fly machine restart`), confirm the bot
   reconnects and resumes logging.
