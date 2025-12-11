"""Macro management modules for Roland.

Includes:
- manager: Macro CRUD operations
- storage: SQLite persistence layer
"""

from roland.macros.manager import MacroManager
from roland.macros.storage import MacroStorage

__all__ = ["MacroManager", "MacroStorage"]
