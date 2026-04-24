
# Hex – Slack → Google Tasks Bot

**Hex** is a small Python/Flask bot that:

- Listens for `@Hex` mentions in Slack.
- Parses inline or bullet-form task descriptions with `@mentions`.
- Creates one **Google Task per assignee**, in **that assignee's own Google account**, grouped into a **Google Tasks list per Slack channel**.
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
   - Each task goes into **the assignee's own Google account** (looked up by their Slack user ID).
   - `title = "[Display Name] {task_text}"`
   - `notes` include the Slack permalink.
   - Tasks go into a **Google Tasks list whose title = Slack channel name** (created on demand in each assignee's account).
6. After Google confirms each task, Hex removes the 👀 reaction and replies in the Slack thread with a per-task ✓/✗ summary.

**Important:**
The **assignee** must be registered with `@Hex register` (not the sender). If an assignee is not registered, Hex reports a failure for their task and continues with the others.

---

## 2. Code structure

```text
hex-bot/
  hex_bot/
    __init__.py
    app.py               # Flask entrypoint (/slack/events, /healthz, /oauth/google/callback)
    config.py            # Central config (reads env vars + .env)
    slack_client.py      # Slack WebClient + signature verification
    dispatcher.py        # Routes app_mention events to subcommands
    db.py                # MongoDB persistence (users, event dedup, Fernet encryption)
    google_tasks.py      # Google Tasks client + tasklist helpers
    commands/
      __init__.py
      base.py            # Command base class + registry (@register_command decorator)
      tasks.py           # "@Hex tasks" command
      register.py        # "@Hex register" command (starts Google OAuth flow)
      unregister.py      # "@Hex unregister" command
      status.py          # "@Hex status" command
      tasklist.py        # "@Hex tasklist [name] [all] [limit N] [skip N]" command
      config.py          # "@Hex config tasklist <name|default>" command
      help.py            # "@Hex help [command]" command
  tests/
    __init__.py
    conftest.py          # pytest fixtures (MongoDB hex_test database)
    test_db.py           # MongoDB CRUD and event deduplication tests
    test_parsing.py      # Bullet/inline parsing tests
    test_signature.py    # Slack signature verification tests
    test_slack_client.py # Bot user ID caching tests
    test_oauth.py        # OAuth URL generation / state verification tests
    test_google_tasks.py # Google Tasks client tests
    test_app.py          # Flask endpoint tests (URL verification, OAuth callback)
    test_dispatcher.py   # Command routing tests
    test_commands.py     # register / unregister / status command tests
    test_commands_tasks.py  # tasks command tests (parsing, per-assignee logic, due dates, me)
    test_commands_list_config.py  # tasklist and config command tests
    test_commands_help.py         # help command tests
  scripts/
    get_refresh_token.py # One-off helper to obtain a Google refresh token
  Dockerfile             # Production image (python:3.13-slim + gunicorn)
  build.sh               # Build the Docker image locally
  run.sh                 # Start ngrok + Flask locally (--docker flag available)
  test.sh                # Run the pytest suite
  requirements.txt       # Production dependencies
  requirements-dev.txt   # Dev/test dependencies (-r requirements.txt + pytest)
  pytest.ini
  .env                   # Local secrets (never committed)
```

Key modules:

- **`app.py`** – `/slack/events` endpoint: URL verification, signature check, event deduplication (MongoDB TTL), dispatches `app_mention` in a background thread to avoid Slack's 3s timeout. `/oauth/google/callback` handles the OAuth redirect from Google.
- **`config.py`** – reads all env vars; calls `load_dotenv()` so `.env` is loaded automatically.
- **`db.py`** – MongoDB persistence: user CRUD with Fernet-encrypted refresh tokens, event dedup via TTL collection (10 min window).
- **`slack_client.py`** – `WebClient`, `verify_slack_signature`, `get_bot_user_id`.
- **`dispatcher.py`** – finds the `@Hex <command>` line, routes to the matching command.
- **`commands/tasks.py`** – parses bullets/inline/`me` self-assignment, resolves names, handles due dates, calls Google Tasks per assignee, posts per-task summary.
- **`commands/tasklist.py`** – lists open tasks from a Google Tasks list (by channel name, configured default, or explicit name); supports `all`, `limit N`, `skip N`.
- **`commands/config.py`** – sets or resets the user's default tasklist name.
- **`commands/help.py`** – lists all registered commands (`@Hex help`) or shows usage and examples for one (`@Hex help <cmd>`). Documentation is pulled from each command's own class attributes — no centralised help strings.
- **`google_tasks.py`** – OAuth2 refresh-token client, tasklist cache (per token), `create_task`, `list_tasks`.

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

### 3.3. Public URL

- `PUBLIC_BASE_URL` *(optional, default `http://localhost:8080`)* – base URL used to build the Google OAuth callback URI.
  - In dev: `http://localhost:8080` works as-is (Google allows localhost for Desktop OAuth clients).
  - In prod: set to your public HTTPS domain.

### 3.4. MongoDB

- `MONGODB_URI` – e.g. `mongodb+srv://user:pass@cluster.mongodb.net/`
- `MONGODB_DB_NAME` *(optional, default `hex`)*

### 3.5. Encryption

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

# Optional — defaults to http://localhost:8080
# PUBLIC_BASE_URL=https://your-bot-domain.example.com

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
- `im:write` – open a DM to send registration confirmation.

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
2. Under **Authorized redirect URIs**, add:
   - `http://localhost:8080/oauth/google/callback` (for local dev)
   - Your production HTTPS URL when deploying.
3. Note the **Client ID** and **Client secret**.

---

## 6. Running locally

1. Create the virtual environment (Python 3.13):

   ```bash
   python3.13 -m venv .venv
   .venv/bin/pip install -r requirements-dev.txt
   ```

   `requirements.txt` contains production dependencies only (used by the Docker image).
   `requirements-dev.txt` adds pytest on top — use it for local development and running tests.

2. Create `.env` (see Section 3).

3. Start the bot (ngrok + Flask):

   ```bash
   ./run.sh
   ```

   Or with Docker (builds image first if needed):

   ```bash
   ./run.sh --docker
   ```

   The script prints the ngrok public URL. Set it as the Slack Event Subscription Request URL if it has changed.

4. Each user who wants tasks created in their Google account must register first:

   ```text
   @Hex register
   ```

   Click the link in the ephemeral message, complete the Google OAuth flow. Hex sends a DM when it's done.

5. Then create tasks:

   ```text
   @Hex tasks @you inline test
   ```

   or:

   ```text
   @Hex tasks
   * @you bullet test
   * @you @someone another bullet
   ```

**Available commands:**

| Command | Description |
|---|---|
| `@Hex register` | Connect your Google Tasks account (sends an OAuth link). |
| `@Hex unregister` | Disconnect your Google Tasks account. |
| `@Hex status` | Check whether you are registered and which tasklist is configured. |
| `@Hex tasks` | Create Google Tasks from a bullet list or inline mention. |
| `@Hex tasklist [name] [all] [limit N] [skip N]` | List open tasks (current channel, configured default, or named tasklist). |
| `@Hex config tasklist <name\|default>` | Set or reset your default tasklist name. |
| `@Hex help [command]` | List all commands, or show usage and examples for one. |

**Expected behavior for `@Hex tasks`:**

- Hex adds 👀 to the message immediately.
- After Google confirms, Hex removes 👀 and replies in thread with ✓/✗ per task.
- A Google Tasks list named after the Slack channel is created in the **assignee's** Google account (if it doesn't exist).
- The **sender** does not need to be registered — only the **assignees** do.
- If an assignee is not registered, Hex reports `✗` for their task and continues with the rest.

