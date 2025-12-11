"""Macro management for Roland.

Provides high-level macro operations including creation,
execution, and management through voice commands.
"""

from pathlib import Path
from typing import Optional

from roland.config import get_settings
from roland.keyboard.executor import KeyAction, KeyboardExecutor
from roland.macros.storage import MacroStorage
from roland.utils.logger import get_logger, log_macro_event

logger = get_logger(__name__)


class MacroManager:
    """Manages voice macros for Roland.

    Handles macro creation, storage, retrieval, and execution.
    Works with both the storage layer and keyboard executor.

    Attributes:
        storage: Macro storage backend.
        executor: Keyboard executor for macro execution.
        max_macros: Maximum number of macros allowed.
    """

    def __init__(
        self,
        storage: Optional[MacroStorage] = None,
        executor: Optional[KeyboardExecutor] = None,
        max_macros: int = 100,
    ):
        """Initialize the macro manager.

        Args:
            storage: Macro storage backend.
            executor: Keyboard executor.
            max_macros: Maximum macros allowed.
        """
        settings = get_settings()
        db_path = Path(settings.macros.database_path)

        self.storage = storage or MacroStorage(db_path)
        self.executor = executor or KeyboardExecutor.from_config() if hasattr(KeyboardExecutor, 'from_config') else KeyboardExecutor()
        self.max_macros = max_macros

    @classmethod
    def from_config(cls) -> "MacroManager":
        """Create MacroManager from app configuration.

        Returns:
            Configured MacroManager instance.
        """
        settings = get_settings()
        return cls(max_macros=settings.macros.max_macros)

    async def create(
        self,
        name: str,
        trigger: str,
        keys: list[str],
        action_type: str = "press_key",
        duration: float = 0.0,
        response: Optional[str] = None,
    ) -> dict:
        """Create a new macro.

        Args:
            name: Unique macro name.
            trigger: Voice trigger phrase.
            keys: Keys to press.
            action_type: Action type (press_key, hold_key, key_combo).
            duration: Hold duration for hold_key actions.
            response: Optional TTS response after execution.

        Returns:
            Created macro dictionary.

        Raises:
            ValueError: If name exists or max macros reached.
        """
        # Check max macros
        count = await self.storage.count()
        if count >= self.max_macros:
            raise ValueError(f"Maximum number of macros ({self.max_macros}) reached")

        # Normalize inputs
        name = name.lower().strip()
        trigger = trigger.lower().strip() if trigger else name

        # Create default response if not provided
        if not response:
            response = f"Executing {name} macro, Commander."

        # Store macro
        macro_id = await self.storage.create(
            name=name,
            trigger_phrase=trigger,
            action_type=action_type,
            keys=keys,
            duration=duration,
            response=response,
        )

        macro = await self.storage.get_by_id(macro_id)
        log_macro_event("macro_created", name, trigger=trigger, keys=keys)

        return macro

    async def delete(self, name: str) -> bool:
        """Delete a macro.

        Args:
            name: Macro name to delete.

        Returns:
            True if deleted, False if not found.
        """
        name = name.lower().strip()
        deleted = await self.storage.delete(name)

        if deleted:
            log_macro_event("macro_deleted", name)

        return deleted

    async def get(self, name: str) -> Optional[dict]:
        """Get a macro by name.

        Args:
            name: Macro name.

        Returns:
            Macro dictionary or None.
        """
        return await self.storage.get(name.lower().strip())

    async def find_by_trigger(self, text: str) -> Optional[dict]:
        """Find a macro by trigger phrase in text.

        Args:
            text: Text to search for trigger phrases.

        Returns:
            Matching macro or None.
        """
        return await self.storage.find_by_trigger(text)

    async def execute(self, macro: dict) -> bool:
        """Execute a macro's keyboard action.

        Args:
            macro: Macro dictionary.

        Returns:
            True if executed successfully.
        """
        action_type = macro.get("action_type", "press_key")
        keys = macro.get("keys", [])
        duration = macro.get("duration", 0.0)
        name = macro.get("name", "unknown")

        log_macro_event("macro_executing", name, keys=keys)

        try:
            # Map action type to KeyAction
            action_map = {
                "press_key": KeyAction.PRESS,
                "hold_key": KeyAction.HOLD,
                "key_combo": KeyAction.COMBO,
            }
            action = action_map.get(action_type, KeyAction.PRESS)

            # Execute the action
            success = await self.executor.execute_action(
                action=action,
                keys=keys,
                duration=duration if action == KeyAction.HOLD else None,
            )

            if success:
                # Record usage
                await self.storage.record_usage(name)
                log_macro_event("macro_executed", name, success=True)
            else:
                log_macro_event("macro_execution_failed", name, reason="blocked")

            return success

        except Exception as e:
            logger.error("macro_execution_error", macro=name, error=str(e))
            return False

    async def list_all(self) -> list[dict]:
        """List all macros.

        Returns:
            List of all macro dictionaries.
        """
        return await self.storage.list_all()

    async def count(self) -> int:
        """Get total macro count.

        Returns:
            Number of macros.
        """
        return await self.storage.count()

    async def export(self) -> str:
        """Export all macros as JSON.

        Returns:
            JSON string of all macros.
        """
        return await self.storage.export_json()

    async def import_macros(self, json_data: str, overwrite: bool = False) -> int:
        """Import macros from JSON.

        Args:
            json_data: JSON string of macros.
            overwrite: If True, overwrite existing macros.

        Returns:
            Number of macros imported.
        """
        return await self.storage.import_json(json_data, overwrite)

    def get_macro_list_text(self, macros: list[dict]) -> str:
        """Format macro list for TTS response.

        Args:
            macros: List of macro dictionaries.

        Returns:
            Formatted text for speaking.
        """
        if not macros:
            return "You haven't created any macros yet, Commander."

        lines = [f"You have {len(macros)} macros, Commander:"]
        for macro in macros[:10]:  # Limit to 10 for TTS
            name = macro["name"]
            trigger = macro["trigger_phrase"]
            keys = ", ".join(macro["keys"])
            lines.append(f"{name}: say '{trigger}' to press {keys}")

        if len(macros) > 10:
            lines.append(f"...and {len(macros) - 10} more.")

        return " ".join(lines)

    async def handle_create_command(
        self,
        name: str,
        trigger: Optional[str],
        keys: list[str],
        action_type: str = "press_key",
        duration: float = 0.0,
    ) -> tuple[bool, str]:
        """Handle a macro creation command.

        Returns success status and response text for TTS.

        Args:
            name: Macro name.
            trigger: Trigger phrase (defaults to name).
            keys: Keys to press.
            action_type: Action type.
            duration: Hold duration.

        Returns:
            Tuple of (success, response_text).
        """
        try:
            await self.create(
                name=name,
                trigger=trigger or name,
                keys=keys,
                action_type=action_type,
                duration=duration,
            )
            return (
                True,
                f"Macro created, Commander. Say '{trigger or name}' to activate it.",
            )
        except ValueError as e:
            return (False, f"I couldn't create that macro, Commander. {str(e)}")

    async def handle_delete_command(self, name: str) -> tuple[bool, str]:
        """Handle a macro deletion command.

        Args:
            name: Macro name to delete.

        Returns:
            Tuple of (success, response_text).
        """
        if await self.delete(name):
            return (True, f"Macro '{name}' has been removed, Commander.")
        else:
            return (False, f"I couldn't find a macro named '{name}', Commander.")

    async def handle_list_command(self) -> tuple[bool, str]:
        """Handle a macro list command.

        Returns:
            Tuple of (success, response_text).
        """
        macros = await self.list_all()
        return (True, self.get_macro_list_text(macros))
