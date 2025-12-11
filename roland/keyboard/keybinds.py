"""Star Citizen keybind definitions and management.

Loads keybind definitions from YAML and provides lookup functionality
for mapping voice commands to keyboard actions.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from roland.keyboard.executor import KeyAction
from roland.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Keybind:
    """Represents a single keybind definition.

    Attributes:
        name: Internal name of the keybind.
        category: Category (flight, power, combat, etc.).
        keys: List of keys to press.
        action: Type of action (press, hold, combo).
        duration: Duration for hold actions.
        aliases: List of voice command aliases.
        response: Response text for TTS.
    """

    name: str
    category: str
    keys: list[str]
    action: KeyAction
    duration: float
    aliases: list[str]
    response: str

    def matches(self, query: str) -> bool:
        """Check if query matches any alias.

        Args:
            query: Voice command text to match.

        Returns:
            True if query matches an alias.
        """
        query_lower = query.lower().strip()
        return any(alias.lower() in query_lower for alias in self.aliases)


class KeybindManager:
    """Manages Star Citizen keybind definitions.

    Loads keybinds from YAML configuration and provides methods
    to look up keybinds by name or voice command.

    Attributes:
        keybinds: Dictionary of keybind name to Keybind object.
        categories: Dictionary of category name to list of keybinds.
    """

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize the keybind manager.

        Args:
            config_path: Path to keybinds YAML file.
        """
        self.keybinds: dict[str, Keybind] = {}
        self.categories: dict[str, list[Keybind]] = {}
        self._alias_index: dict[str, Keybind] = {}

        if config_path:
            self.load(config_path)
        else:
            self.load(Path("config/keybinds.yaml"))

    def load(self, config_path: Path) -> None:
        """Load keybinds from a YAML file.

        Args:
            config_path: Path to keybinds YAML file.
        """
        if not config_path.exists():
            logger.warning("keybinds_file_not_found", path=str(config_path))
            return

        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

        self.keybinds.clear()
        self.categories.clear()
        self._alias_index.clear()

        for category, binds in data.items():
            if not isinstance(binds, dict):
                continue

            self.categories[category] = []

            for name, bind_data in binds.items():
                if not isinstance(bind_data, dict):
                    continue

                keybind = Keybind(
                    name=name,
                    category=category,
                    keys=bind_data.get("keys", []),
                    action=KeyAction(bind_data.get("action", "press")),
                    duration=bind_data.get("duration", 0.0),
                    aliases=bind_data.get("aliases", []),
                    response=bind_data.get("response", ""),
                )

                self.keybinds[name] = keybind
                self.categories[category].append(keybind)

                # Index aliases for fast lookup
                for alias in keybind.aliases:
                    self._alias_index[alias.lower()] = keybind

        logger.info(
            "keybinds_loaded",
            total=len(self.keybinds),
            categories=list(self.categories.keys()),
        )

    def get(self, name: str) -> Optional[Keybind]:
        """Get a keybind by its internal name.

        Args:
            name: Internal keybind name.

        Returns:
            Keybind if found, None otherwise.
        """
        return self.keybinds.get(name)

    def find_by_alias(self, query: str) -> Optional[Keybind]:
        """Find a keybind matching a voice command.

        First tries exact alias match, then partial matching.

        Args:
            query: Voice command text.

        Returns:
            Matching Keybind if found, None otherwise.
        """
        query_lower = query.lower().strip()

        # Try exact alias match first
        if query_lower in self._alias_index:
            return self._alias_index[query_lower]

        # Try partial matching
        for alias, keybind in self._alias_index.items():
            if alias in query_lower or query_lower in alias:
                return keybind

        # Try fuzzy matching with individual words
        query_words = set(query_lower.split())
        best_match: Optional[Keybind] = None
        best_score = 0

        for keybind in self.keybinds.values():
            for alias in keybind.aliases:
                alias_words = set(alias.lower().split())
                common_words = query_words & alias_words
                score = len(common_words) / max(len(alias_words), 1)
                if score > best_score and score >= 0.5:
                    best_score = score
                    best_match = keybind

        return best_match

    def get_by_category(self, category: str) -> list[Keybind]:
        """Get all keybinds in a category.

        Args:
            category: Category name.

        Returns:
            List of keybinds in the category.
        """
        return self.categories.get(category, [])

    def list_all(self) -> list[Keybind]:
        """Get all keybinds.

        Returns:
            List of all keybinds.
        """
        return list(self.keybinds.values())

    def list_categories(self) -> list[str]:
        """Get all category names.

        Returns:
            List of category names.
        """
        return list(self.categories.keys())

    def get_aliases_text(self) -> str:
        """Get formatted text of all keybinds and aliases.

        Returns:
            Formatted string for display or LLM context.
        """
        lines = ["Available Star Citizen Commands:"]

        for category, binds in self.categories.items():
            lines.append(f"\n{category.upper()}:")
            for bind in binds:
                aliases_str = ", ".join(bind.aliases[:3])
                if len(bind.aliases) > 3:
                    aliases_str += f" (+{len(bind.aliases) - 3} more)"
                lines.append(f"  - {bind.name}: {aliases_str}")

        return "\n".join(lines)
