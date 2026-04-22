import logging
from unittest.mock import MagicMock, patch

log = logging.getLogger("test")

CHANNEL = "C123"
USER = "U456"
TS = "1234567890.000"


def _slack(channel_name="general"):
    slack = MagicMock()
    slack.conversations_info.return_value = {"channel": {"name": channel_name}}
    return slack


# ---------------------------------------------------------------------------
# ListCommand
# ---------------------------------------------------------------------------

class TestListCommand:

    def _run(self, text_lines, *, slack=None, refresh_token="tok",
             user_record=None, tasklist_id="L1", tasks=None):
        from hex_bot.commands.list import ListCommand
        if slack is None:
            slack = _slack()
        with patch("hex_bot.commands.list.get_refresh_token", return_value=refresh_token), \
             patch("hex_bot.commands.list.get_user", return_value=user_record or {"_id": USER, "tasklist_name": None}), \
             patch("hex_bot.commands.list.find_tasklist", return_value=tasklist_id), \
             patch("hex_bot.commands.list.list_tasks", return_value=tasks or []):
            cmd = ListCommand(slack_client=slack, logger=log)
            cmd.handle(channel=CHANNEL, user=USER, ts=TS, text_lines=text_lines)
        return slack

    def test_not_registered_sends_ephemeral(self):
        slack = self._run(["<@BOT> list"], refresh_token=None)
        text = slack.chat_postEphemeral.call_args[1]["text"]
        assert "register" in text.lower()

    def test_uses_explicit_name_from_args(self):
        from hex_bot.commands.list import ListCommand
        slack = _slack()
        with patch("hex_bot.commands.list.get_refresh_token", return_value="tok"), \
             patch("hex_bot.commands.list.get_user", return_value={"_id": USER, "tasklist_name": None}), \
             patch("hex_bot.commands.list.find_tasklist", return_value="L1") as mock_find, \
             patch("hex_bot.commands.list.list_tasks", return_value=[{"title": "task"}]):
            ListCommand(slack_client=slack, logger=log).handle(
                channel=CHANNEL, user=USER, ts=TS,
                text_lines=["<@BOT> list my-tasks"],
            )
        mock_find.assert_called_once_with("my-tasks", refresh_token="tok")

    def test_uses_configured_tasklist_name(self):
        from hex_bot.commands.list import ListCommand
        slack = _slack()
        with patch("hex_bot.commands.list.get_refresh_token", return_value="tok"), \
             patch("hex_bot.commands.list.get_user", return_value={"_id": USER, "tasklist_name": "My Tasks"}), \
             patch("hex_bot.commands.list.find_tasklist", return_value="L1") as mock_find, \
             patch("hex_bot.commands.list.list_tasks", return_value=[{"title": "task"}]):
            ListCommand(slack_client=slack, logger=log).handle(
                channel=CHANNEL, user=USER, ts=TS,
                text_lines=["<@BOT> list"],
            )
        mock_find.assert_called_once_with("My Tasks", refresh_token="tok")

    def test_falls_back_to_channel_name(self):
        from hex_bot.commands.list import ListCommand
        slack = _slack(channel_name="general")
        with patch("hex_bot.commands.list.get_refresh_token", return_value="tok"), \
             patch("hex_bot.commands.list.get_user", return_value={"_id": USER, "tasklist_name": None}), \
             patch("hex_bot.commands.list.find_tasklist", return_value="L1") as mock_find, \
             patch("hex_bot.commands.list.list_tasks", return_value=[{"title": "task"}]):
            ListCommand(slack_client=slack, logger=log).handle(
                channel=CHANNEL, user=USER, ts=TS,
                text_lines=["<@BOT> list"],
            )
        mock_find.assert_called_once_with("general", refresh_token="tok")

    def test_dm_without_config_sends_error(self):
        from hex_bot.commands.list import ListCommand
        slack = MagicMock()
        slack.conversations_info.side_effect = Exception("no channel name in DM")
        with patch("hex_bot.commands.list.get_refresh_token", return_value="tok"), \
             patch("hex_bot.commands.list.get_user", return_value={"_id": USER, "tasklist_name": None}):
            ListCommand(slack_client=slack, logger=log).handle(
                channel=USER, user=USER, ts=TS,
                text_lines=["<@BOT> list"],
            )
        text = slack.chat_postEphemeral.call_args[1]["text"]
        assert "config tasklist" in text

    def test_tasklist_not_found_sends_error(self):
        slack = self._run(["<@BOT> list"], tasklist_id=None)
        text = slack.chat_postEphemeral.call_args[1]["text"]
        assert "No tasklist" in text

    def test_empty_tasklist_sends_message(self):
        slack = self._run(["<@BOT> list"], tasks=[])
        text = slack.chat_postEphemeral.call_args[1]["text"]
        assert "No open tasks" in text

    def test_tasks_listed_in_reply(self):
        tasks = [{"title": "Buy milk"}, {"title": "Write tests"}]
        slack = self._run(["<@BOT> list"], tasks=tasks)
        text = slack.chat_postEphemeral.call_args[1]["text"]
        assert "Buy milk" in text
        assert "Write tests" in text

    def test_max_tasks_note_shown(self):
        from hex_bot.google_tasks import _MAX_LIST_TASKS
        tasks = [{"title": f"task {i}"} for i in range(_MAX_LIST_TASKS)]
        slack = self._run(["<@BOT> list"], tasks=tasks)
        text = slack.chat_postEphemeral.call_args[1]["text"]
        assert "first" in text  # truncation note


# ---------------------------------------------------------------------------
# ConfigCommand
# ---------------------------------------------------------------------------

class TestConfigCommand:

    _DEFAULT_USER = {"_id": USER}

    def _run(self, text_lines, *, user_record=_DEFAULT_USER):
        from hex_bot.commands.config import ConfigCommand
        slack = MagicMock()
        with patch("hex_bot.commands.config.get_user", return_value=user_record), \
             patch("hex_bot.commands.config.set_tasklist_name") as mock_set:
            ConfigCommand(slack_client=slack, logger=log).handle(
                channel=CHANNEL, user=USER, ts=TS, text_lines=text_lines,
            )
        return slack, mock_set

    def test_missing_subcommand_sends_usage(self):
        slack, _ = self._run(["<@BOT> config"])
        text = slack.chat_postEphemeral.call_args[1]["text"]
        assert "tasklist" in text

    def test_wrong_subcommand_sends_usage(self):
        slack, _ = self._run(["<@BOT> config something"])
        text = slack.chat_postEphemeral.call_args[1]["text"]
        assert "tasklist" in text

    def test_not_registered_sends_error(self):
        slack, mock_set = self._run(["<@BOT> config tasklist My Tasks"], user_record=None)
        text = slack.chat_postEphemeral.call_args[1]["text"]
        assert "register" in text.lower()
        mock_set.assert_not_called()

    def test_set_custom_tasklist(self):
        slack, mock_set = self._run(["<@BOT> config tasklist My Tasks"])
        mock_set.assert_called_once_with(USER, "My Tasks")
        text = slack.chat_postEphemeral.call_args[1]["text"]
        assert "My Tasks" in text

    def test_reset_to_default(self):
        slack, mock_set = self._run(["<@BOT> config tasklist default"])
        mock_set.assert_called_once_with(USER, None)
        text = slack.chat_postEphemeral.call_args[1]["text"]
        assert "default" in text.lower()

    def test_tasklist_name_missing_sends_usage(self):
        slack, mock_set = self._run(["<@BOT> config tasklist"])
        text = slack.chat_postEphemeral.call_args[1]["text"]
        assert "Usage" in text
        mock_set.assert_not_called()
