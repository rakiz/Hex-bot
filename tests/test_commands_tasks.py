import logging
from unittest.mock import MagicMock, patch

log = logging.getLogger("test")

CHANNEL = "C123"
USER = "U456"
TS = "1234567890.000"


def _make_slack():
    slack = MagicMock()
    slack.conversations_info.return_value = {"channel": {"name": "general"}}
    slack.chat_getPermalink.return_value = {"permalink": "https://slack.com/p"}
    slack.users_info.return_value = {
        "user": {"profile": {"display_name": "Alice"}, "name": "alice"}
    }
    return slack


def _run(text_lines, *, slack=None, refresh_token="tok", create_side_effect=None):
    """Run TasksCommand.handle with Slack + Google mocked."""
    from hex_bot.commands.tasks import TasksCommand

    if slack is None:
        slack = _make_slack()

    create_kwargs = (
        {"side_effect": create_side_effect}
        if create_side_effect
        else {"return_value": {"id": "T1"}}
    )

    with patch("hex_bot.commands.tasks.get_refresh_token", return_value=refresh_token), \
         patch("hex_bot.commands.tasks.get_or_create_tasklist", return_value="LIST1"), \
         patch("hex_bot.commands.tasks.create_task", **create_kwargs):
        cmd = TasksCommand(slack_client=slack, logger=log)
        cmd.handle(channel=CHANNEL, user=USER, ts=TS, text_lines=text_lines)

    return slack


# ---------------------------------------------------------------------------
# Registration guard
# ---------------------------------------------------------------------------

def test_not_registered_sends_ephemeral_no_task_created():
    slack = _make_slack()
    with patch("hex_bot.commands.tasks.get_refresh_token", return_value=None), \
         patch("hex_bot.commands.tasks.create_task") as mock_create:
        from hex_bot.commands.tasks import TasksCommand
        TasksCommand(slack_client=slack, logger=log).handle(
            channel=CHANNEL, user=USER, ts=TS,
            text_lines=["<@BOT> tasks <@U2> do thing"],
        )
    slack.chat_postEphemeral.assert_called_once()
    assert "register" in slack.chat_postEphemeral.call_args[1]["text"].lower()
    mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# Content parsing / usage message
# ---------------------------------------------------------------------------

def test_no_task_content_sends_usage():
    slack = _run(["<@BOT> tasks"])
    slack.chat_postMessage.assert_called_once()
    assert "@Hex tasks" in slack.chat_postMessage.call_args[1]["text"]


def test_unparseable_bullets_sends_error():
    # Bullets with no text after stripping mentions → nothing to create
    slack = _run(["<@BOT> tasks", "* <@U2>"])
    slack.chat_postMessage.assert_called_once()
    assert "couldn't parse" in slack.chat_postMessage.call_args[1]["text"]


# ---------------------------------------------------------------------------
# Task creation — success
# ---------------------------------------------------------------------------

def test_inline_task_success_reports_tick():
    slack = _run(["<@BOT> tasks <@U2> do thing"])
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "✓" in text
    assert "do thing" in text


def test_bullet_tasks_count_in_reply():
    slack = _run([
        "<@BOT> tasks",
        "* <@U2> first task",
        "* <@U3> second task",
    ])
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "Created 2" in text
    assert text.count("✓") == 2


def test_multi_mention_creates_one_task_per_person():
    slack = _run(["<@BOT> tasks", "* <@U2> <@U3> shared work"])
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "Created 2" in text


# ---------------------------------------------------------------------------
# Task creation — failure
# ---------------------------------------------------------------------------

def test_google_failure_reports_cross():
    slack = _run(
        ["<@BOT> tasks <@U2> do thing"],
        create_side_effect=Exception("Google down"),
    )
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "✗" in text
    assert "✓" not in text


def test_partial_failure_reports_both():
    call_count = 0

    def flaky(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise Exception("fail")
        return {"id": "T1"}

    slack = _run(
        ["<@BOT> tasks", "* <@U2> ok task", "* <@U3> bad task"],
        create_side_effect=flaky,
    )
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "✓" in text
    assert "✗" in text


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------

def test_eyes_reaction_added_then_removed():
    slack = _run(["<@BOT> tasks <@U2> do thing"])
    slack.reactions_add.assert_called_once_with(channel=CHANNEL, name="eyes", timestamp=TS)
    slack.reactions_remove.assert_called_once_with(channel=CHANNEL, name="eyes", timestamp=TS)
