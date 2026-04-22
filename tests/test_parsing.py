import pytest
from hex_bot.commands.tasks import TasksCommand
from hex_bot.dispatcher import _find_command_line

BOT_ID = "UBOT123"
BOT_MENTION = f"<@{BOT_ID}>"


class TestParseBulletLine:

    def test_bullet_with_single_mention(self):
        result = TasksCommand._parse_bullet_line("* <@UALICE> fix the bug")
        assert result == [("UALICE", "fix the bug")]

    def test_bullet_with_multiple_mentions_expands(self):
        result = TasksCommand._parse_bullet_line("* <@UALICE> <@UBOB> fix the bug")
        assert result == [("UALICE", "fix the bug"), ("UBOB", "fix the bug")]

    def test_bullet_without_mention_is_unassigned(self):
        result = TasksCommand._parse_bullet_line("* fix the bug")
        assert result == [(None, "fix the bug")]

    def test_dash_bullet(self):
        result = TasksCommand._parse_bullet_line("- <@UALICE> fix the bug")
        assert result == [("UALICE", "fix the bug")]

    def test_empty_line_returns_empty(self):
        assert TasksCommand._parse_bullet_line("") == []
        assert TasksCommand._parse_bullet_line("   ") == []

    def test_mention_only_no_task_text_returns_empty(self):
        assert TasksCommand._parse_bullet_line("* <@UALICE>") == []

    def test_line_without_bullet_prefix(self):
        result = TasksCommand._parse_bullet_line("<@UALICE> fix the bug")
        assert result == [("UALICE", "fix the bug")]

    def test_task_text_is_stripped(self):
        result = TasksCommand._parse_bullet_line("*   <@UALICE>   do this   ")
        assert result == [("UALICE", "do this")]


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
