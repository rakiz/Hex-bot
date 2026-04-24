from .base import Command, register_command
from ..db import get_user, delete_user


@register_command
class UnregisterCommand(Command):
    name = "unregister"
    description = "Disconnect your Google Tasks account from Hex."
    usage = "@Hex unregister"
    notes = "Removes your stored credentials. Hex will no longer be able to create tasks in your Google account. Your existing tasks in Google Tasks are not affected."
    examples = ["@Hex unregister"]

    def handle(self, *, channel, user, ts, thread_ts=None, text_lines):
        if not get_user(user):
            self.slack.chat_postEphemeral(
                channel=channel,
                user=user,
                text=f"<@{user}> You are not registered — nothing to remove.",
                thread_ts=thread_ts,
            )
            return

        delete_user(user)
        self.log.info("UnregisterCommand: user=%s removed", user)
        self.slack.chat_postEphemeral(
            channel=channel,
            user=user,
            text=f"<@{user}> Your Google Tasks account has been disconnected from Hex.",
            thread_ts=thread_ts,
        )
