"""Conversation context management for Roland.

Maintains conversation history to enable contextual understanding
of commands like "do that again" or "repeat".
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from roland.llm.interpreter import Command
from roland.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ConversationTurn:
    """Represents a single turn in the conversation.

    Attributes:
        role: 'user' or 'assistant'.
        content: The text content.
        command: Associated command (for assistant turns).
        timestamp: When the turn occurred.
    """

    role: str
    content: str
    command: Optional[Command] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for LLM context.

        Returns:
            Dictionary representation.
        """
        return {
            "role": self.role,
            "content": self.content,
        }


class ContextManager:
    """Manages conversation context and history.

    Stores recent conversation turns to enable contextual
    understanding and command repetition.

    Attributes:
        max_turns: Maximum conversation turns to retain.
        history: Deque of conversation turns.
    """

    def __init__(self, max_turns: int = 10):
        """Initialize the context manager.

        Args:
            max_turns: Maximum number of turns to keep.
        """
        self.max_turns = max_turns
        self._history: deque[ConversationTurn] = deque(maxlen=max_turns * 2)
        self._last_command: Optional[Command] = None
        self._last_user_input: Optional[str] = None

    def add_user_input(self, text: str) -> None:
        """Add user input to history.

        Args:
            text: User's spoken text.
        """
        turn = ConversationTurn(role="user", content=text)
        self._history.append(turn)
        self._last_user_input = text
        logger.debug("context_added_user_input", text=text[:50])

    def add_response(self, response: str, command: Optional[Command] = None) -> None:
        """Add assistant response to history.

        Args:
            response: Roland's spoken response.
            command: Associated command if any.
        """
        turn = ConversationTurn(role="assistant", content=response, command=command)
        self._history.append(turn)
        if command:
            self._last_command = command
        logger.debug("context_added_response", response=response[:50])

    def add(self, user_input: str, command: Command) -> None:
        """Add a complete conversation exchange.

        Convenience method to add both user input and response.

        Args:
            user_input: User's spoken text.
            command: Executed command with response.
        """
        self.add_user_input(user_input)
        self.add_response(command.response, command)

    def get_history(self) -> list[dict]:
        """Get conversation history for LLM context.

        Returns:
            List of conversation turn dictionaries.
        """
        return [turn.to_dict() for turn in self._history]

    def get_recent_history(self, n: int = 5) -> list[dict]:
        """Get the N most recent conversation turns.

        Args:
            n: Number of turns to return.

        Returns:
            List of recent turn dictionaries.
        """
        recent = list(self._history)[-n:]
        return [turn.to_dict() for turn in recent]

    @property
    def last_command(self) -> Optional[Command]:
        """Get the last executed command."""
        return self._last_command

    @property
    def last_user_input(self) -> Optional[str]:
        """Get the last user input."""
        return self._last_user_input

    def is_repeat_request(self, text: str) -> bool:
        """Check if text is a request to repeat last action.

        Args:
            text: User input text.

        Returns:
            True if user wants to repeat last command.
        """
        text_lower = text.lower().strip()
        repeat_phrases = [
            "repeat",
            "do that again",
            "again",
            "same again",
            "one more time",
            "do it again",
            "repeat that",
            "same thing",
        ]
        return any(phrase in text_lower for phrase in repeat_phrases)

    def is_undo_request(self, text: str) -> bool:
        """Check if text is a request to undo last action.

        Args:
            text: User input text.

        Returns:
            True if user wants to undo last command.
        """
        text_lower = text.lower().strip()
        undo_phrases = [
            "undo",
            "undo that",
            "cancel",
            "cancel that",
            "never mind",
            "nevermind",
        ]
        return any(phrase in text_lower for phrase in undo_phrases)

    def get_last_keyboard_command(self) -> Optional[Command]:
        """Get the last command that involved keyboard input.

        Returns:
            Last keyboard command or None.
        """
        for turn in reversed(self._history):
            if turn.command and turn.command.is_keyboard_action:
                return turn.command
        return None

    def clear(self) -> None:
        """Clear all conversation history."""
        self._history.clear()
        self._last_command = None
        self._last_user_input = None
        logger.info("context_cleared")

    def get_summary(self) -> str:
        """Get a brief summary of recent context.

        Returns:
            Summary string.
        """
        if not self._history:
            return "No conversation history."

        recent = list(self._history)[-4:]
        lines = []
        for turn in recent:
            prefix = "You:" if turn.role == "user" else "Roland:"
            lines.append(f"{prefix} {turn.content[:50]}...")

        return "\n".join(lines)

    def __len__(self) -> int:
        """Get number of turns in history."""
        return len(self._history)

    def __bool__(self) -> bool:
        """Check if there's any history."""
        return len(self._history) > 0
