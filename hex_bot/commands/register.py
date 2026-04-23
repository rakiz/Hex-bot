from .base import Command, register_command
from ..oauth import generate_oauth_url, STATE_TTL_SECONDS


@register_command
class RegisterCommand(Command):
    name = "register"

    def handle(self, *, channel, user, ts, thread_ts=None, text_lines):
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
