import pytest
from unittest.mock import patch
from hex_bot.commands.tasks import TasksCommand
from hex_bot.dispatcher import _find_command_line

BOT_ID = "UBOT123"
BOT_MENTION = f"<@{BOT_ID}>"

# Fixed reference date for due-date tests: Wednesday 2026-04-29
_TODAY = "2026-04-29"


class TestParseBulletLine:

    def test_bullet_with_single_mention(self):
        result = TasksCommand._parse_bullet_line("* <@UALICE> fix the bug")
        assert result == [("UALICE", "fix the bug", None)]

    def test_bullet_with_multiple_mentions_expands(self):
        result = TasksCommand._parse_bullet_line("* <@UALICE> <@UBOB> fix the bug")
        assert result == [("UALICE", "fix the bug", None), ("UBOB", "fix the bug", None)]

    def test_bullet_without_mention_is_ignored(self):
        # Lines without @mention are silently skipped — no assignee, no task.
        result = TasksCommand._parse_bullet_line("* fix the bug")
        assert result == []

    def test_dash_bullet(self):
        result = TasksCommand._parse_bullet_line("- <@UALICE> fix the bug")
        assert result == [("UALICE", "fix the bug", None)]

    def test_empty_line_returns_empty(self):
        assert TasksCommand._parse_bullet_line("") == []
        assert TasksCommand._parse_bullet_line("   ") == []

    def test_mention_only_no_task_text_returns_none_text(self):
        # Mention present but no text → caller must report as failure
        result = TasksCommand._parse_bullet_line("* <@UALICE>")
        assert result == [("UALICE", None, None)]

    def test_line_without_bullet_prefix(self):
        result = TasksCommand._parse_bullet_line("<@UALICE> fix the bug")
        assert result == [("UALICE", "fix the bug", None)]

    def test_task_text_is_stripped(self):
        result = TasksCommand._parse_bullet_line("*   <@UALICE>   do this   ")
        assert result == [("UALICE", "do this", None)]

    def test_mention_in_middle_cleans_gap(self):
        # Mention stripped from middle should not leave double spaces
        result = TasksCommand._parse_bullet_line("* please <@UALICE> review this")
        assert result == [("UALICE", "please review this", None)]

    # -----------------------------------------------------------------------
    # Due dates
    # -----------------------------------------------------------------------

    def test_due_date_iso_explicit(self):
        result = TasksCommand._parse_bullet_line("* <@UALICE> fix bug by 2026-05-01")
        assert result == [("UALICE", "fix bug", "2026-05-01T00:00:00.000Z")]

    def test_due_date_hash_syntax(self):
        result = TasksCommand._parse_bullet_line("* <@UALICE> fix bug #2026-05-01")
        assert result == [("UALICE", "fix bug", "2026-05-01T00:00:00.000Z")]

    def test_due_date_today(self):
        with patch("hex_bot.commands.tasks.date") as mock_date:
            mock_date.today.return_value = __import__("datetime").date(2026, 4, 29)
            mock_date.fromisoformat = __import__("datetime").date.fromisoformat
            result = TasksCommand._parse_bullet_line("* <@UALICE> fix bug by today")
        assert result == [("UALICE", "fix bug", "2026-04-29T00:00:00.000Z")]

    def test_due_date_tomorrow(self):
        with patch("hex_bot.commands.tasks.date") as mock_date:
            mock_date.today.return_value = __import__("datetime").date(2026, 4, 29)
            mock_date.fromisoformat = __import__("datetime").date.fromisoformat
            result = TasksCommand._parse_bullet_line("* <@UALICE> fix bug by tomorrow")
        assert result == [("UALICE", "fix bug", "2026-04-30T00:00:00.000Z")]

    def test_due_date_friday_from_wednesday(self):
        # Wednesday → next Friday = +2 days
        with patch("hex_bot.commands.tasks.date") as mock_date:
            mock_date.today.return_value = __import__("datetime").date(2026, 4, 29)  # Wednesday
            mock_date.fromisoformat = __import__("datetime").date.fromisoformat
            result = TasksCommand._parse_bullet_line("* <@UALICE> fix bug by Friday")
        assert result == [("UALICE", "fix bug", "2026-05-01T00:00:00.000Z")]

    def test_due_date_stripped_from_task_text(self):
        result = TasksCommand._parse_bullet_line("* <@UALICE> fix bug by 2026-05-01")
        _, task_text, _ = result[0]
        assert task_text == "fix bug"
        assert "by" not in task_text
        assert "2026" not in task_text

    def test_no_due_date_returns_none(self):
        result = TasksCommand._parse_bullet_line("* <@UALICE> fix the bug")
        _, _, due = result[0]
        assert due is None

    def test_slack_bullet_character(self):
        result = TasksCommand._parse_bullet_line("• <@UALICE> fix the bug")
        assert result == [("UALICE", "fix the bug", None)]


class TestFindCommandLine:

    def test_finds_simple_subcommand(self):
        lines = [f"{BOT_MENTION} tasks"]
        subcmd, idx = _find_command_line(lines, BOT_ID)
        assert subcmd == "tasks"
        assert idx == 0

    def test_subcommand_is_lowercased(self):
        lines = [f"{BOT_MENTION} TASKS"]
        subcmd, idx = _find_command_line(lines, BOT_ID)
        assert subcmd == "tasks"

    def test_mention_without_subcommand(self):
        lines = [BOT_MENTION]
        subcmd, idx = _find_command_line(lines, BOT_ID)
        assert subcmd is None
        assert idx == 0

    def test_mention_not_first_token_is_ignored(self):
        lines = [f"hey {BOT_MENTION} tasks"]
        subcmd, idx = _find_command_line(lines, BOT_ID)
        assert subcmd is None
        assert idx is None

    def test_no_mention_returns_none(self):
        lines = ["just a regular message"]
        subcmd, idx = _find_command_line(lines, BOT_ID)
        assert subcmd is None
        assert idx is None

    def test_finds_command_line_among_bullets(self):
        lines = [
            f"{BOT_MENTION} tasks",
            "* <@UALICE> do this",
            "* <@UBOB> do that",
        ]
        subcmd, idx = _find_command_line(lines, BOT_ID)
        assert subcmd == "tasks"
        assert idx == 0

    def test_empty_lines_are_skipped(self):
        lines = ["", "  ", f"{BOT_MENTION} tasks"]
        subcmd, idx = _find_command_line(lines, BOT_ID)
        assert subcmd == "tasks"
        assert idx == 2
