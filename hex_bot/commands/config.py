from typing import Optional

from .base import Command, register_command
from ..db import get_user, set_tasklist_name

# Keyword to reset the tasklist to the default (channel name) behaviour.
_RESET_KEYWORD = "default"


@register_command
class ConfigCommand(Command):
    name = "config"

    def handle(self, *, channel, user, ts, thread_ts=None, text_lines):
        # Expected: "@Hex config tasklist <name>" or "@Hex config tasklist default"
        tokens = text_lines[0].split() if text_lines else []

        if len(tokens) < 3 or tokens[2].lower() != "tasklist":
            self._send_usage(channel, user, thread_ts)
            return

        if not get_user(user):
            self.slack.chat_postEphemeral(
                channel=channel,
                user=user,
                text=f'<@{user}> You are not registered. Type "@Hex register" first.',
                thread_ts=thread_ts,
            )
            return

        name_arg = " ".join(tokens[3:]).strip() if len(tokens) >= 4 else ""
        if not name_arg:
            self._send_usage(channel, user, thread_ts)
            return

        if name_arg.lower() == _RESET_KEYWORD:
            set_tasklist_name(user, None)
            self.log.info("ConfigCommand: user=%s tasklist reset to default", user)
            self.slack.chat_postEphemeral(
                channel=channel,
                user=user,
                text=f"<@{user}> Tasklist reset to default (channel name).",
                thread_ts=thread_ts,
            )
        else:
            set_tasklist_name(user, name_arg)
            self.log.info("ConfigCommand: user=%s tasklist set to %r", user, name_arg)
            self.slack.chat_postEphemeral(
                channel=channel,
                user=user,
                text=f"<@{user}> Tasklist set to *{name_arg}* for all channels.",
                thread_ts=thread_ts,
            )

    def _send_usage(self, channel: str, user: str, thread_ts: Optional[str]) -> None:
        self.slack.chat_postEphemeral(
            channel=channel,
            user=user,
            text=(
                f"<@{user}> Usage:\n"
                "`@Hex config tasklist <name>` — use a fixed tasklist for all channels.\n"
                f"`@Hex config tasklist {_RESET_KEYWORD}` — revert to channel name (default)."
            ),
            thread_ts=thread_ts,
        )
