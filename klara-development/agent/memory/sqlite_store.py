"""
memory/sqlite_store.py – SQLite as the Source of Truth for Klara.

Tables:
  - events          : every interaction cycle (input, response, tool calls)
  - user_facts      : explicit facts about the user (extracted by LLM)
  - preferences     : user preferences with recency/frequency scores
  - assistant_actions: log of all executed sub-agent tasks
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator


class SQLiteStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------
    # Context manager for connections
    # ------------------------------------------------------------------

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Schema init
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT    NOT NULL,
                    event_type  TEXT    NOT NULL,
                    user_input  TEXT,
                    response    TEXT,
                    tasks_json  TEXT,
                    reasoning   TEXT,
                    created_at  TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_facts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT    NOT NULL,
                    fact        TEXT    NOT NULL,
                    confidence  REAL    NOT NULL DEFAULT 1.0,
                    source      TEXT,
                    created_at  TEXT    NOT NULL,
                    updated_at  TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS preferences (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT    NOT NULL,
                    key         TEXT    NOT NULL,
                    value       TEXT    NOT NULL,
                    frequency   INTEGER NOT NULL DEFAULT 1,
                    recency     TEXT    NOT NULL,
                    updated_at  TEXT    NOT NULL,
                    UNIQUE(user_id, key)
                );

                CREATE TABLE IF NOT EXISTS assistant_actions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id        INTEGER REFERENCES events(id),
                    sub_agent       TEXT    NOT NULL,
                    action          TEXT    NOT NULL,
                    payload_json    TEXT,
                    result_json     TEXT,
                    success         INTEGER NOT NULL DEFAULT 1,
                    executed_at     TEXT    NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_user   ON events(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_facts_user    ON user_facts(user_id);
                CREATE INDEX IF NOT EXISTS idx_prefs_user    ON preferences(user_id);
            """)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def log_event(
        self,
        user_id: str,
        event_type: str,
        user_input: str | None = None,
        response: str | None = None,
        tasks: list[dict] | None = None,
        reasoning: str | None = None,
    ) -> int:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO events
                   (user_id, event_type, user_input, response, tasks_json, reasoning, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    event_type,
                    user_input,
                    response,
                    json.dumps(tasks) if tasks else None,
                    reasoning,
                    now,
                ),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def get_recent_events(self, user_id: str, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM events
                   WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # User facts
    # ------------------------------------------------------------------

    def upsert_fact(
        self,
        user_id: str,
        fact: str,
        confidence: float = 1.0,
        source: str | None = None,
    ) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO user_facts (user_id, fact, confidence, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, fact, confidence, source, now, now),
            )

    def get_facts(self, user_id: str, min_confidence: float = 0.5) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT fact FROM user_facts
                   WHERE user_id = ? AND confidence >= ?
                   ORDER BY updated_at DESC""",
                (user_id, min_confidence),
            ).fetchall()
        return [r["fact"] for r in rows]

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    def upsert_preference(self, user_id: str, key: str, value: str) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO preferences (user_id, key, value, frequency, recency, updated_at)
                   VALUES (?, ?, ?, 1, ?, ?)
                   ON CONFLICT(user_id, key) DO UPDATE SET
                       value     = excluded.value,
                       frequency = frequency + 1,
                       recency   = excluded.recency,
                       updated_at = excluded.updated_at""",
                (user_id, key, value, now, now),
            )

    def get_preferences(self, user_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT key, value, frequency, recency FROM preferences
                   WHERE user_id = ?
                   ORDER BY frequency DESC, recency DESC""",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Assistant actions
    # ------------------------------------------------------------------

    def log_action(
        self,
        event_id: int | None,
        sub_agent: str,
        action: str,
        payload: dict | None = None,
        result: Any = None,
        success: bool = True,
    ) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO assistant_actions
                   (event_id, sub_agent, action, payload_json, result_json, success, executed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    sub_agent,
                    action,
                    json.dumps(payload) if payload else None,
                    json.dumps(result) if result is not None else None,
                    int(success),
                    now,
                ),
            )

    # ------------------------------------------------------------------
    # Consolidation support
    # ------------------------------------------------------------------

    def get_events_since(self, user_id: str, since: str) -> list[dict]:
        """Return events since the given ISO timestamp (for nightly consolidation)."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM events
                   WHERE user_id = ? AND created_at >= ?
                   ORDER BY created_at ASC""",
                (user_id, since),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_fact_by_id(self, fact_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM user_facts WHERE id = ?", (fact_id,))

    def get_all_facts_with_ids(self, user_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, fact, confidence FROM user_facts WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]
