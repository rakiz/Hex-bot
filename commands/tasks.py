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

    Exemples:

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

        # Première ligne: '@Hex tasks ...'
        command_line = text_lines[0].strip()
        # Lignes suivantes: potentiels bullets
        bullets = text_lines[1:]

        # Chaque tâche parsée: (assignee_id ou None, task_text)
        parsed_tasks: List[Tuple[Optional[str], str]] = []

        def parse_bullet_line(line_text: str) -> List[Tuple[Optional[str], str]]:
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

        # Y a-t-il des bullets après la commande ?
        has_bullets = any(
            line.strip().startswith(("*", "-"))
            for line in bullets
        )

        # Si pas de bullets: interpréter la ligne de commande comme une seule tâche inline
        if not has_bullets:
            tokens = command_line.split()
            # On attend: "<@BOTID> tasks reste..."
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
            parsed_tasks.extend(parse_bullet_line(bullet_line))

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

        # Déterminer la tasklist Google pour ce channel
        tasklist_id: Optional[str] = None
        try:
            info = self.slack.conversations_info(channel=channel)
            ch = info.get("channel", {})
            channel_name = ch.get("name") or ch.get("id") or "Hex"
            tasklist_id = get_or_create_tasklist(channel_name)
        except Exception as exc:
            self.log.exception("Failed to get channel name, using default list: %s", exc)
            tasklist_id = None

        # Permalink Slack pour mettre dans les notes (optionnel)
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
            # Titre Google: nom lisible, pas l'ID Slack
            if assignee_id is not None:
                assignee_name = self._get_user_display_name(assignee_id)
                google_title = f"[{assignee_name}] {task_text}"
            else:
                google_title = f"[unassigned] {task_text}"

            notes = ""
            if permalink:
                notes = f"From Slack: {permalink}"

            try:
                create_task(
                    title=google_title,
                    notes=notes,
                    tasklist_id=tasklist_id,
                )
                created_count += 1
            except Exception as exc:
                self.log.exception("Failed to create Google Task for %r: %s", google_title, exc)

            # Affichage Slack: utiliser les mentions @ pour que Slack affiche les noms
            if assignee_id is not None:
                assignee_mention = f"<@{assignee_id}>"
            else:
                assignee_mention = "unassigned"

            summary_lines.append(
                f"{sender_mention} assigned the following task to {assignee_mention}: {task_text}"
            )

        header = f"Created {created_count} Google Tasks in my list:"
        text = header + "\n" + "\n".join(summary_lines)

        self.slack.chat_postMessage(
            channel=channel,
            text=text,
            thread_ts=ts,
        )