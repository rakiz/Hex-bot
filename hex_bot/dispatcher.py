from __future__ import annotations

import logging
from typing import List, Tuple, Optional

from .slack_client import get_bot_user_id, slack
from .commands.base import get_command
from . import commands  # noqa: F401  # ensure registration side effects run

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
    Runs in a background thread — exceptions are logged, not re-raised.
    """
    try:
        _dispatch(event)
    except Exception:
        log.exception("Unhandled error during event dispatch: %s", event)


def _dispatch(event: dict) -> None:
    channel = event.get("channel")
    user = event.get("user")
    ts = event.get("ts")
    # thread_ts is set by Slack only when the command was sent inside an existing thread.
    # Passing it down lets commands post ephemerals in the same context as the command.
    thread_ts = event.get("thread_ts")
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
        return

    if not subcmd:
        _invoke_help(bot_user_id, channel, user, ts, thread_ts)
        return

    cmd_cls = get_command(subcmd)
    if not cmd_cls:
        _invoke_help(bot_user_id, channel, user, ts, thread_ts, subcmd)
        return

    # Pass from the command line itself (not cmd_line_idx+1): commands need
    # text_lines[0] to parse their own invocation (e.g. inline arguments on the
    # same line as "@Hex tasks").
    relevant_lines = lines[cmd_line_idx:]
    cmd = cmd_cls(slack_client=slack, logger=log)
    cmd.handle(channel=channel, user=user, ts=ts, thread_ts=thread_ts, text_lines=relevant_lines)

def _invoke_help(
    bot_user_id: str,
    channel: str,
    user: str,
    ts: str,
    thread_ts: Optional[str],
    target: Optional[str] = None,
) -> None:
    """
    Delegate to HelpCommand by synthesising a text_lines list.

    Used for two cases:
      - bare "@Hex" (no subcommand) → shows the command summary
      - "@Hex <unknown>" → HelpCommand recognises the unknown name and shows an error
    """
    help_cls = get_command("help")
    if help_cls is None:
        return  # shouldn't happen — help is always registered
    synthetic_line = f"<@{bot_user_id}> help" + (f" {target}" if target else "")
    help_cls(slack_client=slack, logger=log).handle(
        channel=channel,
        user=user,
        ts=ts,
        thread_ts=thread_ts,
        text_lines=[synthetic_line],
    )