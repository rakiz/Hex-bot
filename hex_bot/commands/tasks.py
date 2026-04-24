from __future__ import annotations

import re
from datetime import date, timedelta
from typing import List, Tuple, Optional, Dict

from google.auth.exceptions import RefreshError

from .base import Command, register_command
from ..db import get_refresh_token
from ..google_tasks import create_task, get_or_create_tasklist

MENTION_PATTERN = re.compile(r"<@([A-Z0-9]+)>")

_PROCESSING_REACTION = "eyes"   # Slack reaction added while tasks are being created
_FALLBACK_CHANNEL_NAME = "Hex"  # tasklist name used when Slack channel name can't be resolved

# Matches 'me', 'me:list-name', or 'me:"list name with spaces"' placed right after
# '@Hex tasks'. Captures: group 1 = quoted list name, group 2 = unquoted list name.
# Anything remaining after the me token is the inline task text (group 3).
_ME_PREFIX_RE = re.compile(
    r"^<@[A-Z0-9]+>\s+tasks\s+me(?::(?:\"([^\"]+)\"|(\S+)))?(?:\s+(.*))?$",
    re.IGNORECASE,
)


def _parse_me_prefix(command_line: str) -> Tuple[bool, Optional[str], str]:
    """
    Detect 'me[:list]' immediately after '@Hex tasks'.

    Returns (has_me, list_override, remaining_task_text).
    list_override is None when no list was specified (use default resolution).
    remaining_task_text is the inline task text following the me token, or "".
    """
    m = _ME_PREFIX_RE.fullmatch(command_line.strip())
    if not m:
        return False, None, ""
    list_name = m.group(1) or m.group(2)  # quoted takes priority over unquoted
    remaining = (m.group(3) or "").strip()
    return True, list_name, remaining

