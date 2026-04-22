
# Hex – Slack → Google Tasks Bot

**Hex** is a small Python/Flask bot that:

- Listens for `@Hex tasks` mentions in Slack.
- Parses inline or bullet-form task descriptions with `@mentions`.
- Creates one **Google Task per assignee**, grouped into a **Google Tasks list per Slack channel**.
- Replies in Slack summarizing who assigned what to whom (only after Google confirms).

This document captures how the project works and how to re-create all the required configuration (Slack, Google, local dev) so Future‑You doesn't have to reverse-engineer it.

---

## 1. High‑level architecture

**Flow:**

1. In Slack, user posts:

   ```text
   @Hex tasks
   * @alice do this
   * @alice @bob do that
   ```

   or inline:

   ```text
   @Hex tasks @alice @bob do that
   ```

2. Slack sends an `app_mention` event to Hex via a public HTTPS URL (ngrok in dev).
3. Hex (Flask app) parses each bullet / inline line → one `(assignee_id, task_text)` pair per `@mention`.
4. Hex looks up human‑readable names (`users.info`) and the channel name (`conversations.info`).
5. Hex adds a 👀 reaction to acknowledge receipt, then creates one **Google Task per assignee**:
   - `title = "[Display Name] {task_text}"`
   - `notes` include the Slack permalink.
   - Tasks go into a **Google Tasks list whose title = Slack channel name** (created on demand).
6. After Google confirms each task, Hex removes the 👀 reaction and replies in the Slack thread with a per-task ✓/✗ summary.

**Important:**  
In the current version, **all tasks go to one Google account** (the one used for the OAuth setup). `@mentions` drive title/summary text, not which Google account receives the task.

---

## 2. Code structure

```text
hex-bot/
  hex_bot/
    __init__.py
    app.py               # Flask entrypoint (/slack/events, /healthz)
    config.py            # Central config (reads env vars + .env)
    slack_client.py      # Slack WebClient + signature verification
    dispatcher.py        # Routes app_mention events to subcommands
    db.py                # MongoDB persistence (users, event dedup, Fernet encryption)
    google_tasks.py      # Google Tasks client + tasklist helpers
    commands/
      __init__.py
      base.py            # Command base class + registry
      tasks.py           # "@Hex tasks" command
  tests/
    __init__.py
    conftest.py          # pytest fixtures (MongoDB hex_test database)
    test_db.py           # MongoDB CRUD and event deduplication tests
    test_parsing.py      # Bullet/inline parsing tests
    test_signature.py    # Slack signature verification tests
  scripts/
    get_refresh_token.py # One-off helper to obtain a Google refresh token
  run.sh                 # Start ngrok + Flask locally
  test.sh                # Run the pytest suite
  requirements.txt
  pytest.ini
  .env                   # Local secrets (never committed)
```

Key modules:

- **`app.py`** – `/slack/events` endpoint: URL verification, signature check, event deduplication (MongoDB TTL), dispatches `app_mention` in a background thread to avoid Slack's 3s timeout.
- **`config.py`** – reads all env vars; calls `load_dotenv()` so `.env` is loaded automatically.
- **`db.py`** – MongoDB persistence: user CRUD with Fernet-encrypted refresh tokens, event dedup via TTL collection (10 min window).
- **`slack_client.py`** – `WebClient`, `verify_slack_signature`, `get_bot_user_id`.
- **`dispatcher.py`** – finds the `@Hex <command>` line, routes to the matching command.
- **`commands/tasks.py`** – parses bullets/inline, resolves names, calls Google Tasks, posts per-task summary.
- **`google_tasks.py`** – OAuth2 refresh-token client, tasklist cache, `create_task`.

---

## 3. Environment variables and secrets

Create a `.env` file at the project root (never commit it). `config.py` loads it automatically via `python-dotenv`.

### 3.1. Slack

From your **Slack app**:

- `SLACK_SIGNING_SECRET` – **Basic Information → App Credentials → Signing Secret**.
- `SLACK_BOT_TOKEN` – **OAuth & Permissions → Bot User OAuth Token**.
- `SLACK_BOT_USER_ID` *(optional)* – value from `auth.test()["user_id"]`; auto-discovered if not set.

