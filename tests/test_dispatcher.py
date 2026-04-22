import logging
from unittest.mock import MagicMock, patch

import hex_bot.dispatcher as disp

CHANNEL = "C123"
USER = "U456"
TS = "1234567890.000"


# ---------------------------------------------------------------------------
# _send_help_for_root
# ---------------------------------------------------------------------------

def test_help_lists_all_commands():
    mock_slack = MagicMock()
    with patch.object(disp, "slack", mock_slack):
        disp._send_help_for_root(CHANNEL, USER, TS)
    text = mock_slack.chat_postEphemeral.call_args[1]["text"]
    for cmd in ["register", "unregister", "status", "tasks"]:
        assert cmd in text


def test_help_shows_tasks_example():
    mock_slack = MagicMock()
    with patch.object(disp, "slack", mock_slack):
        disp._send_help_for_root(CHANNEL, USER, TS)
    text = mock_slack.chat_postEphemeral.call_args[1]["text"]
    assert "@Hex tasks" in text


# ---------------------------------------------------------------------------
# _send_unknown_command_help
# ---------------------------------------------------------------------------

def test_unknown_command_includes_subcmd_name():
    mock_slack = MagicMock()
    with patch.object(disp, "slack", mock_slack):
        disp._send_unknown_command_help(CHANNEL, USER, TS, "foobar")
    text = mock_slack.chat_postEphemeral.call_args[1]["text"]
    assert "foobar" in text


def test_unknown_command_lists_available_commands():
    mock_slack = MagicMock()
    with patch.object(disp, "slack", mock_slack):
        disp._send_unknown_command_help(CHANNEL, USER, TS, "foobar")
    text = mock_slack.chat_postEphemeral.call_args[1]["text"]
    for cmd in ["register", "unregister", "status", "tasks"]:
        assert cmd in text


# ---------------------------------------------------------------------------
# dispatch_app_mention — exception safety
# ---------------------------------------------------------------------------

def test_dispatch_app_mention_does_not_propagate_exceptions():
    with patch.object(disp, "_dispatch", side_effect=RuntimeError("boom")):
        # Must not raise — exceptions are caught and logged
        disp.dispatch_app_mention({"channel": CHANNEL, "user": USER, "ts": TS, "text": "hi"})
