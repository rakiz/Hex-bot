from typing import Optional, Type

from .base import Command, register_command, get_command, get_all_commands

# Shown when the user types "@Hex help <unknown>".
_UNKNOWN_CMD_MSG = 'Unknown command `{cmd}`. Type "@Hex help" for the list.'


@register_command
class HelpCommand(Command):
    """
    "@Hex help [command]"

    With no argument: posts an ephemeral with all registered commands and their
    one-line descriptions.

    With a command name: posts usage and examples for that specific command.
    If the name is not recognised, posts an error with a hint.

    Documentation is pulled directly from each command's class attributes
    (description, usage, examples) — no centralised help strings to maintain.
    """

    name = "help"
    description = "Show available commands, or usage and examples for one command."
    usage = "@Hex help [command]"
    examples = ["@Hex help", "@Hex help tasks", "@Hex help tasklist"]

    def handle(self, *, channel, user, ts, thread_ts=None, text_lines):
        # tokens[2:] strips "<@BOTID> help" from the front, leaving optional target
        tokens = text_lines[0].split()[2:] if text_lines else []
        target = tokens[0].lower() if tokens else None

        if target:
            cmd_cls = get_command(target)
            if not cmd_cls:
                self.slack.chat_postEphemeral(
                    channel=channel,
                    user=user,
                    text=_UNKNOWN_CMD_MSG.format(cmd=target),
                    thread_ts=thread_ts,
                )
                return
            self._send_detail(channel, user, thread_ts, cmd_cls)
        else:
            self._send_summary(channel, user, thread_ts)

    def _send_summary(self, channel: str, user: str, thread_ts: Optional[str]) -> None:
        lines = ["*Available commands:*"]
        for name, cls in sorted(get_all_commands().items()):
            lines.append(f"• `{name}` — {cls.description}")
        lines.append('\nType "@Hex help <command>" for usage and examples.')
        self.slack.chat_postEphemeral(
            channel=channel,
            user=user,
            text="\n".join(lines),
            thread_ts=thread_ts,
        )

    def _send_detail(self, channel: str, user: str, thread_ts: Optional[str], cmd_cls: Type[Command]) -> None:
        parts = [f"*{cmd_cls.name}* — {cmd_cls.description}"]
        if cmd_cls.usage:
            parts.append(f"\n*Usage:* `{cmd_cls.usage}`")
        if cmd_cls.notes:
            parts.append(cmd_cls.notes)
        if cmd_cls.examples:
            parts.append("\n*Examples:*")
            for ex in cmd_cls.examples:
                parts.append(f"```{ex}```")
        self.slack.chat_postEphemeral(
            channel=channel,
            user=user,
            text="\n".join(parts),
            thread_ts=thread_ts,
        )
