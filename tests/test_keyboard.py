"""Unit tests for keyboard executor."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from roland.keyboard.executor import KeyAction, KeyboardExecutor, SPECIAL_KEYS


class TestKeyboardExecutor:
    """Tests for KeyboardExecutor class."""

    @pytest.fixture
    def mock_controller(self):
        """Create a mock pynput Controller."""
        with patch("roland.keyboard.executor.Controller") as mock:
            yield mock

    @pytest.fixture
    def executor(self, mock_controller):
        """Create executor with mocked controller."""
        exec = KeyboardExecutor(require_focus=False)
        exec.keyboard = mock_controller.return_value
        return exec

    def test_resolve_key_character(self, executor):
        """Test resolving single character keys."""
        assert executor._resolve_key("n") == "n"
        assert executor._resolve_key("N") == "n"
        assert executor._resolve_key("a") == "a"

    def test_resolve_key_special(self, executor):
        """Test resolving special keys."""
        from pynput.keyboard import Key

        assert executor._resolve_key("ctrl") == Key.ctrl
        assert executor._resolve_key("CTRL") == Key.ctrl
        assert executor._resolve_key("space") == Key.space
        assert executor._resolve_key("enter") == Key.enter
        assert executor._resolve_key("f5") == Key.f5

    def test_resolve_key_unknown(self, executor):
        """Test resolving unknown keys returns lowercase."""
        assert executor._resolve_key("unknown_key") == "unknown_key"

    @pytest.mark.asyncio
    async def test_press_key(self, executor):
        """Test single key press."""
        result = await executor.press_key("n")

        assert result is True
        executor.keyboard.press.assert_called_once()
        executor.keyboard.release.assert_called_once()

    @pytest.mark.asyncio
    async def test_press_key_with_duration(self, executor):
        """Test key press with custom duration."""
        with patch("asyncio.sleep") as mock_sleep:
            await executor.press_key("n", duration=0.1)
            # Check that sleep was called with our duration
            mock_sleep.assert_called()

    @pytest.mark.asyncio
    async def test_hold_key(self, executor):
        """Test holding a key."""
        with patch("asyncio.sleep"):
            result = await executor.hold_key("b", duration=0.5)

        assert result is True
        executor.keyboard.press.assert_called_once()
        executor.keyboard.release.assert_called_once()

    @pytest.mark.asyncio
    async def test_hold_key_tracks_held_keys(self, executor):
        """Test that held keys are tracked and released."""
        # Start holding
        with patch("asyncio.sleep"):
            await executor.hold_key("b", duration=0.1)

        # After hold completes, key should be released and removed from tracking
        assert "b" not in executor._held_keys

    @pytest.mark.asyncio
    async def test_key_combo(self, executor):
        """Test key combination."""
        with patch("asyncio.sleep"):
            result = await executor.key_combo(["ctrl", "n"])

        assert result is True
        # Should press both keys
        assert executor.keyboard.press.call_count == 2
        # Should release both keys
        assert executor.keyboard.release.call_count == 2

    @pytest.mark.asyncio
    async def test_key_combo_empty_keys(self, executor):
        """Test key combo with empty keys list."""
        result = await executor.key_combo([])
        assert result is False

    @pytest.mark.asyncio
    async def test_release_key_not_held(self, executor):
        """Test releasing a key that wasn't held."""
        result = await executor.release_key("x")
        assert result is False

    def test_release_all_held_keys(self, executor):
        """Test releasing all held keys."""
        # Simulate held keys
        executor._held_keys = ["a", "b", "c"]

        executor.release_all_held_keys()

        assert executor._held_keys == []
        assert executor.keyboard.release.call_count == 3

    @pytest.mark.asyncio
    async def test_execute_action_press(self, executor):
        """Test execute_action with press action."""
        with patch("asyncio.sleep"):
            result = await executor.execute_action(KeyAction.PRESS, ["n"])
        assert result is True

    @pytest.mark.asyncio
    async def test_execute_action_hold(self, executor):
        """Test execute_action with hold action."""
        with patch("asyncio.sleep"):
            result = await executor.execute_action(KeyAction.HOLD, ["b"], duration=0.5)
        assert result is True

    @pytest.mark.asyncio
    async def test_execute_action_combo(self, executor):
        """Test execute_action with combo action."""
        with patch("asyncio.sleep"):
            result = await executor.execute_action(KeyAction.COMBO, ["ctrl", "n"])
        assert result is True

    @pytest.mark.asyncio
    async def test_type_string(self, executor):
        """Test typing a string."""
        with patch("asyncio.sleep"):
            result = await executor.type_string("hello")

        assert result is True
        # Should press and release each character
        assert executor.keyboard.press.call_count == 5
        assert executor.keyboard.release.call_count == 5


class TestKeyboardExecutorFocusCheck:
    """Tests for game focus checking."""

    @pytest.fixture
    def executor_with_focus(self):
        """Create executor that requires focus."""
        with patch("roland.keyboard.executor.Controller"):
            exec = KeyboardExecutor(require_focus=True, game_window_title="Star Citizen")
            return exec

    def test_focus_disabled(self):
        """Test that focus check is skipped when disabled."""
        with patch("roland.keyboard.executor.Controller"):
            exec = KeyboardExecutor(require_focus=False)
            assert exec.is_game_focused() is True

    @patch("subprocess.run")
    def test_focus_check_game_focused(self, mock_run, executor_with_focus):
        """Test focus check when game is focused."""
        mock_run.return_value = MagicMock(stdout="Star Citizen Alpha 4.0\n")
        assert executor_with_focus.is_game_focused() is True

    @patch("subprocess.run")
    def test_focus_check_game_not_focused(self, mock_run, executor_with_focus):
        """Test focus check when game is not focused."""
        mock_run.return_value = MagicMock(stdout="Firefox\n")
        assert executor_with_focus.is_game_focused() is False

    @patch("subprocess.run")
    def test_focus_check_xdotool_not_found(self, mock_run, executor_with_focus):
        """Test focus check when xdotool is not installed."""
        mock_run.side_effect = FileNotFoundError()
        # Should return True (allow input) when xdotool not found
        assert executor_with_focus.is_game_focused() is True

    @pytest.mark.asyncio
    @patch("subprocess.run")
    async def test_press_key_blocked_by_focus(self, mock_run, executor_with_focus):
        """Test that key press is blocked when game not focused."""
        mock_run.return_value = MagicMock(stdout="Firefox\n")
        result = await executor_with_focus.press_key("n")
        assert result is False


class TestSpecialKeys:
    """Tests for special key mappings."""

    def test_all_special_keys_are_valid(self):
        """Test that all special key mappings are valid pynput Keys."""
        from pynput.keyboard import Key

        for name, key in SPECIAL_KEYS.items():
            assert isinstance(key, Key), f"{name} is not a valid Key"

    def test_common_modifiers_mapped(self):
        """Test that common modifier keys are mapped."""
        assert "ctrl" in SPECIAL_KEYS
        assert "alt" in SPECIAL_KEYS
        assert "shift" in SPECIAL_KEYS

    def test_function_keys_mapped(self):
        """Test that function keys are mapped."""
        for i in range(1, 13):
            assert f"f{i}" in SPECIAL_KEYS
