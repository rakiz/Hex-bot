import logging
from unittest.mock import MagicMock, patch

log = logging.getLogger("test")

CHANNEL = "C123"
USER = "U456"
TS = "1234567890.000"


def _slack():
    return MagicMock()


# ---------------------------------------------------------------------------
# RegisterCommand
# ---------------------------------------------------------------------------

def test_register_sends_ephemeral_with_url():
    from hex_bot.commands.register import RegisterCommand
    slack = _slack()
    with patch("hex_bot.commands.register.generate_oauth_url", return_value="https://oauth.url") as mock_url:
        RegisterCommand(slack_client=slack, logger=log).handle(
            channel=CHANNEL, user=USER, ts=TS, text_lines=[],
        )
    mock_url.assert_called_once_with(USER)
    slack.chat_postEphemeral.assert_called_once()
    text = slack.chat_postEphemeral.call_args[1]["text"]
    assert "https://oauth.url" in text
    assert "10 minutes" in text


# ---------------------------------------------------------------------------
# UnregisterCommand
# ---------------------------------------------------------------------------

def test_unregister_when_not_registered():
    from hex_bot.commands.unregister import UnregisterCommand
    slack = _slack()
    with patch("hex_bot.commands.unregister.get_user", return_value=None), \
         patch("hex_bot.commands.unregister.delete_user") as mock_delete:
        UnregisterCommand(slack_client=slack, logger=log).handle(
            channel=CHANNEL, user=USER, ts=TS, text_lines=[],
        )
    mock_delete.assert_not_called()
    text = slack.chat_postEphemeral.call_args[1]["text"]
    assert "not registered" in text


def test_unregister_when_registered():
    from hex_bot.commands.unregister import UnregisterCommand
    slack = _slack()
    with patch("hex_bot.commands.unregister.get_user", return_value={"_id": USER}), \
         patch("hex_bot.commands.unregister.delete_user") as mock_delete:
        UnregisterCommand(slack_client=slack, logger=log).handle(
            channel=CHANNEL, user=USER, ts=TS, text_lines=[],
        )
    mock_delete.assert_called_once_with(USER)
    text = slack.chat_postEphemeral.call_args[1]["text"]
    assert "disconnected" in text


# ---------------------------------------------------------------------------
# StatusCommand
# ---------------------------------------------------------------------------

def test_status_not_registered():
    from hex_bot.commands.status import StatusCommand
    slack = _slack()
    with patch("hex_bot.commands.status.get_user", return_value=None):
        StatusCommand(slack_client=slack, logger=log).handle(
            channel=CHANNEL, user=USER, ts=TS, text_lines=[],
        )
    text = slack.chat_postEphemeral.call_args[1]["text"]
    assert "not registered" in text
    assert "register" in text


def test_status_registered_default_tasklist():
    from hex_bot.commands.status import StatusCommand
    slack = _slack()
    with patch("hex_bot.commands.status.get_user", return_value={"_id": USER, "tasklist_name": None}):
        StatusCommand(slack_client=slack, logger=log).handle(
            channel=CHANNEL, user=USER, ts=TS, text_lines=[],
        )
    text = slack.chat_postEphemeral.call_args[1]["text"]
    assert "✅" in text
    assert "default" in text


def test_status_registered_custom_tasklist():
    from hex_bot.commands.status import StatusCommand
    slack = _slack()
    with patch("hex_bot.commands.status.get_user", return_value={"_id": USER, "tasklist_name": "My Tasks"}):
        StatusCommand(slack_client=slack, logger=log).handle(
            channel=CHANNEL, user=USER, ts=TS, text_lines=[],
        )
    text = slack.chat_postEphemeral.call_args[1]["text"]
    assert "My Tasks" in text
