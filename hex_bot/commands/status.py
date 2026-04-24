from .base import Command, register_command
from ..db import get_user

# Displayed when tasklist_name is NULL in the DB.
_DEFAULT_TASKLIST_LABEL = "channel name (default)"
# Slack DM channel IDs start with 'D' — no channel name available in that context.
_DM_TASKLIST_LABEL = "channel name (default — requires explicit name in DMs)"
# Slack channel ID prefix for direct messages.
_SLACK_DM_PREFIX = "D"


@register_command
class StatusCommand(Command):
    name = "status"
    description = "Show whether you are registered and which tasklist is configured."
    usage = "@Hex status"
    examples = ["@Hex status"]

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

        configured = record.get("tasklist_name")
        if configured:
            tasklist = configured
        elif channel.startswith(_SLACK_DM_PREFIX):
            tasklist = _DM_TASKLIST_LABEL
        else:
            tasklist = _DEFAULT_TASKLIST_LABEL
        self.slack.chat_postEphemeral(
            channel=channel,
            user=user,
            text=f"<@{user}> ✅ Registered. Tasklist: *{tasklist}*",
            thread_ts=thread_ts,
        )
