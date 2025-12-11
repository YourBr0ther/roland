"""Keyboard input simulation for Roland.

Uses pynput to simulate keyboard presses, holds, and combinations
for controlling Star Citizen.
"""

import asyncio
import subprocess
from enum import Enum
from typing import Optional, Union

from roland.utils.logger import get_logger

logger = get_logger(__name__)

# pynput requires X display - handle gracefully for headless/testing
try:
    from pynput.keyboard import Controller, Key
    PYNPUT_AVAILABLE = True
except ImportError as e:
    PYNPUT_AVAILABLE = False
    Controller = None
    Key = None
    logger.warning("pynput_not_available", error=str(e))


class KeyAction(str, Enum):
    """Types of keyboard actions."""

    PRESS = "press"
    HOLD = "hold"
    RELEASE = "release"
    COMBO = "combo"


# Map string key names to pynput Key objects (only if pynput available)
SPECIAL_KEYS: dict[str, "Key"] = {}

if PYNPUT_AVAILABLE and Key is not None:
    SPECIAL_KEYS = {
        "ctrl": Key.ctrl,
        "control": Key.ctrl,
        "ctrl_l": Key.ctrl_l,
        "ctrl_r": Key.ctrl_r,
        "alt": Key.alt,
        "alt_l": Key.alt_l,
        "alt_r": Key.alt_r,
        "shift": Key.shift,
        "shift_l": Key.shift_l,
        "shift_r": Key.shift_r,
        "space": Key.space,
        "enter": Key.enter,
        "return": Key.enter,
        "tab": Key.tab,
        "esc": Key.esc,
        "escape": Key.esc,
        "backspace": Key.backspace,
        "delete": Key.delete,
        "up": Key.up,
        "down": Key.down,
        "left": Key.left,
        "right": Key.right,
        "home": Key.home,
        "end": Key.end,
        "page_up": Key.page_up,
        "page_down": Key.page_down,
        "insert": Key.insert,
        "f1": Key.f1,
        "f2": Key.f2,
        "f3": Key.f3,
        "f4": Key.f4,
        "f5": Key.f5,
        "f6": Key.f6,
        "f7": Key.f7,
        "f8": Key.f8,
        "f9": Key.f9,
        "f10": Key.f10,
        "f11": Key.f11,
        "f12": Key.f12,
        "caps_lock": Key.caps_lock,
        "num_lock": Key.num_lock,
        "scroll_lock": Key.scroll_lock,
        "print_screen": Key.print_screen,
        "pause": Key.pause,
        "menu": Key.menu,
    }


