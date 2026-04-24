from typing import Optional, Tuple

from .base import Command, register_command
from ..db import get_refresh_token, get_user
from ..google_tasks import find_tasklist, list_tasks, _MAX_LIST_TASKS


@register_command
class TasklistCommand(Command):
    """
    "@Hex tasklist [name] [--all] [--limit N] [--skip N]"

    Lists open tasks from a Google Tasks list and replies with an ephemeral message.

    Tasklist resolution order (first match wins):
      1. Explicit name argument — "@Hex tasklist my-list"
      2. User's configured default — set via "@Hex config tasklist <name>"
      3. Current Slack channel name — automatic, no configuration needed

    Pagination flags:
      --all       : return every open task (no limit)
      --limit N   : return at most N tasks (default: _MAX_LIST_TASKS)
      --skip N    : skip the first N results (for paging through a long list)

    Only the calling user's tasks are shown — each user has their own Google account.
    """

    name = "tasklist"
    description = "List open tasks from a Google Tasks list."
    usage = "@Hex tasklist [name] [all] [limit N] [skip N]"
    notes = (
        "<name> — tasklist to query (default: your configured tasklist, or the current channel name)\n"
        "all — return every open task (no cap)\n"
        "limit N — return at most N tasks (default: 20)\n"
        "skip N — skip the first N results, useful to page through a long list"
    )
    examples = [
        "@Hex tasklist",
        "@Hex tasklist my-project",
        "@Hex tasklist limit 5 skip 10",
        "@Hex tasklist all",
    ]

    def handle(self, *, channel, user, ts, thread_ts=None, text_lines):
        self.log.info("TasklistCommand: user=%s channel=%s", user, channel)
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

        # Parse "@Hex tasklist [--all] [--limit N] [--skip N] [name]"
        tokens = text_lines[0].split()[2:] if text_lines else []
        explicit_name, limit, skip = self._parse_flags(tokens)

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

        tasks = list_tasks(tasklist_id, refresh_token=refresh_token, limit=limit, skip=skip)
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
            title = task.get("title", "(no title)")
            due = task.get("due", "")
            due_label = f" _(due {due[:10]})_" if due else ""
            lines.append(f"• {title}{due_label}")

        # Tell the user if there may be more tasks not shown
        if limit is not None and len(tasks) == limit:
            next_skip = skip + limit
            lines.append(
                f"_(showing {skip + 1}–{next_skip}"
                f" — use `skip {next_skip}` for more, or `all` to see everything)_"
            )

        self.slack.chat_postEphemeral(
            channel=channel,
            user=user,
            text="\n".join(lines),
            thread_ts=thread_ts,
        )

    @staticmethod
    def _parse_flags(tokens: list) -> Tuple[Optional[str], Optional[int], int]:
        """
        Parse flags from the tokens after '@Hex tasklist'.
        Returns (explicit_name, limit, skip).
        --all  → limit=None (fetch everything)
        --limit N → limit=N
        --skip N  → skip=N
        Remaining non-flag tokens are joined as the tasklist name.
        """
        limit: Optional[int] = _MAX_LIST_TASKS
        skip = 0
        name_parts = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token == "all":
                limit = None
            elif token == "limit" and i + 1 < len(tokens):
                try:
                    limit = int(tokens[i + 1])
                    i += 1
                except ValueError:
                    pass
            elif token == "skip" and i + 1 < len(tokens):
                try:
                    skip = int(tokens[i + 1])
                    i += 1
                except ValueError:
                    pass
            else:
                name_parts.append(token)
            i += 1
        explicit_name = " ".join(name_parts).strip() or None
        return explicit_name, limit, skip

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
        except Exception as exc:
            self.log.warning("conversations_info failed in _resolve_tasklist_title: %s", exc)

        self.slack.chat_postEphemeral(
            channel=channel,
            user=user,
            text=(
                f"<@{user}> I can't determine which tasklist to show.\n"
                'Use `@Hex tasklist <name>` or set a default with `@Hex config tasklist <name>`.'
            ),
            thread_ts=thread_ts,
        )
        return None