**Parsing rules — what counts as a task:**

| Input line | Result |
|---|---|
| `* @alice fix the bug` | 1 task for alice: _"fix the bug"_ |
| `* @alice @bob fix the bug` | 2 tasks: one for alice, one for bob — same text |
| `* fix @alice the bug` | 1 task for alice: _"fix the bug"_ (mention position doesn't matter) |
| `* @alice fix the bug by Friday` | 1 task for alice with due date set to next Friday |
| `* @alice fix the bug by 2026-04-28` | 1 task with explicit ISO due date |
| `* @alice fix the bug #2026-04-28` | same — alternative due date syntax |
| `* fix the bug` | ignored — no assignee, no task |
| `* @alice` | ✗ reported — mention found but no task text |
| `context line` | ignored — plain text without mention |
| `@Hex tasks @alice do this` | inline form: 1 task for alice (no bullet needed) |
| `@Hex tasks me fix the bug` | inline self-assignment: 1 task for the sender |
| `@Hex tasks me:my-project fix the bug` | self-assignment in tasklist _"my-project"_ |
| `@Hex tasks me:"my project" fix the bug` | same — quoted name allows spaces |

Each line with `@mention` creates one task per mentioned user. All mentions are stripped from the task title regardless of where they appear in the line.

**⚠️ Free-text lines with mentions also create tasks.** Any line that contains an `@mention` — even without a bullet prefix — is treated as a task. The task title is the entire line with all mentions removed. For example:

```
@Hex tasks
Please @alice review the auth code and @bob fix the login bug.
Context line with no mention — this is ignored.
```

Creates two tasks with the title `"Please review the auth code and fix the login bug."` (mentions stripped, gaps normalized). Use the bullet form for clean task titles:

```
@Hex tasks
* @alice review the auth code
* @bob fix the login bug
```

---

## 7. Running tests

```bash
./test.sh
```

Requires `MONGODB_URI` in the environment (or `.env`). Tests run against a `hex_test` database that is wiped after each test.

The suite has 152 tests covering: command parsing, per-assignee task creation, due dates, self-assignment (`me`), pagination, Google Tasks client (with RefreshError handling), OAuth state management, Slack signature verification, MongoDB encryption/dedup, and all seven commands (including help).

---

## 8. Roadmap

See `PLAN.md` for the full evolution plan (MongoDB persistence ✅, per-user OAuth ✅, list/config commands ✅, Docker ✅, help command ✅).

### Potential improvements

| Feature | Notes |
|---|---|
| **DM support** | Currently Hex only responds to `app_mention` events in channels. Supporting DMs requires: enabling the Messages Tab in App Home (Slack config), adding the `im:history` scope, subscribing to the `message.im` event, and updating the dispatcher to skip the `@Hex` prefix since users are already talking directly to the bot. |
