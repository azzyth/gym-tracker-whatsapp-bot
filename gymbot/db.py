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


# Public kind -> table name. Only ever used to build SQL from these literals,
# never from user input.
_LOG_TABLES = {"meal": "meals", "set": "sets", "weigh": "bodyweight"}


class DB:
    """Thin wrapper around a single SQLite connection.

    The connection is opened with ``check_same_thread=False`` and guarded by
    an ``RLock`` because the WhatsApp adapter calls into it from its message
    callback thread, not the thread that created it.

    Every read orders by ``ts, id``. Several sets can land in the same second
    (one ``/set`` writes them with an identical timestamp), and without the
    ``id`` tiebreak SQLite is free to return them in any order — which would
    make "your last set" mean an arbitrary one of the three.
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
                "SELECT * FROM meals WHERE ts >= ? AND ts < ? ORDER BY ts, id",
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
                    "SELECT * FROM sets WHERE ts >= ? AND ts < ? AND exercise = ? ORDER BY ts, id",
                    (start.isoformat(), end.isoformat(), exercise),
                ).fetchall()
            return self.conn.execute(
                "SELECT * FROM sets WHERE ts >= ? AND ts < ? ORDER BY ts, id",
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

    def all_sets(self, exercise: Optional[str] = None) -> list[sqlite3.Row]:
        with self._lock:
            if exercise:
                return self.conn.execute(
                    "SELECT * FROM sets WHERE exercise = ? ORDER BY ts, id", (exercise,)
                ).fetchall()
            return self.conn.execute(
                "SELECT * FROM sets ORDER BY ts, id"
            ).fetchall()

    def rename_exercise(self, old: str, new: str) -> int:
        """Re-point every logged set from one exercise name to another.

        Returns the number of sets moved, so the caller can report a merge
        (target existed) versus a plain rename.
        """
        with self._lock:
            cur = self.conn.execute(
                "UPDATE sets SET exercise = ? WHERE exercise = ?", (new, old)
            )
            self.conn.commit()
            return cur.rowcount

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
                "SELECT * FROM bodyweight WHERE ts >= ? AND ts < ? ORDER BY ts, id",
                (start.isoformat(), end.isoformat()),
            ).fetchall()

    # --- undo ----------------------------------------------------------------
    def _delete_last(self, table: str, n: int) -> list[sqlite3.Row]:
        with self._lock:
            rows = self.conn.execute(
                f"SELECT * FROM {table} ORDER BY ts DESC, id DESC LIMIT ?", (max(1, n),)
            ).fetchall()
            if not rows:
                return []
            ids = [r["id"] for r in rows]
            self.conn.execute(
                f"DELETE FROM {table} WHERE id IN ({','.join('?' * len(ids))})", ids
            )
            self.conn.commit()
            return rows

    def delete_last(self, kind: str, n: int = 1) -> list[sqlite3.Row]:
        """Delete the newest ``n`` entries of one kind; returns what went."""
        return self._delete_last(_LOG_TABLES[kind], n)

    def latest_entries(self) -> list[tuple[str, sqlite3.Row]]:
        """The newest entry from each log, newest first.

        Used by bare ``/undo``, which should remove whatever you logged last
        regardless of whether it was a meal, a set or a weigh-in. Entries
        sharing a timestamp fall back to a fixed kind order (sets, meals,
        body weight) because row ids are only unique within their own table.
        """
        with self._lock:
            found = []
            for kind, table in _LOG_TABLES.items():
                row = self.conn.execute(
                    f"SELECT * FROM {table} ORDER BY ts DESC, id DESC LIMIT 1"
                ).fetchone()
                if row:
                    found.append((kind, row))
        priority = {"set": 0, "meal": 1, "weigh": 2}
        found.sort(key=lambda kr: (kr[1]["ts"], -priority[kr[0]]), reverse=True)
        return found

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
