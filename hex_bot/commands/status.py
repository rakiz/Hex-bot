from .base import Command, register_command
from ..db import get_user

# Displayed when tasklist_name is NULL in the DB, meaning "use the Slack channel name".
_DEFAULT_TASKLIST_LABEL = "channel name (default)"


@register_command
class StatusCommand(Command):
    name = "status"

    def handle(self, *, channel, user, ts, thread_ts=None, text_lines):
        record = get_user(user)
        if not record:
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

        tasklist = record.get("tasklist_name") or _DEFAULT_TASKLIST_LABEL
        self.slack.chat_postEphemeral(
            channel=channel,
            user=user,
            text=f"<@{user}> ✅ Registered. Tasklist: *{tasklist}*",
            thread_ts=thread_ts,
        )