# Matches an optional due-date clause anywhere in a task line.
# Two syntaxes are accepted:
#   "by <token>"  — e.g. "by Friday", "by tomorrow", "by 2026-04-28"
#   "#YYYY-MM-DD" — shorthand hash prefix, e.g. "#2026-04-28"
# The pattern is stripped from the line before building the task title so
# "fix login bug by Friday" becomes the title "fix login bug".
_DUE_PATTERN = re.compile(
    r"\s+by\s+(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4}-\d{2}-\d{2})"
    r"|\s*#(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _resolve_due_date(token: str) -> Optional[str]:
    """Convert a due-date token to an RFC 3339 UTC midnight string, or None if unparseable."""
    today = date.today()
    t = token.lower()
    if t == "today":
        d = today
    elif t == "tomorrow":
        d = today + timedelta(days=1)
    elif t in _WEEKDAYS:
        days = (_WEEKDAYS[t] - today.weekday()) % 7
        # days == 0 means today IS already that weekday; "by Friday" when it's
        # already Friday means next Friday, so we substitute 7 to move forward a week.
        d = today + timedelta(days=days or 7)
    else:
        try:
            d = date.fromisoformat(token)
        except ValueError:
            return None
    return f"{d.isoformat()}T00:00:00.000Z"


@register_command
class TasksCommand(Command):
    """
    Hex `tasks` command.

    Examples:

      @Hex tasks @user1 @user2 do that

      @Hex tasks
      * @user1 do this
      * @user1 @user2 do that

    Due dates (optional, appended to any bullet):
      * @user1 fix login bug by Friday
      * @user1 fix login bug by 2026-04-28
      * @user1 fix login bug #2026-04-28
    """

    name = "tasks"
    description = "Create Google Tasks from a bullet list or inline mention."
    usage = "@Hex tasks [me[:list]] [@mention ...] [task text] [by <date>]"
    notes = (
        "One task is created per @mention. Each assignee must have registered their Google account with @Hex register.\n"
        "me — inline shorthand to assign a task to yourself: @Hex tasks me fix the bug. "
        "me:list or me:\"list name\" also sets the tasklist. "
        "me is inline-only and cannot be combined with other @mentions.\n"
        "Bullet form: one task per line, starting with * or -. "
        "Inline form: @mentions and task text all on the same line as @Hex tasks.\n"
        "Due dates are optional — append 'by Friday', 'by tomorrow', or 'by 2026-05-01' to any line.\n"
        "The sender does not need to be registered — only the assignees do."
    )
    examples = [
        "@Hex tasks @alice fix the login bug",
        "@Hex tasks @alice @bob review the PR by Friday",
        "@Hex tasks me fix the login bug",
        "@Hex tasks me:my-project fix the login bug",
        "@Hex tasks\n* @alice do this\n* @bob do that by 2026-05-01",
    ]

    def __init__(self, *, slack_client, logger):
        super().__init__(slack_client=slack_client, logger=logger)
        # Avoids duplicate users_info API calls when the same user appears in
        # multiple bullets within a single command invocation.
        self._user_name_cache: Dict[str, str] = {}

    def _get_user_display_name(self, user_id: str) -> str:
        """
        Return a readable name for a Slack user (display_name, real_name, or name).
        """
        if user_id in self._user_name_cache:
            return self._user_name_cache[user_id]

        try:
            resp = self.slack.users_info(user=user_id)
            self.log.info("users_info(%s) response=%r", user_id, resp)
            user = resp.get("user", {})
            profile = user.get("profile", {})
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or user.get("name")
                or user_id
            )
        except Exception as exc:
            self.log.exception("users_info(%s) failed: %s", user_id, exc)
            name = user_id

        if name == user_id:
            self.log.warning("Using raw user_id as name for %s", user_id)

        self._user_name_cache[user_id] = name
        return name

    @staticmethod
    def _parse_bullet_line(line_text: str) -> List[Tuple[str, Optional[str], Optional[str]]]:
        """
        Parse one line into a list of (assignee_id, task_text, due_iso) tuples.

        Returns a list because one bullet with multiple @mentions expands to one
        task per assignee. Returns [] when the line has no @mention (silently
        ignored). Returns (assignee_id, None, None) when a mention exists but
        there is no task text — the caller should report this as a failure.
        """
        line = line_text.strip()
        if not line:
            return []

        # Strip optional bullet prefix: *, -, or • (Slack's rich-text bullet character)
        if line[0] in ("*", "-", "•"):
            body = line[1:].strip()
        else:
            body = line

        mentions = MENTION_PATTERN.findall(body)
        if not mentions:
            # Lines without @mention are silently ignored — they're context or free text,
            # not tasks to assign.
            return []

        # Extract optional due date before stripping mentions
        due_iso: Optional[str] = None
        due_match = _DUE_PATTERN.search(body)
        if due_match:
            token = due_match.group(1) or due_match.group(2)
            due_iso = _resolve_due_date(token)
            body = _DUE_PATTERN.sub("", body, count=1)

        # Remove mentions and normalize the gaps they leave behind
        task_text = re.sub(r" {2,}", " ", MENTION_PATTERN.sub("", body)).strip()

        if not task_text:
            # Mention present but no task text — signal as failure via None
            return [(uid, None, None) for uid in mentions]

        return [(uid, task_text, due_iso) for uid in mentions]

    def handle(
        self,
        *,
        channel: str,
        user: str,
        ts: str,
        thread_ts: Optional[str] = None,
        text_lines: List[str],
    ) -> None:
        self.log.info("TasksCommand.handle lines=%r", text_lines)

        # The SENDER does not need to be registered — it's the ASSIGNEE who needs a
        # Google account. Registration is checked per-assignee in the task loop below.

        if not text_lines:
            return

        # First line: '@Hex tasks ...'
        command_line = text_lines[0].strip()
        # Next  lines: potential bullets
        bullets = text_lines[1:]

        # Detect 'me[:list]' right after '@Hex tasks': self-assignment shorthand.
        # list_override replaces channel-name resolution for this invocation.
        has_me, list_override, me_remaining = _parse_me_prefix(command_line)

        # Each parsed task: (assignee_id, task_text or None, due_iso or None)
        parsed_tasks: List[Tuple[str, Optional[str], Optional[str]]] = []

        # A line is a task line if it has a bullet prefix (*, -, •) OR contains a @mention.
        # Slack sends its rich-text bullets as • (U+2022), not *.
        has_bullets = any(
            line.strip().startswith(("*", "-", "•")) or bool(MENTION_PATTERN.search(line))
            for line in bullets
        )

        if not has_bullets:
            if has_me and me_remaining:
                # "me[:list] task text" inline form — one task for the sender only.
                # Strip any stray @mentions from the text (me is not compatible with
                # other assignees; any mentions in the text are silently ignored).
                clean_text = re.sub(r" {2,}", " ", MENTION_PATTERN.sub("", me_remaining)).strip()
                if clean_text:
                    bullets = [f"* <@{user}> {clean_text}"]
                    has_bullets = True
            elif not has_me:
                # Regular inline form: "@Hex tasks @alice do this"
                tokens = command_line.split()
                if len(tokens) >= 3:
                    inline_text = " ".join(tokens[2:]).strip()
                    if inline_text:
                        bullets = [f"* {inline_text}"]
                        has_bullets = True

        if not has_bullets:
            usage = (
                "I saw `@Hex tasks` but no task content.\n\n"
                "*Bullet form* (one task per line):\n"
                "`@Hex tasks`\n"
                "`* @alice do this`\n"
                "`* @alice @bob do that` ← creates one task per person\n\n"
                "*Inline form* (single task):\n"
                "`@Hex tasks @alice @bob do that`"
            )
            self.slack.chat_postMessage(
                channel=channel,
                text=usage,
                thread_ts=thread_ts or ts,
            )
            return

        for bullet_line in bullets:
            parsed_tasks.extend(self._parse_bullet_line(bullet_line))

        self.log.info("TasksCommand parsed_tasks=%r", parsed_tasks)

        if not parsed_tasks:
            msg = (
                "I saw '@Hex tasks' but couldn't parse any tasks. "
                "Make sure lines look like '* @alice do this'."
            )
            self.slack.chat_postMessage(
                channel=channel,
                text=msg,
                thread_ts=thread_ts or ts,
            )
            return

        # Resolve the tasklist name: explicit override > channel name > fallback.
        # list_override comes from 'me:name' on the command line; if set, skip the
        # Slack API call entirely.
        channel_name: Optional[str] = list_override
        if channel_name is None:
            try:
                info = self.slack.conversations_info(channel=channel)
                ch = info.get("channel", {})
                channel_name = ch.get("name") or ch.get("id") or _FALLBACK_CHANNEL_NAME
            except Exception as exc:
                self.log.exception("Failed to get channel name: %s", exc)

        # Slack permalink to be added in the notes (optional if failure)
        permalink = None
        try:
            resp = self.slack.chat_getPermalink(channel=channel, message_ts=ts)
            permalink = resp.get("permalink")
        except Exception:
            permalink = None

        # Signal to the user that the bot has seen the message and is working on it
        try:
            self.slack.reactions_add(channel=channel, name=_PROCESSING_REACTION, timestamp=ts)
        except Exception as exc:
            self.log.warning("reactions_add failed: %s", exc)

        sender_mention = f"<@{user}>"
        successes: List[str] = []
        failures: List[str] = []

        for assignee_id, task_text, due_date in parsed_tasks:
            assignee_mention = f"<@{assignee_id}>"

            # Mention found but no task text on that line
            if task_text is None:
                failures.append(f"✗ {assignee_mention} — no task text found on that line.")
                continue

            # Each assignee has their own Google account — look up their token.
            # assignee_id is always set: _parse_bullet_line never returns (None, text).
            refresh_token = get_refresh_token(assignee_id)

            if not refresh_token:
                self.log.warning("TasksCommand: %s not registered, skipping %r", assignee_mention, task_text)
                failures.append(
                    f'✗ {assignee_mention} is not registered — they need to type "@Hex register" '
                    "to connect their Google Tasks account."
                )
                continue

            # Tasklist lookup uses the assignee's token (their own Google account).
            tasklist_id: Optional[str] = None
            if channel_name:
                try:
                    tasklist_id = get_or_create_tasklist(channel_name, refresh_token=refresh_token)
                except RefreshError:
                    self.log.warning("RefreshError getting tasklist for %s", assignee_id)
                    failures.append(
                        f'✗ {assignee_mention}: Google account disconnected — '
                        f'type "@Hex register" to reconnect.'
                    )
                    continue
                except Exception as exc:
                    self.log.exception("Failed to get tasklist for %s: %s", assignee_id, exc)
            else:
                # channel_name resolution failed — task will land in Google's @default list
                self.log.warning("channel_name unknown; task for %s going to @default tasklist", assignee_id)

            # Default title set before the try so the except handler can log it even
            # if _get_user_display_name raises before google_title is reassigned.
            google_title = f"[unassigned] {task_text}"
            notes = f"From Slack: {permalink}" if permalink else ""

            try:
                # Google title uses a readable name, not a raw Slack ID
                assignee_name = self._get_user_display_name(assignee_id)
                google_title = f"[{assignee_name}] {task_text}"

                create_task(
                    title=google_title,
                    notes=notes,
                    due=due_date,
                    tasklist_id=tasklist_id,
                    refresh_token=refresh_token,
                )

                # Only added to the reply after Google confirms the task was created
                due_label = f" _(due {due_date[:10]})_" if due_date else ""
                if not channel_name:
                    due_label += " _(added to your default tasklist — channel name unavailable)_"
                successes.append(
                    f"✓ {sender_mention} → {assignee_mention}: {task_text}{due_label}"
                )
            except RefreshError:
                self.log.warning("RefreshError creating task for %s", assignee_id)
                failures.append(
                    f'✗ {assignee_mention}: {task_text} — Google account disconnected, '
                    f'type "@Hex register" to reconnect.'
                )
            except Exception as exc:
                self.log.exception("Failed to create Google Task for %r: %s", google_title, exc)
                failures.append(
                    f"✗ {assignee_mention}: {task_text} — task creation failed, please try again."
                )

        # Build a single reply that reflects the actual outcome from Google
        reply_lines: List[str] = []
        if successes:
            reply_lines.append(f"Created {len(successes)} task(s) in Google Tasks:")
            reply_lines.extend(successes)
        if failures:
            reply_lines.append(f"Failed to create {len(failures)} task(s):")
            reply_lines.extend(failures)

        if reply_lines:
            self.slack.chat_postMessage(
                channel=channel,
                text="\n".join(reply_lines),
                thread_ts=thread_ts or ts,
            )

        # Remove the "eyes" reaction now that the summary has been posted.
        # Always attempted — even if the reply above raised, we don't want a
        # stuck 👀 emoji on the message.
        try:
            self.slack.reactions_remove(channel=channel, name=_PROCESSING_REACTION, timestamp=ts)
        except Exception as exc:
            self.log.warning("reactions_remove failed: %s", exc)
