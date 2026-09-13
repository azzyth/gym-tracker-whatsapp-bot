"""Tests for the GymBot core — run with the standard library only:

    python -m unittest discover -s tests -v

No third-party packages are required for the core.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta

from gymbot import commands, plateau
from gymbot.db import DB


class TestMath(unittest.TestCase):
    def test_epley_1rm(self):
        self.assertAlmostEqual(plateau.epley_1rm(100, 10), 100 * (1 + 10 / 30))

    def test_linear_trend_flat(self):
        xs = [0, 1, 2, 3]
        ys = [80, 80, 80, 80]
        slope, intercept = plateau.linear_trend(xs, ys)
        self.assertAlmostEqual(slope, 0.0)
        self.assertAlmostEqual(intercept, 80.0)

    def test_linear_trend_rising(self):
        xs = [0, 1, 2, 3]
        ys = [100, 102, 104, 106]
        slope, _ = plateau.linear_trend(xs, ys)
        self.assertAlmostEqual(slope, 2.0)


class TestPlateau(unittest.TestCase):
    def _rows(self, weights):
        rows = []
        base = datetime(2026, 1, 5)
        for i, w in enumerate(weights):
            rows.append({
                "ts": (base + timedelta(weeks=i)).isoformat(),
                "weight": w,
                "reps": 8,
            })
        return rows

    def test_stalled_lift_detected(self):
        # flat then slightly down -> plateau
        result = plateau.plateau_status(self._rows([80, 82, 84, 84, 83]), "bench")
        self.assertTrue(result.is_plateau)
        self.assertIn("bench", result.exercise)

    def test_progressing_lift_not_flagged(self):
        result = plateau.plateau_status(self._rows([100, 105, 110, 115, 120]), "squat")
        self.assertFalse(result.is_plateau)

    def test_insufficient_data(self):
        result = plateau.plateau_status(self._rows([80, 82]), "bench")
        self.assertFalse(result.is_plateau)
        self.assertIn("at least", result.advice.lower())


class TestDoubleProgression(unittest.TestCase):
    def _rows(self, weight, reps):
        return [{"ts": datetime(2026, 1, 1).isoformat(), "weight": weight, "reps": reps}]

    def test_top_of_range_adds_weight(self):
        r = plateau.next_session_plan(self._rows(80, 12), "bench")
        self.assertGreater(r.last_weight, 0)
        self.assertIn("add weight", r.suggestion)

    def test_in_range_adds_rep(self):
        r = plateau.next_session_plan(self._rows(80, 10), "bench")
        self.assertIn("same", r.suggestion)

    def test_below_range_backs_off(self):
        r = plateau.next_session_plan(self._rows(80, 5), "bench")
        self.assertIn("Back off", r.suggestion)


class TestCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = DB(self.tmp.name)
        self.now = datetime(2026, 2, 2, 12, 0, 0)

    def tearDown(self):
        self.db.close()

    def test_eat_and_today(self):
        out = commands.handle(self.db, "/eat chicken rice 550 40 60 12", now=self.now)
        self.assertIn("Logged", out)
        today = commands.handle(self.db, "/today", now=self.now)
        self.assertIn("550", today)
        self.assertIn("protein", today)

    def test_set_and_1rm(self):
        commands.handle(self.db, "/set bench press 80 10", now=self.now)
        one_rm = commands.handle(self.db, "/1rm bench press", now=self.now)
        self.assertIn("bench press", one_rm)

    def test_target_roundtrip(self):
        commands.handle(self.db, "/target 2200 140 200 60", now=self.now)
        out = commands.handle(self.db, "/target", now=self.now)
        self.assertIn("2200", out)

    def test_demo_and_plateau(self):
        out = commands.handle(self.db, "/demo", now=self.now)
        self.assertIn("Seeded", out)
        p = commands.handle(self.db, "/plateau bench press", now=self.now)
        self.assertIn("bench press", p)
        # demo bench stalls by week 8 -> plateau should be flagged
        self.assertTrue(p.strip().startswith("🚨"))


if __name__ == "__main__":
    unittest.main()
