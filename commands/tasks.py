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
        # cache Slack user_id -> display_name
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

        # If there's no bullets, consider the command line as a unique inlined task
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

        # Set up the Google tasklist name for this channel
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

        created_count = 0
        sender_mention = f"<@{user}>"
        summary_lines: List[str] = []

        for assignee_id, task_text in parsed_tasks:
            # Default title for logging in case of early failure
            google_title = f"[unassigned] {task_text}"
            notes = ""
            if permalink:
                notes = f"From Slack: {permalink}"

            try:
                # Google title: readable name not a Slack ID
                if assignee_id is not None:
                    assignee_name = self._get_user_display_name(assignee_id)
                    google_title = f"[{assignee_name}] {task_text}"

                create_task(
                    title=google_title,
                    notes=notes,
                    tasklist_id=tasklist_id,
                )
                created_count += 1

                # Add to summary only on success
                if assignee_id is not None:
                    assignee_mention = f"<@{assignee_id}>"
                else:
                    assignee_mention = "unassigned"

                summary_lines.append(
                    f"{sender_mention} assigned the following task to {assignee_mention}: {task_text}"
                )
            except Exception as exc:
                self.log.exception("Failed to create Google Task for %r: %s", google_title, exc)

        if created_count > 0:
            header = f"Created {created_count} Google Tasks in my list:"
            text = header + "\n" + "\n".join(summary_lines)
            self.slack.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=ts,
            )
        elif parsed_tasks:  # Only send failure message if we had tasks to begin with
            self.slack.chat_postMessage(
                channel=channel,
                text="I tried to create tasks, but something went wrong and none were created. Please check my logs for details.",
                thread_ts=ts,
            )