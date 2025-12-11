"""Command interpretation for Roland.

Parses LLM responses into executable commands and handles
command validation and routing.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from roland.keyboard.executor import KeyAction
from roland.utils.logger import get_logger

logger = get_logger(__name__)


class CommandType(str, Enum):
    """Types of commands Roland can execute."""

    PRESS_KEY = "press_key"
    HOLD_KEY = "hold_key"
    KEY_COMBO = "key_combo"
    CREATE_MACRO = "create_macro"
    DELETE_MACRO = "delete_macro"
    LIST_MACROS = "list_macros"
    SPEAK_ONLY = "speak_only"
    UNKNOWN = "unknown"


@dataclass
class Command:
    """Represents a parsed command.

    Attributes:
        type: Command type.
        keys: List of keys for keyboard actions.
        duration: Duration for hold actions.
        response: Text response for TTS.
        macro_name: Name for macro operations.
        trigger_phrase: Trigger phrase for macro creation.
        macro_keys: Keys for macro creation.
        macro_action_type: Action type for macro.
        raw: Original command dictionary.
    """

    type: CommandType
    keys: list[str]
    duration: float
    response: str
    macro_name: Optional[str] = None
    trigger_phrase: Optional[str] = None
    macro_keys: Optional[list[str]] = None
    macro_action_type: Optional[str] = None
    raw: Optional[dict] = None

    @property
    def is_keyboard_action(self) -> bool:
        """Check if command involves keyboard input."""
        return self.type in (
            CommandType.PRESS_KEY,
            CommandType.HOLD_KEY,
            CommandType.KEY_COMBO,
        )

    @property
    def is_macro_action(self) -> bool:
        """Check if command involves macro operations."""
        return self.type in (
            CommandType.CREATE_MACRO,
            CommandType.DELETE_MACRO,
            CommandType.LIST_MACROS,
        )

    @property
    def key_action(self) -> KeyAction:
        """Convert command type to KeyAction."""
        mapping = {
            CommandType.PRESS_KEY: KeyAction.PRESS,
            CommandType.HOLD_KEY: KeyAction.HOLD,
            CommandType.KEY_COMBO: KeyAction.COMBO,
        }
        return mapping.get(self.type, KeyAction.PRESS)


class CommandInterpreter:
    """Interprets and validates LLM command responses.

    Parses raw LLM output into structured Command objects,
    validates keys and parameters, and handles edge cases.

    Attributes:
        allowed_keys: Set of allowed key names.
        max_duration: Maximum allowed hold duration.
    """

    # Keys that are allowed to be pressed
    ALLOWED_KEYS = {
        # Letters
        *"abcdefghijklmnopqrstuvwxyz",
        # Numbers
        *"0123456789",
        # Function keys
        "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
        # Modifiers
        "ctrl", "alt", "shift", "ctrl_l", "ctrl_r", "alt_l", "alt_r", "shift_l", "shift_r",
        # Special keys
        "space", "enter", "tab", "esc", "backspace", "delete",
        "up", "down", "left", "right",
        "home", "end", "page_up", "page_down", "insert",
        # Punctuation (common in gaming)
        "[", "]", "'", "\\", ",", ".", "/", ";", "-", "=", "`",
    }

    def __init__(self, max_duration: float = 5.0):
        """Initialize the interpreter.

        Args:
            max_duration: Maximum allowed hold duration in seconds.
        """
        self.max_duration = max_duration

    def parse(self, response: dict) -> Command:
        """Parse LLM response dictionary into Command.

        Args:
            response: Dictionary from LLM response.

        Returns:
            Parsed Command object.
        """
        action = response.get("action", "").lower()

        # Determine command type
        try:
            cmd_type = CommandType(action)
        except ValueError:
            logger.warning("unknown_action_type", action=action)
            cmd_type = CommandType.UNKNOWN

        # Extract common fields
        keys = self._normalize_keys(response.get("keys", []))
        duration = self._validate_duration(response.get("duration", 0.0))
        text_response = response.get("response", "Acknowledged, Commander.")

        # Build command based on type
        command = Command(
            type=cmd_type,
            keys=keys,
            duration=duration,
            response=text_response,
            raw=response,
        )

        # Add macro-specific fields
        if cmd_type == CommandType.CREATE_MACRO:
            command.macro_name = response.get("macro_name", "").strip().lower()
            command.trigger_phrase = response.get("trigger_phrase", command.macro_name)
            command.macro_keys = self._normalize_keys(response.get("macro_keys", []))
            command.macro_action_type = response.get("macro_action_type", "press_key")

        elif cmd_type == CommandType.DELETE_MACRO:
            command.macro_name = response.get("macro_name", "").strip().lower()

        # Validate keyboard actions
        if command.is_keyboard_action:
            self._validate_keyboard_command(command)

        logger.info(
            "command_parsed",
            type=cmd_type.value,
            keys=keys if keys else None,
            has_response=bool(text_response),
        )

        return command

    def _normalize_keys(self, keys) -> list[str]:
        """Normalize key list to lowercase strings.

        Args:
            keys: Keys as list or single value.

        Returns:
            List of normalized key strings.
        """
        if not keys:
            return []

        if isinstance(keys, str):
            keys = [keys]

        normalized = []
        for key in keys:
            key_str = str(key).lower().strip()
            if key_str:
                normalized.append(key_str)

        return normalized

    def _validate_duration(self, duration) -> float:
        """Validate and clamp duration value.

        Args:
            duration: Duration value to validate.

        Returns:
            Validated duration in seconds.
        """
        try:
            dur = float(duration)
        except (TypeError, ValueError):
            return 0.0

        # Clamp to valid range
        if dur < 0:
            return 0.0
        if dur > self.max_duration:
            logger.warning("duration_clamped", original=dur, max=self.max_duration)
            return self.max_duration

        return dur

    def _validate_keyboard_command(self, command: Command) -> None:
        """Validate keyboard command keys.

        Args:
            command: Command to validate.

        Raises:
            ValueError: If keys are invalid.
        """
        if not command.keys:
            logger.warning("keyboard_command_no_keys", type=command.type.value)
            return

        invalid_keys = []
        for key in command.keys:
            if key not in self.ALLOWED_KEYS:
                invalid_keys.append(key)

        if invalid_keys:
            logger.warning("invalid_keys_detected", keys=invalid_keys)
            # Remove invalid keys
            command.keys = [k for k in command.keys if k not in invalid_keys]

    def interpret_macro_command(self, text: str) -> Optional[dict]:
        """Try to interpret text as a macro creation command.

        Looks for patterns like "when I say X, press Y" without
        going through the LLM.

        Args:
            text: User input text.

        Returns:
            Macro command dict or None if not a macro command.
        """
        text_lower = text.lower()

        # Patterns that indicate macro creation
        patterns = [
            ("when i say", "press"),
            ("if i say", "press"),
            ("create macro", None),
            ("save macro", None),
            ("make macro", None),
        ]

        for trigger_phrase, action_phrase in patterns:
            if trigger_phrase in text_lower:
                # Try to extract macro details
                try:
                    # Find the trigger phrase name
                    idx = text_lower.find(trigger_phrase)
                    remaining = text_lower[idx + len(trigger_phrase):].strip()

                    # Find the action
                    if action_phrase and action_phrase in remaining:
                        action_idx = remaining.find(action_phrase)
                        macro_name = remaining[:action_idx].strip().strip(",").strip()
                        key_part = remaining[action_idx + len(action_phrase):].strip()

                        # Extract the key
                        key = key_part.split()[0] if key_part else None

                        if macro_name and key:
                            return {
                                "action": "create_macro",
                                "macro_name": macro_name,
                                "trigger_phrase": macro_name,
                                "macro_keys": [key.lower()],
                                "macro_action_type": "press_key",
                            }
                except Exception:
                    pass

        return None

    def get_help_text(self) -> str:
        """Get help text for available commands.

        Returns:
            Formatted help text.
        """
        return """
Available Commands:
- Ship Controls: landing gear, quantum drive, request landing, etc.
- Power: power to weapons/engines/shields
- Combat: target, fire missile, cycle targets
- Macros: "When I say [phrase], press [key]"
- Questions: Ask about Star Citizen

Examples:
- "Lower the landing gear"
- "Engage quantum drive"
- "Power to weapons"
- "Create a macro: when I say panic, press C"
"""
