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
         patch("hex_bot.commands.tasks.create_task", **create_kwargs), \
         patch("hex_bot.commands.tasks.record_tasks"):
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


def test_mention_only_no_text_reports_failure():
    # * <@U2> with no task text → explicit failure, not silent drop
    slack = _run(["<@BOT> tasks", "* <@U2>"])
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "✗" in text
    assert "no task text" in text


def test_all_bullets_without_mention_sends_unparseable_error():
    # Lines with no @mention at all → parsed_tasks stays empty
    slack = _run(["<@BOT> tasks", "* fix this", "* fix that"])
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
# Due dates
# ---------------------------------------------------------------------------

def test_due_date_passed_to_create_task():
    from unittest.mock import call
    with patch("hex_bot.commands.tasks.get_refresh_token", return_value="tok"), \
         patch("hex_bot.commands.tasks.get_or_create_tasklist", return_value="L1"), \
         patch("hex_bot.commands.tasks.create_task", return_value={"id": "T1"}) as mock_create:
        from hex_bot.commands.tasks import TasksCommand
        slack = _make_slack()
        TasksCommand(slack_client=slack, logger=log).handle(
            channel=CHANNEL, user=USER, ts=TS,
            text_lines=["<@BOT> tasks", "* <@U2> fix bug by 2026-05-01"],
        )
    _, kwargs = mock_create.call_args
    assert kwargs["due"] == "2026-05-01T00:00:00.000Z"


def test_due_date_shown_in_success_reply():
    slack = _run(["<@BOT> tasks", "* <@U2> fix bug by 2026-05-01"])
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "2026-05-01" in text


def test_no_due_date_passes_none_to_create_task():
    with patch("hex_bot.commands.tasks.get_refresh_token", return_value="tok"), \
         patch("hex_bot.commands.tasks.get_or_create_tasklist", return_value="L1"), \
         patch("hex_bot.commands.tasks.create_task", return_value={"id": "T1"}) as mock_create:
        from hex_bot.commands.tasks import TasksCommand
        slack = _make_slack()
        TasksCommand(slack_client=slack, logger=log).handle(
            channel=CHANNEL, user=USER, ts=TS,
            text_lines=["<@BOT> tasks", "* <@U2> fix bug"],
        )
    _, kwargs = mock_create.call_args
    assert kwargs["due"] is None


# ---------------------------------------------------------------------------
# me: self-assignment
# ---------------------------------------------------------------------------

def test_me_inline_assigns_to_sender():
    slack = _run([f"<@BOT> tasks me fix the login bug"], tokens={USER: "tok"})
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "✓" in text
    assert f"<@{USER}>" in text


def test_me_with_unquoted_list_override_skips_conversations_info():
    slack = _run([f"<@BOT> tasks me:my-project fix the login bug"], tokens={USER: "tok"})
    slack.conversations_info.assert_not_called()
    with patch("hex_bot.commands.tasks.get_refresh_token", return_value="tok"), \
         patch("hex_bot.commands.tasks.get_or_create_tasklist", return_value="L1") as mock_gtl, \
         patch("hex_bot.commands.tasks.create_task", return_value={"id": "T1"}):
        from hex_bot.commands.tasks import TasksCommand
        s = _make_slack()
        TasksCommand(slack_client=s, logger=log).handle(
            channel=CHANNEL, user=USER, ts=TS,
            text_lines=[f"<@BOT> tasks me:my-project fix the login bug"],
        )
    mock_gtl.assert_called_once_with("my-project", refresh_token="tok")


def test_me_with_quoted_list_override():
    with patch("hex_bot.commands.tasks.get_refresh_token", return_value="tok"), \
         patch("hex_bot.commands.tasks.get_or_create_tasklist", return_value="L1") as mock_gtl, \
         patch("hex_bot.commands.tasks.create_task", return_value={"id": "T1"}):
        from hex_bot.commands.tasks import TasksCommand
        s = _make_slack()
        TasksCommand(slack_client=s, logger=log).handle(
            channel=CHANNEL, user=USER, ts=TS,
            text_lines=[f'<@BOT> tasks me:"my project 2026" fix bug'],
        )
    mock_gtl.assert_called_once_with("my project 2026", refresh_token="tok")


# ---------------------------------------------------------------------------
# _parse_me_prefix — unit tests for the parser
# ---------------------------------------------------------------------------

