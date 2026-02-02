from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Type, List

class Command(ABC):
    """
    Base interface for all Hex subcommands, e.g. "tasks", "help", etc.
    """

    # Subcommand name as invoked from Slack, e.g. "@Hex tasks"
    name: str

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
        text_lines: List[str],
    ) -> None:
        """
        Execute the command.

        text_lines: all lines of the Slack message (including the first one).
        """
        ...

# Simple registry for commands
_COMMANDS: Dict[str, Type[Command]] = {}

def register_command(cls: Type[Command]) -> Type[Command]:
    """
    Decorator to register a command class by its `name` attribute.
    """
    if not getattr(cls, "name", None):
        raise ValueError(f"Command class {cls.__name__} is missing 'name'")
    _COMMANDS[cls.name] = cls
    return cls

def get_command(name: str) -> Type[Command] | None:
    return _COMMANDS.get(name)