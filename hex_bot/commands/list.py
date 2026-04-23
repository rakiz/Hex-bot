from typing import Optional

from .base import Command, register_command
from ..db import get_refresh_token, get_user
from ..google_tasks import find_tasklist, list_tasks, _MAX_LIST_TASKS


@register_command
class ListCommand(Command):
    name = "list"

    def handle(self, *, channel, user, ts, thread_ts=None, text_lines):
        self.log.info("ListCommand: user=%s channel=%s", user, channel)
        refresh_token = get_refresh_token(user)
        if not refresh_token:
            self.slack.chat_postEphemeral(
                channel=channel,
                user=user,
                text=(
                    f"<@{user}> You are not registered.\n"
                    'Type "@Hex register" to connect your Google Tasks account.'
                ),
                thread_ts=thread_ts,
            )
            return

        # Parse optional explicit tasklist name: "@Hex list [name]"
        tokens = text_lines[0].split() if text_lines else []
        explicit_name = " ".join(tokens[2:]).strip() if len(tokens) >= 3 else None

        tasklist_title = self._resolve_tasklist_title(channel, user, thread_ts, explicit_name)
        if tasklist_title is None:
            return  # error already sent

        tasklist_id = find_tasklist(tasklist_title, refresh_token=refresh_token)
        if tasklist_id is None:
            self.log.warning("Tasklist %r not found for user=%s", tasklist_title, user)
            self.slack.chat_postEphemeral(
                channel=channel,
                user=user,
                text=f"<@{user}> No tasklist named *{tasklist_title}* found in your Google Tasks.",
                thread_ts=thread_ts,
            )
            return

        tasks = list_tasks(tasklist_id, refresh_token=refresh_token)
        if not tasks:
            self.slack.chat_postEphemeral(
                channel=channel,
                user=user,
                text=f"<@{user}> No open tasks in *{tasklist_title}*.",
                thread_ts=thread_ts,
            )
            return

        lines = [f"<@{user}> Open tasks in *{tasklist_title}*:"]
        for task in tasks:
            lines.append(f"• {task.get('title', '(no title)')}")
        # Equality (not >=): list_tasks caps maxResults at _MAX_LIST_TASKS, so Google
        # returns at most that many — hitting exactly the cap means there may be more.
        if len(tasks) == _MAX_LIST_TASKS:
            lines.append(f"_(showing first {_MAX_LIST_TASKS} tasks)_")

        self.slack.chat_postEphemeral(
            channel=channel,
            user=user,
            text="\n".join(lines),
            thread_ts=thread_ts,
        )

    def _resolve_tasklist_title(
        self,
        channel: str,
        user: str,
        thread_ts: Optional[str],
        explicit_name: Optional[str],
    ) -> Optional[str]:
        """
        Returns the tasklist title to query, or None if it can't be determined
        (in which case an error ephemeral has already been sent).

        Priority: explicit arg > configured tasklist_name > channel name.
        """
        if explicit_name:
            return explicit_name

        record = get_user(user)
        configured = record.get("tasklist_name") if record else None
        if configured:
            return configured

        # Fall back to the current channel name.
        # This fails in DMs since DMs have no name — caught in the except block.
        try:
            info = self.slack.conversations_info(channel=channel)
            ch = info.get("channel", {})
            name = ch.get("name") or ch.get("id")
            if name:
                return name
        except Exception:
            pass

        self.slack.chat_postEphemeral(
            channel=channel,
            user=user,
            text=(
                f"<@{user}> I can't determine which tasklist to show.\n"
                "Use `@Hex list <name>` or set a default with `@Hex config tasklist <name>`."
            ),
            thread_ts=thread_ts,
        )
        return None
