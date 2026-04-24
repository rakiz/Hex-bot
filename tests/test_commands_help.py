from unittest.mock import MagicMock

from hex_bot.commands.help import HelpCommand
from hex_bot.commands.base import get_command, get_all_commands

CHANNEL = "C123"
USER = "U456"
TS = "1234567890.000"
BOT_ID = "UBOT"


def _make_cmd():
    return HelpCommand(slack_client=MagicMock(), logger=MagicMock())


def _text(cmd):
    return cmd.slack.chat_postEphemeral.call_args[1]["text"]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_help_command_is_registered():
    assert get_command("help") is HelpCommand


# ---------------------------------------------------------------------------
# @Hex help  (no argument — summary)
# ---------------------------------------------------------------------------

def test_help_no_args_lists_all_commands():
    cmd = _make_cmd()
    cmd.handle(channel=CHANNEL, user=USER, ts=TS, text_lines=[f"<@{BOT_ID}> help"])
    text = _text(cmd)
    for name in get_all_commands():
        assert name in text


def test_help_no_args_includes_hint():
    cmd = _make_cmd()
    cmd.handle(channel=CHANNEL, user=USER, ts=TS, text_lines=[f"<@{BOT_ID}> help"])
    text = _text(cmd)
    assert "@Hex help <command>" in text


def test_help_no_args_is_ephemeral():
    cmd = _make_cmd()
    cmd.handle(channel=CHANNEL, user=USER, ts=TS, text_lines=[f"<@{BOT_ID}> help"])
    cmd.slack.chat_postEphemeral.assert_called_once()
    cmd.slack.chat_postMessage.assert_not_called()


# ---------------------------------------------------------------------------
# @Hex help tasks  (known command — detail)
# ---------------------------------------------------------------------------

def test_help_known_command_shows_description():
    cmd = _make_cmd()
    cmd.handle(channel=CHANNEL, user=USER, ts=TS, text_lines=[f"<@{BOT_ID}> help tasks"])
    text = _text(cmd)
    assert "tasks" in text
    assert "Create Google Tasks" in text


def test_help_known_command_shows_usage():
    cmd = _make_cmd()
    cmd.handle(channel=CHANNEL, user=USER, ts=TS, text_lines=[f"<@{BOT_ID}> help tasks"])
    text = _text(cmd)
    assert "Usage" in text
    assert "@Hex tasks" in text


def test_help_known_command_shows_examples():
    cmd = _make_cmd()
    cmd.handle(channel=CHANNEL, user=USER, ts=TS, text_lines=[f"<@{BOT_ID}> help tasks"])
    text = _text(cmd)
    assert "Examples" in text


def test_help_known_command_is_ephemeral():
    cmd = _make_cmd()
    cmd.handle(channel=CHANNEL, user=USER, ts=TS, text_lines=[f"<@{BOT_ID}> help tasks"])
    cmd.slack.chat_postEphemeral.assert_called_once()


# ---------------------------------------------------------------------------
# @Hex help <unknown>  (error)
# ---------------------------------------------------------------------------

def test_help_unknown_command_shows_error():
    cmd = _make_cmd()
    cmd.handle(channel=CHANNEL, user=USER, ts=TS, text_lines=[f"<@{BOT_ID}> help foobar"])
    text = _text(cmd)
    assert "foobar" in text
    assert "Unknown command" in text


def test_help_unknown_command_includes_hint():
    cmd = _make_cmd()
    cmd.handle(channel=CHANNEL, user=USER, ts=TS, text_lines=[f"<@{BOT_ID}> help foobar"])
    text = _text(cmd)
    assert "@Hex help" in text


# ---------------------------------------------------------------------------
# thread_ts propagation
# ---------------------------------------------------------------------------

def test_help_passes_thread_ts():
    cmd = _make_cmd()
    cmd.handle(channel=CHANNEL, user=USER, ts=TS, thread_ts="999.000",
               text_lines=[f"<@{BOT_ID}> help"])
    assert cmd.slack.chat_postEphemeral.call_args[1]["thread_ts"] == "999.000"
