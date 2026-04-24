from .base import Command, register_command
from ..db import get_refresh_token
from ..oauth import generate_oauth_url, STATE_TTL_SECONDS


@register_command
class RegisterCommand(Command):
    name = "register"
    description = "Connect your Google Tasks account via OAuth."
    usage = "@Hex register"
    notes = "You'll receive a private link (visible only to you). Click it, sign in to Google, and approve access to Google Tasks. The link expires after 10 minutes."
    examples = ["@Hex register"]

    def handle(self, *, channel, user, ts, thread_ts=None, text_lines):
        # Prevent silent token overwrite: if already registered, tell the user to
        # unregister first so the action is always intentional.
        if get_refresh_token(user):
            self.slack.chat_postEphemeral(
                channel=channel,
                user=user,
                text=(
                    f"<@{user}> You are already registered.\n"
                    'To switch Google accounts, type "@Hex unregister" first, then register again.'
                ),
                thread_ts=thread_ts,
            )
            return

        self.log.info("RegisterCommand: user=%s initiated OAuth", user)
        url = generate_oauth_url(user)
        ttl_minutes = STATE_TTL_SECONDS // 60
        # Ephemeral: the OAuth URL is personal and must not be visible to others in the channel.
        self.slack.chat_postEphemeral(
            channel=channel,
            user=user,
            text=(
                f"<@{user}> Click the link below to connect your Google Tasks account:\n"
                f"{url}\n\n"
                f"_This link expires in {ttl_minutes} minutes._"
            ),
            thread_ts=thread_ts,
        )
