"""SQLite storage layer.

A single local file (``gymbot.db`` by default) holds everything. Pure
stdlib ``sqlite3``, so no server is needed.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Iterable, Optional

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meals (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    name    TEXT NOT NULL,
    kcal    REAL NOT NULL,
    protein REAL NOT NULL,
    carbs   REAL NOT NULL,
    fat     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sets (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    exercise TEXT NOT NULL,
    weight   REAL NOT NULL,
    reps     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bodyweight (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kg  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sets_exercise ON sets(exercise, ts);
CREATE INDEX IF NOT EXISTS idx_meals_ts ON meals(ts);
CREATE INDEX IF NOT EXISTS idx_bodyweight_ts ON bodyweight(ts);
"""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class DB:
    """Thin wrapper around a single SQLite connection.

    The connection is opened with ``check_same_thread=False`` and guarded by
    an ``RLock`` because the WhatsApp adapter calls into it from its message
    callback thread, not the thread that created it.
    """

    def __init__(self, path: Optional[str] = None):
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path or config.DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # --- meals -------------------------------------------------------------
    def log_meal(self, name: str, kcal: float, protein: float,
                 carbs: float, fat: float, ts: Optional[str] = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO meals (ts, name, kcal, protein, carbs, fat) VALUES (?,?,?,?,?,?)",
                (ts or _now_iso(), name, kcal, protein, carbs, fat),
            )
            self.conn.commit()

    def meals_between(self, start: datetime, end: datetime) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM meals WHERE ts >= ? AND ts < ? ORDER BY ts",
                (start.isoformat(), end.isoformat()),
            ).fetchall()

    # --- training sets ------------------------------------------------------
    def log_set(self, exercise: str, weight: float, reps: int,
                ts: Optional[str] = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO sets (ts, exercise, weight, reps) VALUES (?,?,?,?)",
                (ts or _now_iso(), exercise, weight, reps),
            )
            self.conn.commit()

    def sets_between(self, start: datetime, end: datetime,
                     exercise: Optional[str] = None) -> list[sqlite3.Row]:
        with self._lock:
            if exercise:
                return self.conn.execute(
                    "SELECT * FROM sets WHERE ts >= ? AND ts < ? AND exercise = ? ORDER BY ts",
                    (start.isoformat(), end.isoformat(), exercise),
                ).fetchall()
            return self.conn.execute(
                "SELECT * FROM sets WHERE ts >= ? AND ts < ? ORDER BY ts",
                (start.isoformat(), end.isoformat()),
            ).fetchall()

    def sets_since(self, since: datetime,
                   exercise: Optional[str] = None) -> list[sqlite3.Row]:
        return self.sets_between(since, datetime.now() + timedelta(days=1), exercise)

    def exercises(self) -> list[str]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT DISTINCT exercise FROM sets ORDER BY exercise"
            ).fetchall()
            return [r["exercise"] for r in rows]

    # --- body weight ---------------------------------------------------------
    def log_bodyweight(self, kg: float, ts: Optional[str] = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO bodyweight (ts, kg) VALUES (?,?)",
                (ts or _now_iso(), kg),
            )
            self.conn.commit()

    def bodyweight_between(self, start: datetime, end: datetime) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM bodyweight WHERE ts >= ? AND ts < ? ORDER BY ts",
                (start.isoformat(), end.isoformat()),
            ).fetchall()

    # --- settings (key/value, e.g. diet targets) -----------------------------
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self.conn.commit()

    def get_diet_target(self) -> "config.DietTarget":
        """Read persisted diet targets (fall back to config defaults)."""
        t = config.DietTarget()
        raw = self.get_setting("diet_target")
        if raw:
            try:
                parts = [float(x) for x in raw.split(",")]
                if len(parts) == 4:
                    t.kcal, t.protein_g, t.carbs_g, t.fat_g = parts
            except ValueError:
                pass
        return t

    def set_diet_target(self, target: "config.DietTarget") -> None:
        self.set_setting(
            "diet_target",
            f"{target.kcal},{target.protein_g},{target.carbs_g},{target.fat_g}",
        )

    def close(self) -> None:
        with self._lock:
            self.conn.close()


def normalize_exercise(name: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation noise."""
    return " ".join(name.lower().split())