def test_parse_me_prefix_bare_me():
    from hex_bot.commands.tasks import _parse_me_prefix
    has_me, list_override, remaining = _parse_me_prefix("<@BOT> tasks me")
    assert has_me is True
    assert list_override is None
    assert remaining == ""


def test_parse_me_prefix_me_with_text():
    from hex_bot.commands.tasks import _parse_me_prefix
    has_me, list_override, remaining = _parse_me_prefix("<@BOT> tasks me fix the bug")
    assert has_me is True
    assert list_override is None
    assert remaining == "fix the bug"


def test_parse_me_prefix_unquoted_list():
    from hex_bot.commands.tasks import _parse_me_prefix
    has_me, list_override, remaining = _parse_me_prefix("<@BOT> tasks me:my-project fix the bug")
    assert has_me is True
    assert list_override == "my-project"
    assert remaining == "fix the bug"


def test_parse_me_prefix_quoted_list():
    from hex_bot.commands.tasks import _parse_me_prefix
    has_me, list_override, remaining = _parse_me_prefix('<@BOT> tasks me:"my project 2026" fix the bug')
    assert has_me is True
    assert list_override == "my project 2026"
    assert remaining == "fix the bug"


def test_parse_me_prefix_no_me():
    from hex_bot.commands.tasks import _parse_me_prefix
    has_me, list_override, remaining = _parse_me_prefix("<@BOT> tasks @U2 fix the bug")
    assert has_me is False


def test_parse_me_prefix_word_starting_with_me_is_not_matched():
    from hex_bot.commands.tasks import _parse_me_prefix
    has_me, _, _ = _parse_me_prefix("<@BOT> tasks meaningful work")
    assert has_me is False


# ---------------------------------------------------------------------------
# me: self-assignment — edge cases
# ---------------------------------------------------------------------------

def test_me_stray_mentions_in_text_are_ignored():
    # me is not compatible with other assignees — stray @mentions in the text are stripped
    slack = _run([f"<@BOT> tasks me fix @U2 the bug"], tokens={USER: "tok"})
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "Created 1" in text
    assert f"<@{USER}>" in text


def test_me_without_task_text_sends_usage():
    slack = _run([f"<@BOT> tasks me"])
    slack.chat_postMessage.assert_called_once()
    assert "@Hex tasks" in slack.chat_postMessage.call_args[1]["text"]


def test_me_with_list_override_but_no_task_text_sends_usage():
    slack = _run([f"<@BOT> tasks me:my-project"])
    slack.chat_postMessage.assert_called_once()
    assert "@Hex tasks" in slack.chat_postMessage.call_args[1]["text"]


def test_me_due_date_passed_to_create_task():
    with patch("hex_bot.commands.tasks.get_refresh_token", return_value="tok"), \
         patch("hex_bot.commands.tasks.get_or_create_tasklist", return_value="L1"), \
         patch("hex_bot.commands.tasks.create_task", return_value={"id": "T1"}) as mock_create:
        from hex_bot.commands.tasks import TasksCommand
        s = _make_slack()
        TasksCommand(slack_client=s, logger=log).handle(
            channel=CHANNEL, user=USER, ts=TS,
            text_lines=[f"<@BOT> tasks me fix bug by 2026-05-01"],
        )
    _, kwargs = mock_create.call_args
    assert kwargs["due"] == "2026-05-01T00:00:00.000Z"


def test_me_with_bullets_present_ignores_me_processes_bullets():
    # me is inline-only; if bullets are present, me on the command line is irrelevant
    slack = _run([
        f"<@BOT> tasks me",
        "* <@U2> review the PR",
    ], tokens={"U2": "tok"})
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "Created 1" in text
    assert "<@U2>" in text


def test_me_sender_not_registered_reports_failure():
    slack = _run([f"<@BOT> tasks me fix the bug"], tokens={USER: None})
    text = slack.chat_postMessage.call_args[1]["text"]
    assert "✗" in text
    assert "register" in text.lower()


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------

def test_eyes_reaction_added_then_removed():
    slack = _run(["<@BOT> tasks <@U2> do thing"])
    slack.reactions_add.assert_called_once_with(channel=CHANNEL, name="eyes", timestamp=TS)
    slack.reactions_remove.assert_called_once_with(channel=CHANNEL, name="eyes", timestamp=TS)


