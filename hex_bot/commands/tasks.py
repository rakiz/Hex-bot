from __future__ import annotations

import re
from typing import List, Tuple, Optional, Dict

from .base import Command, register_command
from ..db import get_refresh_token
from ..google_tasks import create_task, get_or_create_tasklist

MENTION_PATTERN = re.compile(r"<@([A-Z0-9]+)>")

@register_command
class TasksCommand(Command):
    """
    Hex `tasks` command.

    Examples:

      @Hex tasks @user1 @user2 do that

      @Hex tasks
      * @user1 do this
      * @user1 @user2 do that
    """

    name = "tasks"

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
    def _parse_bullet_line(line_text: str) -> List[Tuple[str, str]]:
        # Returns a list because one bullet with multiple @mentions expands to
        # one task per assignee, all with the same text.
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

        task_text = MENTION_PATTERN.sub("", body).strip()
        if not task_text:
            return []

        return [(uid, task_text) for uid in mentions]

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

        # Each parsed task: (assignee_id or None, task_text)
        parsed_tasks: List[Tuple[Optional[str], str]] = []

        # A line is a task line if it has a bullet prefix (*, -, •) OR contains a @mention.
        # Slack sends its rich-text bullets as • (U+2022), not *.
        has_bullets = any(
            line.strip().startswith(("*", "-", "•")) or bool(MENTION_PATTERN.search(line))
            for line in bullets
        )

        # Inline form: "@Hex tasks @alice do this" — normalize to a bullet so the
        # same _parse_bullet_line path handles both input styles.
        if not has_bullets:
            tokens = command_line.split()
            # Expecting: "<@BOTID> tasks xxx..."
            if len(tokens) >= 3:
                inline_text = " ".join(tokens[2:]).strip()
                if inline_text:
                    synthetic = f"* {inline_text}"
                    bullets = [synthetic]
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

        # One Google tasklist per Slack channel, created on demand.
        # If channel resolution fails we leave channel_name=None, which makes
        # create_task fall back to "@default" (the user's default Google tasklist).
        channel_name: Optional[str] = None
        try:
            info = self.slack.conversations_info(channel=channel)
            ch = info.get("channel", {})
            channel_name = ch.get("name") or ch.get("id") or "Hex"
        except Exception as exc:
            self.log.exception("Failed to get channel name, using default list: %s", exc)

        # Slack permalink to be added in the notes (optional if failure)
        permalink = None
        try:
            resp = self.slack.chat_getPermalink(channel=channel, message_ts=ts)
            permalink = resp.get("permalink")
        except Exception:
            permalink = None

        # Signal to the user that the bot has seen the message and is working on it
        try:
            self.slack.reactions_add(channel=channel, name="eyes", timestamp=ts)
        except Exception as exc:
            self.log.warning("reactions_add failed: %s", exc)

        sender_mention = f"<@{user}>"
        successes: List[str] = []
        failures: List[str] = []

        for assignee_id, task_text in parsed_tasks:
            # Each assignee has their own Google account — look up their token.
            # assignee_id is always set: _parse_bullet_line never returns (None, text).
            refresh_token = get_refresh_token(assignee_id)
            assignee_mention = f"<@{assignee_id}>"

            if not refresh_token:
                target = f"<@{assignee_id}>" if assignee_id else sender_mention
                self.log.warning("TasksCommand: %s not registered, skipping %r", target, task_text)
                failures.append(
                    f'✗ {target} is not registered — they need to type "@Hex register" '
                    "to connect their Google Tasks account."
                )
                continue

            # Tasklist lookup uses the assignee's token (their own Google account).
            tasklist_id: Optional[str] = None
            if channel_name:
                try:
                    tasklist_id = get_or_create_tasklist(channel_name, refresh_token=refresh_token)
                except Exception as exc:
                    self.log.exception("Failed to get tasklist for %s: %s", assignee_id or user, exc)

            # Default title set before the try so the except handler can log it even
            # if _get_user_display_name raises before google_title is reassigned.
            google_title = f"[unassigned] {task_text}"
            notes = f"From Slack: {permalink}" if permalink else ""

            try:
                # Google title uses a readable name, not a raw Slack ID
                if assignee_id is not None:
                    assignee_name = self._get_user_display_name(assignee_id)
                    google_title = f"[{assignee_name}] {task_text}"

                create_task(title=google_title, notes=notes, tasklist_id=tasklist_id, refresh_token=refresh_token)

                # Only added to the reply after Google confirms the task was created
                successes.append(
                    f"✓ {sender_mention} → {assignee_mention}: {task_text}"
                )
            except Exception as exc:
                self.log.exception("Failed to create Google Task for %r: %s", google_title, exc)
                failures.append(
                    f"✗ {assignee_mention}: {task_text}"
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

        # Remove the "eyes" reaction now that the summary has been posted
        try:
            self.slack.reactions_remove(channel=channel, name="eyes", timestamp=ts)
        except Exception as exc:
            self.log.warning("reactions_remove failed: %s", exc)