class KeyboardExecutor:
    """Executes keyboard actions for game control.

    This class provides methods to simulate keyboard input including
    single key presses, key holds, key releases, and key combinations.
    It can optionally check if the game window is focused before sending input.

    Attributes:
        keyboard: pynput keyboard controller.
        require_focus: Whether to require game window focus.
        game_window_title: Title of the game window to check for focus.
        press_duration: Default duration for key presses.
        hold_duration: Default duration for key holds.
        combo_delay: Delay between keys in a combination.
    """

    def __init__(
        self,
        require_focus: bool = True,
        game_window_title: str = "Star Citizen",
        press_duration: float = 0.05,
        hold_duration: float = 1.0,
        combo_delay: float = 0.02,
    ):
        """Initialize the keyboard executor.

        Args:
            require_focus: If True, only send input when game is focused.
            game_window_title: Window title to check for focus.
            press_duration: Default key press duration in seconds.
            hold_duration: Default key hold duration in seconds.
            combo_delay: Delay between keys in combinations.
        """
        self.keyboard = Controller() if PYNPUT_AVAILABLE and Controller else None
        self.require_focus = require_focus
        self.game_window_title = game_window_title
        self.press_duration = press_duration
        self.hold_duration = hold_duration
        self.combo_delay = combo_delay
        self._held_keys: list[Union["Key", str]] = []

    @property
    def is_available(self) -> bool:
        """Check if keyboard control is available."""
        return PYNPUT_AVAILABLE and self.keyboard is not None

    def _resolve_key(self, key: str) -> Union[Key, str]:
        """Resolve a key string to pynput Key or character.

        Args:
            key: Key name or character.

        Returns:
            pynput Key object or lowercase character.
        """
        key_lower = key.lower().strip()
        if key_lower in SPECIAL_KEYS:
            return SPECIAL_KEYS[key_lower]
        # Single character keys
        if len(key) == 1:
            return key.lower()
        # Unknown key, return as-is
        logger.warning("unknown_key", key=key)
        return key.lower()

    def is_game_focused(self) -> bool:
        """Check if the game window is currently focused.

        Returns:
            True if game window is focused or focus check is disabled.
        """
        if not self.require_focus:
            return True

        try:
            # Use xdotool to get active window name
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            active_window = result.stdout.strip()
            is_focused = self.game_window_title.lower() in active_window.lower()
            logger.debug(
                "focus_check",
                active_window=active_window,
                game_window=self.game_window_title,
                is_focused=is_focused,
            )
            return is_focused
        except FileNotFoundError:
            logger.warning("xdotool_not_found", message="Install xdotool for focus detection")
            return True  # Allow input if xdotool not installed
        except subprocess.TimeoutExpired:
            logger.warning("focus_check_timeout")
            return True
        except Exception as e:
            logger.error("focus_check_failed", error=str(e))
            return True

    async def press_key(self, key: str, duration: Optional[float] = None) -> bool:
        """Press and release a single key.

        Args:
            key: Key to press (e.g., "n", "space", "f5").
            duration: Optional press duration override.

        Returns:
            True if key was pressed, False if blocked.
        """
        if not self.is_game_focused():
            logger.warning("key_blocked_no_focus", key=key)
            return False

        k = self._resolve_key(key)
        press_time = duration or self.press_duration

        logger.info("key_press", key=key, duration=press_time)

        self.keyboard.press(k)
        await asyncio.sleep(press_time)
        self.keyboard.release(k)

        return True

    async def hold_key(self, key: str, duration: Optional[float] = None) -> bool:
        """Hold a key for a specified duration.

        Args:
            key: Key to hold.
            duration: Hold duration in seconds.

        Returns:
            True if key was held, False if blocked.
        """
        if not self.is_game_focused():
            logger.warning("key_blocked_no_focus", key=key)
            return False

        k = self._resolve_key(key)
        hold_time = duration or self.hold_duration

        logger.info("key_hold", key=key, duration=hold_time)

        self.keyboard.press(k)
        self._held_keys.append(k)

        await asyncio.sleep(hold_time)

        self.keyboard.release(k)
        if k in self._held_keys:
            self._held_keys.remove(k)

        return True

    async def release_key(self, key: str) -> bool:
        """Release a held key.

        Args:
            key: Key to release.

        Returns:
            True if key was released, False if not held.
        """
        k = self._resolve_key(key)

        if k not in self._held_keys:
            logger.warning("release_key_not_held", key=key)
            return False

        logger.info("key_release", key=key)

        self.keyboard.release(k)
        self._held_keys.remove(k)

        return True

    async def key_combo(self, keys: list[str], hold_duration: Optional[float] = None) -> bool:
        """Press a key combination (e.g., Ctrl+N).

        All modifier keys are pressed first, then the final key,
        then all keys are released in reverse order.

        Args:
            keys: List of keys to press together (e.g., ["ctrl", "n"]).
            hold_duration: Optional duration to hold the combo.

        Returns:
            True if combo was executed, False if blocked.
        """
        if not self.is_game_focused():
            logger.warning("combo_blocked_no_focus", keys=keys)
            return False

        if not keys:
            logger.warning("combo_empty_keys")
            return False

        resolved_keys = [self._resolve_key(k) for k in keys]

        logger.info("key_combo", keys=keys, hold_duration=hold_duration)

        # Press all keys
        for k in resolved_keys:
            self.keyboard.press(k)
            await asyncio.sleep(self.combo_delay)

        # Hold if duration specified
        if hold_duration:
            await asyncio.sleep(hold_duration)
        else:
            await asyncio.sleep(self.press_duration)

        # Release all keys in reverse order
        for k in reversed(resolved_keys):
            self.keyboard.release(k)
            await asyncio.sleep(self.combo_delay)

        return True

    async def type_string(self, text: str, delay: float = 0.05) -> bool:
        """Type a string of characters.

        Args:
            text: String to type.
            delay: Delay between characters.

        Returns:
            True if string was typed, False if blocked.
        """
        if not self.is_game_focused():
            logger.warning("type_blocked_no_focus", text=text[:20])
            return False

        logger.info("type_string", text=text[:50], length=len(text))

        for char in text:
            self.keyboard.press(char)
            self.keyboard.release(char)
            await asyncio.sleep(delay)

        return True

    def release_all_held_keys(self) -> None:
        """Release all currently held keys.

        Call this during cleanup or error recovery.
        """
        for k in list(self._held_keys):
            try:
                self.keyboard.release(k)
            except Exception as e:
                logger.error("release_held_key_failed", key=str(k), error=str(e))
        self._held_keys.clear()
        logger.info("released_all_held_keys")

    async def execute_action(
        self,
        action: KeyAction,
        keys: list[str],
        duration: Optional[float] = None,
    ) -> bool:
        """Execute a keyboard action based on action type.

        Args:
            action: Type of action (press, hold, release, combo).
            keys: List of keys involved.
            duration: Optional duration for holds.

        Returns:
            True if action was executed, False if blocked/failed.
        """
        if action == KeyAction.PRESS:
            if len(keys) == 1:
                return await self.press_key(keys[0], duration)
            # Multiple keys = sequential presses
            for key in keys:
                if not await self.press_key(key, duration):
                    return False
            return True

        elif action == KeyAction.HOLD:
            if len(keys) >= 1:
                return await self.hold_key(keys[0], duration)
            return False

        elif action == KeyAction.RELEASE:
            if len(keys) >= 1:
                return await self.release_key(keys[0])
            return False

        elif action == KeyAction.COMBO:
            return await self.key_combo(keys, duration)

        else:
            logger.error("unknown_action", action=action)
            return False
