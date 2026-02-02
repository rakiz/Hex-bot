from __future__ import annotations

import logging
from typing import List, Tuple, Optional

from slack_client import get_bot_user_id, slack
from commands.base import get_command
import commands  # noqa: F401  # ensure registration side effects run

log = logging.getLogger(__name__)

def _find_command_line(
    lines: List[str],
    bot_user_id: str,
) -> Tuple[Optional[str], Optional[int]]:
    """
    Find the first line that looks like '<@BOTID> subcommand'.

    Returns (subcommand, line_index) or (None, None) if not found.
    """
    bot_mention = f"<@{bot_user_id}>"

    for idx, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue

        tokens = line.split()
        if not tokens:
            continue

        # Expect the mention as the first token
        if tokens[0] != bot_mention:
            continue

        if len(tokens) < 2:
            # Mention with no subcommand
            return None, idx

        subcmd = tokens[1].lower()
        return subcmd, idx

    return None, None

def dispatch_app_mention(event: dict) -> None:
    """
    Entry point for all app_mention events.
    Decodes subcommand & delegates to the appropriate Command.
    """
    channel = event.get("channel")
    user = event.get("user")
    ts = event.get("ts")
    text = event.get("text", "")

    if not channel or not user or not ts:
        log.warning("app_mention missing fields: %s", event)
        return

    lines: List[str] = text.splitlines()
    if not lines:
        return

    bot_user_id = get_bot_user_id()
    subcmd, cmd_line_idx = _find_command_line(lines, bot_user_id)

    if cmd_line_idx is None:
        # We were mentioned but not in the "@Hex subcommand" pattern; ignore for now.
        return

    if not subcmd:
        _send_help_for_root(channel, user, ts)
        return

    cmd_cls = get_command(subcmd)
    if not cmd_cls:
        _send_unknown_command_help(channel, user, ts, subcmd)
        return

    # Pass only the slice starting from the command line
    relevant_lines = lines[cmd_line_idx:]

    cmd = cmd_cls(slack_client=slack, logger=log)
    cmd.handle(channel=channel, user=user, ts=ts, text_lines=relevant_lines)

def _send_help_for_root(channel: str, user: str, ts: str) -> None:
    slack.chat_postEphemeral(
        channel=channel,
        user=user,
        text=(
            "Hi, I am Hex.\n\n"
            "For now I know the following command:\n"
            "- `@Hex tasks`: convert a list of bullets into tasks.\n\n"
            "Example:\n"
            "@Hex tasks\n"
            "* @alice do this\n"
            "* @bob do that"
        ),
        thread_ts=ts,
    )

def _send_unknown_command_help(channel: str, user: str, ts: str, subcmd: str) -> None:
    slack.chat_postEphemeral(
        channel=channel,
        user=user,
        text=(
            f"Unknown command: `{subcmd}`.\n"
            "For now I only know:\n"
            "- `@Hex tasks`"
        ),
        thread_ts=ts,
    )