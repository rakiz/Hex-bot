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


def _run(text_lines, *, slack=None, tokens=None, create_side_effect=None):
    """
    Run TasksCommand.handle with Slack + Google mocked.

    tokens: dict mapping user_id -> token (or None = not registered).
            If omitted, every user is considered registered ("tok").
    """
    from hex_bot.commands.tasks import TasksCommand

    if slack is None:
        slack = _make_slack()

    def get_token(uid):
        if tokens is None:
            return "tok"  # everyone registered by default
        # Users present in the dict may be explicitly None (not registered);
        # users absent from the dict fall back to "tok" (registered).
        return tokens.get(uid, "tok")

    create_kwargs = (
        {"side_effect": create_side_effect}
        if create_side_effect
        else {"return_value": {"id": "T1"}}
    )

    with patch("hex_bot.commands.tasks.get_refresh_token", side_effect=get_token), \
         patch("hex_bot.commands.tasks.get_or_create_tasklist", return_value="LIST1"), \
         patch("hex_bot.commands.tasks.create_task", **create_kwargs):
        cmd = TasksCommand(slack_client=slack, logger=log)
        cmd.handle(channel=CHANNEL, user=USER, ts=TS, text_lines=text_lines)

    return slack


# ---------------------------------------------------------------------------
# Registration guard — now on the ASSIGNEE, not the sender
# ---------------------------------------------------------------------------

def test_unregistered_assignee_posts_public_failure_with_register_hint():
    # Only the assignee needs to be registered — the sender's registration is irrelevant.
    slack = _run(
        ["<@BOT> tasks <@U2> do thing"],
        tokens={"U2": None},
    )
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "U2" in text
    assert "register" in text.lower()
    slack.chat_postEphemeral.assert_not_called()


def test_sender_does_not_need_to_be_registered_for_assigned_task():
    # Sender (USER) is not registered; assignee (U2) is. Task must be created.
    slack = _run(
        ["<@BOT> tasks <@U2> do thing"],
        tokens={USER: None},  # sender unregistered, U2 gets "tok" (default)
    )
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "✓" in text


def test_line_without_mention_is_ignored():
    # Lines with no @mention (context, description, etc.) are silently skipped.
    # Only the line with @U2 should produce a task.
    slack = _run(["<@BOT> tasks", "• context text", "• <@U2> real task", "• more context"])
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "Created 1" in text


def test_mention_line_without_bullet_prefix_creates_task():
    # @mention lines work without * or • prefix — the bullet is optional.
    slack = _run(["<@BOT> tasks", "<@U2> do thing"])
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "✓" in text


def test_slack_bullet_character_detected_as_task_line():
    # Slack sends rich-text bullets as • (U+2022), not *.
    slack = _run(["<@BOT> tasks", "• <@U2> do thing"])
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "✓" in text


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
