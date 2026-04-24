import logging
from unittest.mock import MagicMock, patch

import hex_bot.dispatcher as disp

CHANNEL = "C123"
USER = "U456"
TS = "1234567890.000"
BOT_ID = "UBOT"


# ---------------------------------------------------------------------------
# _invoke_help — bare "@Hex" and unknown command both route through HelpCommand
# ---------------------------------------------------------------------------

def test_bare_mention_shows_help_summary():
    mock_slack = MagicMock()
    with patch.object(disp, "slack", mock_slack), \
         patch("hex_bot.dispatcher.get_bot_user_id", return_value=BOT_ID):
        disp._invoke_help(BOT_ID, CHANNEL, USER, TS, None)
    text = mock_slack.chat_postEphemeral.call_args[1]["text"]
    # Summary lists all commands
    for cmd in ["register", "unregister", "status", "tasks", "tasklist", "config", "help"]:
        assert cmd in text


def test_unknown_command_includes_subcmd_name():
    mock_slack = MagicMock()
    with patch.object(disp, "slack", mock_slack), \
         patch("hex_bot.dispatcher.get_bot_user_id", return_value=BOT_ID):
        disp._invoke_help(BOT_ID, CHANNEL, USER, TS, None, target="foobar")
    text = mock_slack.chat_postEphemeral.call_args[1]["text"]
    assert "foobar" in text


# ---------------------------------------------------------------------------
# dispatch_app_mention — exception safety
# ---------------------------------------------------------------------------

def test_dispatch_app_mention_does_not_propagate_exceptions():
    with patch.object(disp, "_dispatch", side_effect=RuntimeError("boom")):
        # Must not raise — exceptions are caught and logged
        disp.dispatch_app_mention({"channel": CHANNEL, "user": USER, "ts": TS, "text": "hi"})