# ---------------------------------------------------------------------------
# Stats recording
# ---------------------------------------------------------------------------

def _run_with_stats(text_lines, *, tokens=None, create_side_effect=None):
    """Like _run but also patches record_tasks and returns (slack, mock_record)."""
    from hex_bot.commands.tasks import TasksCommand

    slack = _make_slack()

    def get_token(uid):
        if tokens is None:
            return "tok"
        return tokens.get(uid, "tok")

    create_kwargs = (
        {"side_effect": create_side_effect}
        if create_side_effect
        else {"return_value": {"id": "T1"}}
    )

    with patch("hex_bot.commands.tasks.get_refresh_token", side_effect=get_token), \
         patch("hex_bot.commands.tasks.get_or_create_tasklist", return_value="LIST1"), \
         patch("hex_bot.commands.tasks.create_task", **create_kwargs), \
         patch("hex_bot.commands.tasks.record_tasks") as mock_record:
        TasksCommand(slack_client=slack, logger=log).handle(
            channel=CHANNEL, user=USER, ts=TS, text_lines=text_lines,
        )

    return slack, mock_record


def test_stats_recorded_on_success():
    _, mock_record = _run_with_stats(["<@BOT> tasks <@U2> fix bug"])
    mock_record.assert_called_once()
    kw = mock_record.call_args[1]
    assert kw["sender_id"] == USER
    assert kw["successes"] == [{"assignee_id": "U2", "assignee_name": "Alice"}]
    assert kw["error_types"] == []


def test_stats_error_unregistered_assignee():
    _, mock_record = _run_with_stats(
        ["<@BOT> tasks <@U2> fix bug"],
        tokens={"U2": None},
    )
    mock_record.assert_called_once()
    kw = mock_record.call_args[1]
    assert kw["error_types"] == ["unregistered_assignee"]
    assert kw["successes"] == []


def test_stats_error_google_api_error():
    _, mock_record = _run_with_stats(
        ["<@BOT> tasks <@U2> fix bug"],
        create_side_effect=Exception("boom"),
    )
    mock_record.assert_called_once()
    kw = mock_record.call_args[1]
    assert "google_api_error" in kw["error_types"]
    assert kw["successes"] == []


def test_stats_mixed_success_and_error():
    call_count = 0

    def flaky(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise Exception("fail")
        return {"id": "T1"}

    _, mock_record = _run_with_stats(
        ["<@BOT> tasks", "* <@U2> ok task", "* <@U3> bad task"],
        create_side_effect=flaky,
    )
    mock_record.assert_called_once()
    kw = mock_record.call_args[1]
    assert len(kw["successes"]) == 1
    assert kw["error_types"] == ["google_api_error"]


def test_stats_not_recorded_when_no_tasks_parsed():
    _, mock_record = _run_with_stats(["<@BOT> tasks"])
    mock_record.assert_not_called()


def test_stats_no_task_text_recorded_as_error():
    _, mock_record = _run_with_stats(["<@BOT> tasks", "* <@U2>"])
    mock_record.assert_called_once()
    kw = mock_record.call_args[1]
    assert "no_task_text" in kw["error_types"]


def test_stats_error_google_refresh_error_on_create_task():
    from google.auth.exceptions import RefreshError
    _, mock_record = _run_with_stats(
        ["<@BOT> tasks <@U2> fix bug"],
        create_side_effect=RefreshError("token expired"),
    )
    mock_record.assert_called_once()
    kw = mock_record.call_args[1]
    assert "google_refresh_error" in kw["error_types"]
    assert kw["successes"] == []


def test_stats_error_google_refresh_error_on_get_tasklist():
    from google.auth.exceptions import RefreshError
    with patch("hex_bot.commands.tasks.get_refresh_token", return_value="tok"), \
         patch("hex_bot.commands.tasks.get_or_create_tasklist", side_effect=RefreshError("expired")), \
         patch("hex_bot.commands.tasks.record_tasks") as mock_record:
        from hex_bot.commands.tasks import TasksCommand
        TasksCommand(slack_client=_make_slack(), logger=log).handle(
            channel=CHANNEL, user=USER, ts=TS,
            text_lines=["<@BOT> tasks <@U2> fix bug"],
        )
    mock_record.assert_called_once()
    kw = mock_record.call_args[1]
    assert "google_refresh_error" in kw["error_types"]
