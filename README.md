
# Hex – Slack → Google Tasks Bot

**Hex** is a small Python/Flask bot that:

- Listens for `@Hex tasks` mentions in Slack.
- Parses inline or bullet-form task descriptions with `@mentions`.
- Creates one **Google Task per assignee**, grouped into a **Google Tasks list per Slack channel**.
- Replies in Slack summarizing who assigned what to whom.

This document captures how the project works and how to re-create all the required configuration (Slack, Google, local dev) so Future‑You doesn’t have to reverse-engineer it.

---

## 1. High‑level architecture

**Flow (personal dev workspace):**

1. In Slack (personal workspace), user posts:

   ```text
   @Hex tasks
   * @alice do this
   * @alice @bob do that
   ```

   or

   ```text
   @Hex tasks @alice @bob do that
   ```

2. Slack sends an `app_mention` event to Hex via a public HTTPS URL (ngrok in dev).
3. Hex (Flask app) parses:
   - Each bullet / inline line → one `(assignee_id, task_text)` pair per `@mention`.
4. Hex looks up:
   - **Human‑readable names** for each assignee (via `users.info`).
   - **Channel name** for per‑channel tasklists (`conversations.info`).
5. Hex creates one **Google Task per assignee**:
   - `title = "[Display Name] {task_text}"`.
   - `notes` include the Slack permalink.
   - Tasks go into a **Google Tasks list whose title = Slack channel name** (created on demand).
6. Hex replies in the Slack thread:

   ```text
   Created N Google Tasks in my list:
   @sender assigned the following task to @alice: do this
   @sender assigned the following task to @alice: do that
   @sender assigned the following task to @bob: do that
   ```

**Important:**  
In the current dev version, **all tasks are created in one Google account** (the one that did the OAuth flow). `@mentions` are semantic: they drive title/summary text, not which Google account receives the task.

---

## 2. Code structure

Approximate layout:

```text
hex-bot/
  app.py               # Flask entrypoint (/slack/events, /healthz)
  config.py            # Central config (Slack, Google env vars)
  slack_client.py      # Slack WebClient + signature verification
  dispatcher.py        # Routes app_mention events to subcommands
  commands/
    __init__.py        # Imports to register commands
    base.py            # Command base class + registry
    tasks.py           # "@Hex tasks" command
  google_tasks.py      # Google Tasks client + tasklist helpers
  requirements.txt
  Dockerfile           # For Kanopy later
```

Key modules:

- **`app.py`**
  - Defines `/slack/events`:
    - Handles Slack URL verification (`url_verification`).
    - Verifies signatures for real events.
    - Passes `app_mention` events to `dispatcher.dispatch_app_mention`.
- **`slack_client.py`**
  - `WebClient` with `SLACK_BOT_TOKEN`.
  - `verify_slack_signature(request)` using `SLACK_SIGNING_SECRET`.
  - `get_bot_user_id()` via `auth.test()` (cached).
- **`dispatcher.py`**
  - Splits text into lines, finds the line with `<@BOTID> tasks`.
  - Passes the slice from that line onward to `TasksCommand`.
- **`commands/tasks.py`**
  - Parses:
    - Inline: `@Hex tasks @user1 @user2 do that`.
    - Bullets:

      ```text
      @Hex tasks
      * @user1 do this
      * @user1 @user2 do that
      ```
  - Produces `List[(assignee_id or None, task_text)]`.
  - Uses `users.info` to get display/real names.
  - Uses `conversations.info` to get the channel name.
  - Calls `google_tasks.create_task(...)`.
  - Posts a Slack summary message.
- **`google_tasks.py`**
  - Builds a `tasks` API client using OAuth2 `Credentials` with a **refresh token**.
  - Maintains a cache of Google **tasklist IDs** by title (Slack channel name).
  - Provides:
    - `get_or_create_tasklist(title) -> tasklist_id`
    - `create_task(title, notes, tasklist_id=None) -> dict`

---

## 3. Environment variables and secrets

You need the following env vars when running Hex:

### 3.1. Slack

From your **Slack app in the personal workspace**:

- `SLACK_SIGNING_SECRET`
  - Found under: **Basic Information → App Credentials → Signing Secret**.
- `SLACK_BOT_TOKEN`
  - Found under: **OAuth & Permissions → Bot User OAuth Token** (after installing the app).

Optional (but can be set to skip `auth.test` each time):

- `SLACK_BOT_USER_ID`
  - Value from `auth.test()["user_id"]`. Not required; Hex can discover it.

Example:

```bash
export SLACK_SIGNING_SECRET="..."
export SLACK_BOT_TOKEN="xoxb-..."
# optional
export SLACK_BOT_USER_ID="U0ACK1M63S8"
```

### 3.2. Google Tasks

From your **Google Cloud project for Hex**:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- Optional:
  - `GOOGLE_TASKS_LIST_ID` (default `@default` if not set; used as fallback when per‑channel list lookup fails)

Example:

```bash
export GOOGLE_CLIENT_ID="...apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="..."
export GOOGLE_REFRESH_TOKEN="ya29.a0AR..."
export GOOGLE_TASKS_LIST_ID="@default"
```

---

## 4. Slack app configuration (personal workspace)

This is the **dev / test** app.

### 4.1. Basic creation

