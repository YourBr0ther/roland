"""SQLite storage layer for macros.

Provides persistent storage for voice macros using SQLite
with async support via aiosqlite.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from roland.utils.logger import get_logger, log_macro_event

logger = get_logger(__name__)


# SQL Schema
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS macros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    trigger_phrase TEXT NOT NULL,
    action_type TEXT NOT NULL,
    keys TEXT NOT NULL,
    duration REAL DEFAULT 0.0,
    response TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP,
    use_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_macros_trigger ON macros(trigger_phrase);
CREATE INDEX IF NOT EXISTS idx_macros_name ON macros(name);
"""


class MacroStorage:
    """SQLite storage backend for macros.

    Provides async CRUD operations for voice macro persistence.

    Attributes:
        db_path: Path to SQLite database file.
    """

    def __init__(self, db_path: Path):
        """Initialize macro storage.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the database schema."""
        if self._initialized:
            return

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(CREATE_TABLE_SQL)
            await db.commit()

        self._initialized = True
        logger.info("macro_storage_initialized", db_path=str(self.db_path))

    async def create(
        self,
        name: str,
        trigger_phrase: str,
        action_type: str,
        keys: list[str],
        duration: float = 0.0,
        response: Optional[str] = None,
    ) -> int:
        """Create a new macro.

        Args:
            name: Unique macro name.
            trigger_phrase: Voice trigger phrase.
            action_type: Action type (press_key, hold_key, key_combo).
            keys: List of keys to press.
            duration: Duration for hold actions.
            response: Optional TTS response.

        Returns:
            ID of created macro.

        Raises:
            ValueError: If macro with name already exists.
        """
        await self.initialize()

        keys_json = json.dumps(keys)

        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    """
                    INSERT INTO macros (name, trigger_phrase, action_type, keys, duration, response)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (name, trigger_phrase, action_type, keys_json, duration, response),
                )
                await db.commit()
                macro_id = cursor.lastrowid

            log_macro_event("macro_created", name, trigger=trigger_phrase, keys=keys)
            return macro_id

        except aiosqlite.IntegrityError:
            raise ValueError(f"Macro '{name}' already exists")

    async def get(self, name: str) -> Optional[dict]:
        """Get a macro by name.

        Args:
            name: Macro name.

        Returns:
            Macro dictionary or None if not found.
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM macros WHERE name = ?",
                (name,),
            )
            row = await cursor.fetchone()

        if row:
            return self._row_to_dict(row)
        return None

    async def get_by_id(self, macro_id: int) -> Optional[dict]:
        """Get a macro by ID.

        Args:
            macro_id: Macro ID.

        Returns:
            Macro dictionary or None if not found.
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM macros WHERE id = ?",
                (macro_id,),
            )
            row = await cursor.fetchone()

        if row:
            return self._row_to_dict(row)
        return None

    async def find_by_trigger(self, text: str) -> Optional[dict]:
        """Find a macro by trigger phrase.

        Searches for exact match first, then partial match.

        Args:
            text: Text to search for trigger phrases.

        Returns:
            Matching macro or None.
        """
        await self.initialize()

        text_lower = text.lower().strip()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Try exact match first
            cursor = await db.execute(
                "SELECT * FROM macros WHERE LOWER(trigger_phrase) = ?",
                (text_lower,),
            )
            row = await cursor.fetchone()

            if row:
                return self._row_to_dict(row)

            # Try partial match (trigger phrase in text)
            cursor = await db.execute("SELECT * FROM macros")
            rows = await cursor.fetchall()

            for row in rows:
                trigger = row["trigger_phrase"].lower()
                if trigger in text_lower:
                    return self._row_to_dict(row)

        return None

    async def update(
        self,
        name: str,
        trigger_phrase: Optional[str] = None,
        action_type: Optional[str] = None,
        keys: Optional[list[str]] = None,
        duration: Optional[float] = None,
        response: Optional[str] = None,
    ) -> bool:
        """Update an existing macro.

        Args:
            name: Macro name to update.
            trigger_phrase: New trigger phrase.
            action_type: New action type.
            keys: New keys list.
            duration: New duration.
            response: New response.

        Returns:
            True if updated, False if not found.
        """
        await self.initialize()

        updates = []
        params = []

        if trigger_phrase is not None:
            updates.append("trigger_phrase = ?")
            params.append(trigger_phrase)
        if action_type is not None:
            updates.append("action_type = ?")
            params.append(action_type)
        if keys is not None:
            updates.append("keys = ?")
            params.append(json.dumps(keys))
        if duration is not None:
            updates.append("duration = ?")
            params.append(duration)
        if response is not None:
            updates.append("response = ?")
            params.append(response)

        if not updates:
            return False

        params.append(name)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"UPDATE macros SET {', '.join(updates)} WHERE name = ?",
                params,
            )
            await db.commit()

            if cursor.rowcount > 0:
                log_macro_event("macro_updated", name)
                return True

        return False

    async def delete(self, name: str) -> bool:
        """Delete a macro by name.

        Args:
            name: Macro name to delete.

        Returns:
            True if deleted, False if not found.
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM macros WHERE name = ?",
                (name,),
            )
            await db.commit()

            if cursor.rowcount > 0:
                log_macro_event("macro_deleted", name)
                return True

        return False

    async def list_all(self) -> list[dict]:
        """List all macros.

        Returns:
            List of all macro dictionaries.
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM macros ORDER BY name"
            )
            rows = await cursor.fetchall()

        return [self._row_to_dict(row) for row in rows]

    async def count(self) -> int:
        """Get total number of macros.

        Returns:
            Macro count.
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM macros")
            row = await cursor.fetchone()

        return row[0] if row else 0

    async def record_usage(self, name: str) -> None:
        """Record macro usage.

        Updates last_used timestamp and increments use_count.

        Args:
            name: Macro name.
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE macros
                SET last_used = ?, use_count = use_count + 1
                WHERE name = ?
                """,
                (datetime.now(), name),
            )
            await db.commit()

    async def export_json(self) -> str:
        """Export all macros as JSON.

        Returns:
            JSON string of all macros.
        """
        macros = await self.list_all()
        return json.dumps(macros, indent=2, default=str)

    async def import_json(self, json_data: str, overwrite: bool = False) -> int:
        """Import macros from JSON.

        Args:
            json_data: JSON string of macros.
            overwrite: If True, overwrite existing macros.

        Returns:
            Number of macros imported.
        """
        macros = json.loads(json_data)
        imported = 0

        for macro in macros:
            try:
                if overwrite:
                    await self.delete(macro["name"])

                await self.create(
                    name=macro["name"],
                    trigger_phrase=macro["trigger_phrase"],
                    action_type=macro["action_type"],
                    keys=macro["keys"],
                    duration=macro.get("duration", 0.0),
                    response=macro.get("response"),
                )
                imported += 1
            except (ValueError, KeyError):
                continue

        logger.info("macros_imported", count=imported)
        return imported

    def _row_to_dict(self, row) -> dict:
        """Convert database row to dictionary.

        Args:
            row: Database row.

        Returns:
            Macro dictionary.
        """
        return {
            "id": row["id"],
            "name": row["name"],
            "trigger_phrase": row["trigger_phrase"],
            "action_type": row["action_type"],
            "keys": json.loads(row["keys"]),
            "duration": row["duration"],
            "response": row["response"],
            "created_at": row["created_at"],
            "last_used": row["last_used"],
            "use_count": row["use_count"],
        }
