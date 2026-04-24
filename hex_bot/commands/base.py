from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Type, List, Optional

class Command(ABC):
    """
    Base interface for all Hex subcommands, e.g. "tasks", "help", etc.

    Subclasses set the class-level documentation attributes so that HelpCommand
    can build its output without any centralised knowledge of individual commands.
    """

    # Subcommand name as invoked from Slack, e.g. "@Hex tasks"
    name: str = ""
    # One-line description shown in "@Hex help" summary.
    description: str = ""
    # Short usage signature shown in "@Hex help <cmd>".
    usage: str = ""
    # Optional plain-text clarification shown below the usage line.
    notes: str = ""
    # Illustrative usage lines shown in "@Hex help <cmd>".
    examples: List[str] = []

    def __init__(self, *, slack_client, logger):
        self.slack = slack_client
        self.log = logger

    @abstractmethod
    def handle(
        self,
        *,
        channel: str,
        user: str,
        ts: str,
        thread_ts: Optional[str] = None,
        text_lines: List[str],
    ) -> None:
        """
        Execute the command.

        ts:        timestamp of the triggering message (used for reactions, permalinks).
        thread_ts: parent thread timestamp if the command was sent inside a thread,
                   None if it was a top-level message. Passed to chat_postEphemeral so
                   bot responses appear in the same context as the original command.
        text_lines: all lines of the Slack message (including the first one).
        """
        ...

# Command registry: populated at import time via @register_command.
# New commands self-register by decorating their class — the dispatcher
# never needs to be updated when a command is added.
_COMMANDS: Dict[str, Type[Command]] = {}

def register_command(cls: Type[Command]) -> Type[Command]:
    """Decorator to register a command class by its `name` attribute."""
    if not getattr(cls, "name", None):
        raise ValueError(f"Command class {cls.__name__} is missing 'name'")
    _COMMANDS[cls.name] = cls
    return cls

def get_command(name: str) -> Type[Command] | None:
    return _COMMANDS.get(name)


def get_all_commands() -> Dict[str, Type[Command]]:
    """Return a snapshot of the full command registry (name → class)."""
    return dict(_COMMANDS)