1. Go to https://api.slack.com/apps → **Create New App → From scratch**.
2. Name: `Hex`.
3. Workspace: your personal Slack workspace.

### 4.2. App Home / bot user

- In **App Home**, enable messages if needed.
- This ensures a bot user exists for the app.

### 4.3. Bot Token Scopes

Under **OAuth & Permissions → Bot Token Scopes**, add:

- `app_mentions:read` – receive `app_mention` events.
- `chat:write` – send messages/ephemerals.
- `channels:read` – read channel names for public channels.
- `groups:read` – read names of private channels the bot is in.
- `im:read`, `mpim:read` – read IM/MPIM info if you ever use Hex there.
- `users:read` – get display/real names via `users.info`.
- `reactions:write` – add/remove emoji reactions to acknowledge messages.

Then **Reinstall to Workspace** (Install App → Reinstall) to grant the new scopes.

### 4.4. Event Subscriptions

You need a public URL pointing to `/slack/events`. In dev, use **ngrok**.

1. Run your app locally on port 8080:

   ```bash
   python app.py
   ```

2. In a second terminal, run:

   ```bash
   ngrok http 8080
   ```

   Note the HTTPS URL, e.g. `https://abcd-1234.ngrok.io`.

3. In **Event Subscriptions**:
   - Enable events.
   - Set **Request URL** to:

     ```text
     https://abcd-1234.ngrok.io/slack/events
     ```

   - Wait for Slack to show it as **Verified**.
   - Under “Subscribe to bot events”, add:
     - `app_mention`.

4. Save.

### 4.5. Installing and inviting Hex

1. In **Install App**, click **Install to Workspace** or **Reinstall to Workspace**, accept scopes.
2. In your personal workspace, in a test channel:

   ```text
   /invite @Hex
   ```

---

## 5. Google Cloud & OAuth setup

These steps are for the **Hex** project in Google Cloud (separate from any other projects you might have).

### 5.1. Create a project

1. Go to https://console.cloud.google.com/
2. Create a new project, e.g. `hex-tasks-dev`.

### 5.2. Enable the Google Tasks API

1. In the project, go to **APIs & Services → Library**.
2. Search for **Google Tasks API**.
3. Click it → **Enable**.

### 5.3. Configure OAuth consent screen

1. **APIs & Services → OAuth consent screen**.
2. User type: **External** (for a personal or non‑managed account).
3. Fill required fields:
   - App name: `Hex Tasks Dev`.
   - User support email: your email.
   - Developer contact info: your email.
4. Scopes: default is fine; the script will request Tasks scope.
5. Under **Test users**, add the **exact email** of the Google account you’ll use to run the dev script.
6. Ensure:
   - **Publishing status** is `Testing`.
   - You do *not* need to publish / verify.

### 5.4. Create OAuth Client ID (Desktop)

1. **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
2. Application type: **Desktop app**.
3. Name: `Hex Dev Desktop`.
4. Save; note the **Client ID** and **Client secret**.

### 5.5. Get a refresh token

1. Run the attached script (e.g. `get_refresh_token.py`):

   ```bash
    export GOOGLE_CLIENT_ID="YOUR_CLIENT_ID"
    export GOOGLE_CLIENT_SECRET="YOUR_CLIENT_SECRET"
    python get_refresh_token.py
   ```

2. When the browser opens:
   - Log in with the **Test user** account you configured.
   - Click through the “unverified app” warning (Advanced → continue).
   - Approve the Tasks scope.
3. Back in the terminal, note the printed `REFRESH_TOKEN`.


---

## 6. Running Hex locally

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Set all env vars:

   ```bash
   export SLACK_SIGNING_SECRET="..."
   export SLACK_BOT_TOKEN="xoxb-..."
   export LOG_LEVEL=INFO

   export GOOGLE_CLIENT_ID="..."
   export GOOGLE_CLIENT_SECRET="..."
   export GOOGLE_REFRESH_TOKEN="..."
   export GOOGLE_TASKS_LIST_ID="@default"
   ```

3. Run Flask app:

   ```bash
   python app.py
   ```

4. Run ngrok:

   ```bash
   ngrok http 8080
   ```

5. Confirm Slack’s Event Subscription Request URL is:

   ```text
   https://<ngrok-id>.ngrok.io/slack/events
   ```

6. In Slack, in your test channel:

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

- Slack:
  - `Created N Google Tasks in my list:`
  - One line per task:  
    `@sender assigned the following task to @assignee: task text`
- Google Tasks:
  - A tasklist whose title is the Slack channel name.
  - Inside: one task per assignee, with title:
    - `[Display Name] task text`
  - Notes: `From Slack: &lt;permalink&gt;`

---

## 7. Current limitations & future work

- All tasks are created in **one** Google account (the one used for OAuth).
  - `@mentions` influence the title and Slack summary only.
- No persistence beyond Google; there’s no DB.
- No per‑user Google auth or domain‑wide delegation.
- No dry‑run or admin command; everything runs on `@Hex tasks`.

**Possible future improvements:**

- Per‑user OAuth linking (`@Hex link-google`) and a small DB of Slack→Google tokens.
- Support for a “dry run” flag (`@Hex tasks --dry-run ...`).
- Better error reporting in Slack if Google/Slack calls fail.
- Switch replies back to ephemeral (`chat_postEphemeral`) in production channels.

---

This README is focused on the **working dev/prototype** in a personal workspace.