### 3.2. Google Tasks

From your **Google Cloud project**:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- `GOOGLE_TASKS_LIST_ID` *(optional, default `@default`)* – fallback when per-channel lookup fails.

### 3.3. MongoDB

- `MONGODB_URI` – e.g. `mongodb+srv://user:pass@cluster.mongodb.net/`
- `MONGODB_DB_NAME` *(optional, default `hex`)*

### 3.4. Encryption

- `FERNET_KEY` – symmetric key for encrypting Google refresh tokens at rest. Generate once with:

  ```bash
  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

  **Never change this once tokens are stored** — existing tokens become unreadable.

### Example `.env`

```dotenv
SLACK_SIGNING_SECRET=...
SLACK_BOT_TOKEN=xoxb-...
SLACK_BOT_USER_ID=U0ACK1M63S8

GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=ya29.a0AR...

MONGODB_URI=mongodb+srv://...
MONGODB_DB_NAME=hex

FERNET_KEY=...
```

---

## 4. Slack app configuration

### 4.1. Basic creation

1. Go to https://api.slack.com/apps → **Create New App → From scratch**.
2. Name: `Hex`. Workspace: your target workspace.

### 4.2. Bot Token Scopes

Under **OAuth & Permissions → Bot Token Scopes**, add:

- `app_mentions:read` – receive `app_mention` events.
- `chat:write` – send messages.
- `channels:read` – read public channel names.
- `groups:read` – read private channel names.
- `im:read`, `mpim:read` – read IM/MPIM info.
- `users:read` – get display/real names via `users.info`.
- `reactions:write` – add/remove emoji reactions to acknowledge messages.

Then **Reinstall to Workspace** to apply new scopes.

### 4.3. Event Subscriptions

1. Set **Request URL** to `https://<ngrok-id>.ngrok.io/slack/events` (use `run.sh` to get the ngrok URL).
2. Under "Subscribe to bot events", add `app_mention`.
3. Save.

### 4.4. Invite the bot

In the target channel: `/invite @Hex`

---

## 5. Google Cloud & OAuth setup

### 5.1. Create a project and enable the API

1. Create a project at https://console.cloud.google.com/ (e.g. `hex-tasks-dev`).
2. **APIs & Services → Library** → enable **Google Tasks API**.

### 5.2. OAuth consent screen

1. **APIs & Services → OAuth consent screen** → External.
2. Fill app name, emails. Add the target Google account under **Test users**.
3. Leave publishing status as `Testing`.

### 5.3. Create OAuth Client ID

1. **Credentials → Create Credentials → OAuth client ID** → **Desktop app**.
2. Note the **Client ID** and **Client secret**.

### 5.4. Get a refresh token

```bash
export GOOGLE_CLIENT_ID="..."
export GOOGLE_CLIENT_SECRET="..."
python scripts/get_refresh_token.py
```

Follow the browser flow. Copy the printed `REFRESH_TOKEN` into your `.env`.

---

## 6. Running locally

1. Create the virtual environment (Python 3.13):

   ```bash
   python3.13 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

2. Create `.env` (see Section 3).

3. Start the bot (ngrok + Flask):

   ```bash
   ./run.sh
   ```

   The script prints the ngrok public URL. Set it as the Slack Event Subscription Request URL if it has changed.

4. In Slack, in your test channel:

   ```text
   @Hex tasks @you inline test
   ```

   or:

   ```text
   @Hex tasks
   * @you bullet test
   * @you @someone another bullet
   ```

**Expected behavior:**

- Hex adds 👀 to the message immediately.
- After Google confirms, Hex removes 👀 and replies in thread with ✓/✗ per task.
- A Google Tasks list named after the Slack channel is created (if it doesn't exist).

---

## 7. Running tests

```bash
./test.sh
```

Requires `MONGODB_URI` in the environment (or `.env`). Tests run against a `hex_test` database that is wiped after each test.

---

## 8. Current limitations & roadmap

- All tasks go to **one Google account**. Per-user OAuth is Phase 2 (see `PLAN.md`).
- No per-user Google auth or domain-wide delegation yet.

See `PLAN.md` for the full evolution plan (MongoDB persistence ✅, per-user OAuth, list/config commands, Kanopy deployment).
