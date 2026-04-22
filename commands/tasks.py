from __future__ import annotations

import re
from typing import List, Tuple, Optional, Dict

from .base import Command, register_command
from google_tasks import create_task, get_or_create_tasklist

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
        # Per-request cache: avoids duplicate users_info calls within one command.
        # Will persist across requests once we have a DB (Phase 1).
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
    def _parse_bullet_line(line_text: str) -> List[Tuple[Optional[str], str]]:
        # Returns a list because one bullet with multiple @mentions expands to
        # one task per assignee, all with the same text.
        line = line_text.strip()
        if not line:
            return []

        if line.startswith("*") or line.startswith("-"):
            body = line.lstrip("*-").strip()
        else:
            body = line

        mentions = MENTION_PATTERN.findall(body)
        task_text = MENTION_PATTERN.sub("", body).strip()
        if not task_text:
            return []

        result: List[Tuple[Optional[str], str]] = []
        if mentions:
            for uid in mentions:
                result.append((uid, task_text))
        else:
            # No @mention: create an unassigned task so the text isn't silently dropped
            result.append((None, task_text))
        return result

    def handle(
        self,
        *,
        channel: str,
        user: str,
        ts: str,
        text_lines: List[str],
    ) -> None:
        self.log.info("TasksCommand.handle lines=%r", text_lines)

        if not text_lines:
            return

        # First line: '@Hex tasks ...'
        command_line = text_lines[0].strip()
        # Next  lines: potential bullets
        bullets = text_lines[1:]

        # Each parsed task: (assignee_id or None, task_text)
        parsed_tasks: List[Tuple[Optional[str], str]] = []

        # Is there any bullet after the command ?
        has_bullets = any(
            line.strip().startswith(("*", "-"))
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
                "I saw '@Hex tasks' but no task content. "
                "Use bullets like:\n"
                "@Hex tasks\n"
                "* @alice do this\n"
                "* @bob do that\n"
                "or inline like:\n"
                "@Hex tasks @alice @bob do that"
            )
            self.slack.chat_postMessage(
                channel=channel,
                text=usage,
                thread_ts=ts,
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
                thread_ts=ts,
            )
            return

        # One Google tasklist per Slack channel, created on demand.
        # Falls back to GOOGLE_TASKS_LIST_ID (env var, default "@default") if the
        # channel name can't be resolved.
        tasklist_id: Optional[str] = None
        try:
            info = self.slack.conversations_info(channel=channel)
            ch = info.get("channel", {})
            channel_name = ch.get("name") or ch.get("id") or "Hex"
            tasklist_id = get_or_create_tasklist(channel_name)
        except Exception as exc:
            self.log.exception("Failed to get channel name, using default list: %s", exc)
            tasklist_id = None

        # Slack permalink Slack to be added in the notes (optional if failure)
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
            google_title = f"[unassigned] {task_text}"
            notes = f"From Slack: {permalink}" if permalink else ""
            assignee_mention = f"<@{assignee_id}>" if assignee_id else "unassigned"

            try:
                # Google title uses a readable name, not a raw Slack ID
                if assignee_id is not None:
                    assignee_name = self._get_user_display_name(assignee_id)
                    google_title = f"[{assignee_name}] {task_text}"

                create_task(title=google_title, notes=notes, tasklist_id=tasklist_id)

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
                thread_ts=ts,
            )

        # Remove the "eyes" reaction now that the summary has been posted
        try:
            self.slack.reactions_remove(channel=channel, name="eyes", timestamp=ts)
        except Exception as exc:
            self.log.warning("reactions_remove failed: %s", exc)