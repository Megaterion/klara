"""
SQLite-backed persistent store for Klara's episodic memory.
Tables: events, user_facts, preferences, assistant_actions
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    trigger     TEXT NOT NULL,
    user_message TEXT,
    assessment  TEXT,   -- JSON blob of ButlerAssessment
    notes       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fact        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'inference',
    confidence  REAL NOT NULL DEFAULT 1.0,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS preferences (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL UNIQUE,
    value       TEXT NOT NULL,
    recency     REAL NOT NULL DEFAULT 1.0,
    frequency   INTEGER NOT NULL DEFAULT 1,
    last_seen   TEXT DEFAULT (datetime('now')),
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS assistant_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    agent       TEXT NOT NULL,
    action      TEXT NOT NULL,
    params      TEXT,   -- JSON
    result      TEXT,   -- JSON
    duration_ms REAL,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_preferences_key ON preferences(key);
"""


class SQLiteStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def open(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info("SQLite store opened: %s", self.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # --- Events ---

    async def log_event(
        self,
        trigger: str,
        user_message: Optional[str],
        assessment: Optional[dict],
        notes: Optional[str] = None,
    ) -> int:
        ts = datetime.utcnow().isoformat()
        assessment_json = json.dumps(assessment, ensure_ascii=False) if assessment else None
        async with self._db.execute(
            "INSERT INTO events (timestamp, trigger, user_message, assessment, notes) VALUES (?, ?, ?, ?, ?)",
            (ts, trigger, user_message, assessment_json, notes),
        ) as cursor:
            row_id = cursor.lastrowid
        await self._db.commit()
        return row_id

    async def get_recent_events(self, limit: int = 20) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- User Facts ---

    async def upsert_user_fact(self, fact: str, source: str = "inference", confidence: float = 1.0) -> None:
        ts = datetime.utcnow().isoformat()
        await self._db.execute(
            """INSERT INTO user_facts (fact, source, confidence, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT DO NOTHING""",
            (fact, source, confidence, ts, ts),
        )
        await self._db.commit()

    async def get_user_facts(self, limit: int = 50) -> list[str]:
        async with self._db.execute(
            "SELECT fact FROM user_facts ORDER BY confidence DESC, updated_at DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [r["fact"] for r in rows]

    # --- Preferences ---

    async def upsert_preference(self, key: str, value: str) -> None:
        ts = datetime.utcnow().isoformat()
        await self._db.execute(
            """INSERT INTO preferences (key, value, frequency, last_seen)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(key) DO UPDATE SET
                 value=excluded.value,
                 frequency=frequency+1,
                 last_seen=excluded.last_seen""",
            (key, value, ts),
        )
        await self._db.commit()

    async def get_preferences(self) -> dict[str, str]:
        async with self._db.execute(
            "SELECT key, value FROM preferences ORDER BY frequency DESC, last_seen DESC"
        ) as cursor:
            rows = await cursor.fetchall()
        return {r["key"]: r["value"] for r in rows}

    # --- Assistant Actions ---

    async def log_action(
        self,
        agent: str,
        action: str,
        params: Optional[dict] = None,
        result: Optional[Any] = None,
        duration_ms: float = 0.0,
    ) -> None:
        ts = datetime.utcnow().isoformat()
        await self._db.execute(
            """INSERT INTO assistant_actions (timestamp, agent, action, params, result, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                ts,
                agent,
                action,
                json.dumps(params, ensure_ascii=False) if params else None,
                json.dumps(result, ensure_ascii=False) if result else None,
                duration_ms,
            ),
        )
        await self._db.commit()
