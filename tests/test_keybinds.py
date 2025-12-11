"""Unit tests for keybind manager."""

import tempfile
from pathlib import Path

import pytest
import yaml

from roland.keyboard.executor import KeyAction, PYNPUT_AVAILABLE
from roland.keyboard.keybinds import Keybind, KeybindManager

# Note: Keybind tests don't actually need pynput, but the imports chain does
# We handle this gracefully


class TestKeybind:
    """Tests for Keybind dataclass."""

    @pytest.fixture
    def sample_keybind(self):
        """Create a sample keybind."""
        return Keybind(
            name="landing_gear",
            category="flight",
            keys=["n"],
            action=KeyAction.PRESS,
            duration=0.0,
            aliases=["landing gear", "gear", "lower gear"],
            response="Landing gear toggled.",
        )

    def test_matches_exact_alias(self, sample_keybind):
        """Test matching exact alias."""
        assert sample_keybind.matches("landing gear") is True
        assert sample_keybind.matches("gear") is True

    def test_matches_partial_alias(self, sample_keybind):
        """Test matching partial/contained alias."""
        assert sample_keybind.matches("toggle the landing gear please") is True
        assert sample_keybind.matches("lower the gear now") is True

    def test_matches_case_insensitive(self, sample_keybind):
        """Test case insensitive matching."""
        assert sample_keybind.matches("LANDING GEAR") is True
        assert sample_keybind.matches("Landing Gear") is True

    def test_no_match(self, sample_keybind):
        """Test non-matching queries."""
        assert sample_keybind.matches("quantum drive") is False
        assert sample_keybind.matches("weapons") is False


class TestKeybindManager:
    """Tests for KeybindManager class."""

    @pytest.fixture
    def sample_config(self):
        """Create sample keybinds config."""
        return {
            "flight": {
                "landing_gear": {
                    "keys": ["n"],
                    "action": "press",
                    "aliases": ["landing gear", "gear down", "gear up"],
                    "response": "Landing gear toggled.",
                },
                "quantum_drive": {
                    "keys": ["b"],
                    "action": "hold",
                    "duration": 0.8,
                    "aliases": ["quantum", "quantum drive", "engage quantum"],
                    "response": "Quantum drive spooling.",
                },
            },
            "power": {
                "weapons": {
                    "keys": ["f5"],
                    "action": "press",
                    "aliases": ["power to weapons", "weapons power"],
                    "response": "Power to weapons.",
                },
            },
        }

    @pytest.fixture
    def config_file(self, sample_config):
        """Create a temporary config file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(sample_config, f)
            return Path(f.name)

    @pytest.fixture
    def manager(self, config_file):
        """Create a keybind manager with test config."""
        return KeybindManager(config_file)

    def test_load_keybinds(self, manager):
        """Test loading keybinds from YAML."""
        assert len(manager.keybinds) == 3
        assert "landing_gear" in manager.keybinds
        assert "quantum_drive" in manager.keybinds
        assert "weapons" in manager.keybinds

    def test_categories_loaded(self, manager):
        """Test categories are properly organized."""
        assert "flight" in manager.categories
        assert "power" in manager.categories
        assert len(manager.categories["flight"]) == 2
        assert len(manager.categories["power"]) == 1

    def test_get_by_name(self, manager):
        """Test getting keybind by name."""
        kb = manager.get("landing_gear")
        assert kb is not None
        assert kb.name == "landing_gear"
        assert kb.keys == ["n"]

    def test_get_nonexistent(self, manager):
        """Test getting non-existent keybind."""
        assert manager.get("nonexistent") is None

    def test_find_by_alias_exact(self, manager):
        """Test finding keybind by exact alias."""
        kb = manager.find_by_alias("landing gear")
        assert kb is not None
        assert kb.name == "landing_gear"

    def test_find_by_alias_partial(self, manager):
        """Test finding keybind by partial match."""
        kb = manager.find_by_alias("engage the quantum drive")
        assert kb is not None
        assert kb.name == "quantum_drive"

    def test_find_by_alias_fuzzy(self, manager):
        """Test fuzzy matching of aliases."""
        kb = manager.find_by_alias("power weapons")
        assert kb is not None
        assert kb.name == "weapons"

    def test_find_by_alias_no_match(self, manager):
        """Test no match returns None."""
        kb = manager.find_by_alias("completely unrelated command")
        assert kb is None

    def test_get_by_category(self, manager):
        """Test getting keybinds by category."""
        flight_binds = manager.get_by_category("flight")
        assert len(flight_binds) == 2

        power_binds = manager.get_by_category("power")
        assert len(power_binds) == 1

    def test_get_by_nonexistent_category(self, manager):
        """Test getting non-existent category returns empty list."""
        binds = manager.get_by_category("nonexistent")
        assert binds == []

    def test_list_all(self, manager):
        """Test listing all keybinds."""
        all_binds = manager.list_all()
        assert len(all_binds) == 3

    def test_list_categories(self, manager):
        """Test listing all categories."""
        categories = manager.list_categories()
        assert "flight" in categories
        assert "power" in categories

    def test_keybind_action_types(self, manager):
        """Test that action types are properly parsed."""
        landing = manager.get("landing_gear")
        assert landing.action == KeyAction.PRESS

        quantum = manager.get("quantum_drive")
        assert quantum.action == KeyAction.HOLD
        assert quantum.duration == 0.8

    def test_get_aliases_text(self, manager):
        """Test formatted aliases text output."""
        text = manager.get_aliases_text()
        assert "Available Star Citizen Commands" in text
        assert "FLIGHT" in text
        assert "POWER" in text
        assert "landing_gear" in text

    def test_load_nonexistent_file(self):
        """Test loading from non-existent file."""
        manager = KeybindManager(Path("/nonexistent/path.yaml"))
        assert len(manager.keybinds) == 0

    def test_empty_config(self):
        """Test loading empty config file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            config_path = Path(f.name)

        manager = KeybindManager(config_path)
        assert len(manager.keybinds) == 0
