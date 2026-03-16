from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from app.models import MemoryRecord


class LongTermMemory:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    async def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_input TEXT NOT NULL,
                    ai_response TEXT NOT NULL,
                    tags TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def add_memory(self, record: MemoryRecord) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                INSERT INTO memories (timestamp, user_input, ai_response, tags)
                VALUES (?, ?, ?, ?)
                """,
                (
                    record.timestamp.isoformat(),
                    record.user_input,
                    record.ai_response,
                    json.dumps(record.tags),
                ),
            )
            await db.commit()

    async def recent_memories(self, limit: int = 10) -> list[MemoryRecord]:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                SELECT timestamp, user_input, ai_response, tags
                FROM memories
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
        return [
            MemoryRecord(
                timestamp=row[0],
                user_input=row[1],
                ai_response=row[2],
                tags=json.loads(row[3]),
            )
            for row in rows
        ]
