"""Tests for the GymBot core — run with the standard library only:

    python -m unittest discover -s tests -v

No third-party packages are required for the core.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta

from gymbot import commands, config, food, plateau
from gymbot.db import DB


class TempDBTest(unittest.TestCase):
    """Base for tests that need a throwaway database."""

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.path = tmp.name
        self.db = DB(self.path)
        self.now = datetime(2026, 2, 2, 12, 0, 0)

    def tearDown(self):
        self.db.close()
        os.unlink(self.path)

    def say(self, text: str, now: datetime | None = None) -> str:
        """Send one command the way the CLI and WhatsApp adapters do."""
        return commands.handle(self.db, text, now=now or self.now)

    def rows_between(self, table: str) -> int:
        """How many entries one of the log tables holds today."""
        start, end = self.now - timedelta(days=1), self.now + timedelta(days=1)
        if table == "meals":
            return len(self.db.meals_between(start, end))
        if table == "sets":
            return len(self.db.sets_between(start, end))
        return len(self.db.bodyweight_between(start, end))


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

    def test_no_context_keeps_the_generic_advice(self):
        result = plateau.plateau_status(self._rows([80, 82, 84, 84, 83]), "bench")
        self.assertIsNone(result.context)


class TestBodyweightTrend(unittest.TestCase):
    def _rows(self, kgs):
        base = datetime(2026, 1, 5)
        return [{"ts": (base + timedelta(weeks=i)).isoformat(), "kg": kg}
                for i, kg in enumerate(kgs)]

    def test_gaining(self):
        slope, trend = plateau.bodyweight_trend(self._rows([80.0, 80.5, 81.0]))
        self.assertEqual(trend, "gaining")
        self.assertGreater(slope, 0)

    def test_cutting(self):
        slope, trend = plateau.bodyweight_trend(self._rows([81.0, 80.5, 80.0]))
        self.assertEqual(trend, "cutting")
        self.assertLess(slope, 0)

    def test_stable(self):
        _, trend = plateau.bodyweight_trend(self._rows([80.0, 80.05, 80.0]))
        self.assertEqual(trend, "stable")

    def test_single_entry_is_stable(self):
        self.assertEqual(plateau.bodyweight_trend(self._rows([80.0])), (0.0, "stable"))


class TestSparkline(unittest.TestCase):
    def test_long_series_is_downsampled_to_width(self):
        bars = plateau.sparkline([float(i) for i in range(100)], 20)
        self.assertEqual(len(bars), 20)

    def test_tip_stays_the_latest_value(self):
        bars = plateau.sparkline([float(i) for i in range(100)], 20)
        self.assertEqual(bars[-1], "█")

    def test_short_series_is_untouched(self):
        self.assertEqual(len(plateau.sparkline([80.0, 81.0, 82.0], 20)), 3)

    def test_flat_series(self):
        self.assertEqual(plateau.sparkline([80.0, 80.0, 80.0], 20), "———")


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


class TestCommands(TempDBTest):
    def test_eat_and_today(self):
        out = self.say("/eat chicken rice 550 40 60 12")
        self.assertIn("Logged", out)
        today = self.say("/today")
        self.assertIn("550", today)
        self.assertIn("protein", today)

    def test_set_and_1rm(self):
        self.say("/set bench press 80 10")
        one_rm = self.say("/1rm bench press")
        self.assertIn("bench press", one_rm)

    def test_target_roundtrip(self):
        self.say("/target 2200 140 200 60")
        out = self.say("/target")
        self.assertIn("2200", out)

    def test_demo_and_plateau(self):
        out = self.say("/demo")
        self.assertIn("Seeded", out)
        p = self.say("/plateau bench press")
        self.assertIn("bench press", p)
        # demo bench stalls by week 8 -> plateau should be flagged
        self.assertTrue(p.strip().startswith("🚨"))


class TestPlateauNutritionJoin(TempDBTest):
    """The plateau verdict has to name the cause, not list every possibility."""

    def _stalled_lift(self):
        for i, weight in enumerate([80.0, 82.0, 84.0, 84.0, 84.0]):
            self.db.log_set("bench press", weight, 8,
                            ts=(self.now - timedelta(weeks=4 - i)).isoformat())

    def test_under_eating_is_named_as_the_cause(self):
        self._stalled_lift()
        self.db.log_meal("rice", 1000, 40, 100, 20, ts=self.now.isoformat())
        out = self.say("/plateau bench press")
        self.assertIn("fuel problem", out)
        self.assertIn("2500 kcal target", out)

    def test_cutting_bodyweight_is_named_when_food_looks_fine(self):
        self._stalled_lift()
        self.say("/target 10 10 10 10")
        self.db.log_meal("rice", 1000, 40, 100, 20, ts=self.now.isoformat())
        self.db.log_bodyweight(80.0, ts=(self.now - timedelta(days=10)).isoformat())
        self.db.log_bodyweight(79.6, ts=(self.now - timedelta(days=1)).isoformat())
        out = self.say("/plateau bench press")
        self.assertIn("trending down", out)
        self.assertIn("on a cut", out)

    def test_fuelled_and_stable_points_at_programming(self):
        self._stalled_lift()
        self.say("/target 10 10 10 10")
        self.db.log_meal("rice", 1000, 40, 100, 20, ts=self.now.isoformat())
        self.db.log_bodyweight(80.0, ts=(self.now - timedelta(days=10)).isoformat())
        self.db.log_bodyweight(80.0, ts=(self.now - timedelta(days=1)).isoformat())
        out = self.say("/plateau bench press")
        self.assertIn("programming problem", out)

    def test_no_food_or_weight_data_keeps_the_generic_advice(self):
        self._stalled_lift()
        self.assertIn("check /week", self.say("/plateau bench press"))

    def test_the_numbers_behind_the_verdict_are_shown(self):
        self._stalled_lift()
        self.db.log_meal("rice", 1000, 40, 100, 20, ts=self.now.isoformat())
        self.db.log_bodyweight(80.0, ts=(self.now - timedelta(days=10)).isoformat())
        self.db.log_bodyweight(79.5, ts=(self.now - timedelta(days=1)).isoformat())
        out = self.say("/plateau bench press")
        self.assertIn("nutrition (14d)", out)
        self.assertIn("body weight:", out)

    def test_progressing_lift_is_not_lectured_about_food(self):
        for i, weight in enumerate([80.0, 85.0, 90.0, 95.0, 100.0]):
            self.db.log_set("squat", weight, 8,
                            ts=(self.now - timedelta(weeks=4 - i)).isoformat())
        out = self.say("/plateau squat")
        self.assertIn("no deload needed", out)

    def test_empty_context_does_not_crash(self):
        context = food.nutrition_context(self.db, now=self.now)
        self.assertFalse(context.has_food)
        self.assertFalse(context.has_weight)
        self.assertEqual(context.avg_kcal, 0.0)
        self.assertEqual(context.kcal_pct, 0.0)

    def test_checking_every_lift_does_not_repeat_the_evidence(self):
        self._stalled_lift()
        self.db.log_set("squat", 100.0, 8, ts=self.now.isoformat())
        self.db.log_meal("rice", 1000, 40, 100, 20, ts=self.now.isoformat())
        out = self.say("/plateau")
        self.assertNotIn("nutrition (14d)", out)
        # the verdict itself still names the cause
        self.assertIn("fuel problem", out)

    def test_food_only_context_does_not_invent_a_weight_trend(self):
        self._stalled_lift()
        self.say("/target 10 10 10 10")
        self.db.log_meal("rice", 1000, 40, 100, 20, ts=self.now.isoformat())
        out = self.say("/plateau bench press")
        self.assertIn("programming problem", out)
        self.assertNotIn("body weight", out)

    def test_weight_only_context_does_not_invent_protein(self):
        self._stalled_lift()
        self.db.log_bodyweight(80.0, ts=(self.now - timedelta(days=10)).isoformat())
        self.db.log_bodyweight(79.6, ts=(self.now - timedelta(days=1)).isoformat())
        out = self.say("/plateau bench press")
        self.assertIn("on a cut", out)
        self.assertNotIn("protein near", out)


class TestUndo(TempDBTest):
    def test_bare_undo_removes_the_newest_of_any_kind(self):
        self.say("/eat rice 500 30 60 10")
        self.say("/set bench press 80 8", now=self.now + timedelta(minutes=5))
        out = self.say("/undo")
        self.assertIn("Removed last set", out)
        self.assertEqual(self.db.all_sets(), [])
        self.assertEqual(self.rows_between("meals"), 1)

    def test_bare_undo_prefers_the_meal_when_it_is_newest(self):
        self.say("/set bench press 80 8")
        self.say("/eat rice 500 30 60 10", now=self.now + timedelta(minutes=5))
        out = self.say("/undo")
        self.assertIn("Removed last meal", out)
        self.assertIn("rice", out)
        self.assertEqual(len(self.db.all_sets()), 1)

    def test_undo_can_target_a_log_and_a_count(self):
        for reps in (10, 9, 8):
            self.say(f"/set squat 100 {reps}")
        out = self.say("/undo set 2")
        self.assertIn("last 2", out)
        self.assertEqual([r["reps"] for r in self.db.all_sets("squat")], [10])

    def test_undo_a_weigh_in(self):
        self.say("/weigh 78.5")
        self.assertIn("Removed weigh-in", self.say("/undo weigh"))
        self.assertEqual(self.rows_between("bodyweight"), 0)

    def test_undo_on_an_empty_database(self):
        self.assertIn("Nothing to undo", self.say("/undo"))

    def test_undo_with_nothing_of_that_kind(self):
        self.assertIn("no meal entries", self.say("/undo meal"))

    def test_undo_with_a_count_needs_a_kind(self):
        self.say("/eat rice 500")
        self.assertIn("Say which log", self.say("/undo 3"))
        self.assertEqual(self.rows_between("meals"), 1)

    def test_undo_rejects_nonsense(self):
        self.assertIn("Usage", self.say("/undo bananas"))


class TestPrs(TempDBTest):
    def test_ranked_by_estimated_1rm(self):
        self.say("/set squat 100 5")          # e1RM ~116.7
        self.say("/set bench press 80 10")    # e1RM ~106.7
        out = self.say("/prs")
        self.assertIn("2 lifts", out)
        self.assertLess(out.index("squat"), out.index("bench press"))

    def test_empty(self):
        self.assertIn("No sets logged yet", self.say("/prs"))

    def test_capped(self):
        for i in range(config.PRS_LIMIT + 1):
            self.db.log_set(f"lift {i}", 100, 5)
        self.assertIn("and 1 more", self.say("/prs"))


class TestPrDetection(TempDBTest):
    def test_first_log_is_not_a_pr(self):
        self.assertNotIn("New PR", self.say("/set bench press 80 10"))

    def test_beating_the_record_is_flagged(self):
        self.say("/set bench press 80 10")
        out = self.say("/set bench press 82.5 10", now=self.now + timedelta(days=1))
        self.assertIn("New PR", out)

    def test_a_weaker_session_is_not_flagged(self):
        self.say("/set bench press 100 5")
        out = self.say("/set bench press 80 5", now=self.now + timedelta(days=1))
        self.assertNotIn("New PR", out)


class TestRename(TempDBTest):
    def test_arrow_form(self):
        self.say("/set bench-press 80 8")
        out = self.say("/rename bench-press -> bench press")
        self.assertIn("Renamed", out)
        self.assertIn("1 set)", out)
        self.assertEqual(self.db.exercises(), ["bench press"])

    def test_quoted_form(self):
        self.say("/set bench-press 80 8")
        self.assertIn("Renamed", self.say('/rename "bench-press" "bench press"'))

    def test_merging_into_an_existing_lift(self):
        self.say("/set bench press 80 8")
        self.say("/set bench-press 85 5")
        out = self.say("/rename bench-press -> bench press")
        self.assertIn("Merged", out)
        self.assertEqual(len(self.db.all_sets("bench press")), 2)
        self.assertEqual(self.db.exercises(), ["bench press"])

    def test_no_op_is_rejected(self):
        self.say("/set bench press 80 8")
        self.assertIn("already named that", self.say("/rename bench press -> bench press"))

    def test_unknown_lift(self):
        self.assertIn("No sets logged", self.say("/rename nope -> other"))

    def test_unparseable_input(self):
        self.assertIn("Usage", self.say("/rename too many words here"))


class TestSetOrdering(TempDBTest):
    def test_same_second_sets_keep_their_order(self):
        self.say("/set bench press 80 10 9 8")
        rows = self.db.all_sets("bench press")
        self.assertEqual([r["reps"] for r in rows], [10, 9, 8])

    def test_plan_uses_the_last_set_not_an_arbitrary_one(self):
        self.say("/set bench press 80 10 9 8")
        # last set was 8 reps -> inside the 8-12 range -> push for 9, not 11
        self.assertIn("push for 9", self.say("/plan bench press"))


class TestWeeklyReport(TempDBTest):
    def test_report_covers_every_section(self):
        self.db.log_meal("rice", 600, 40, 60, 15,
                         ts=(self.now - timedelta(days=1)).isoformat())
        self.db.log_set("squat", 100, 5, ts=(self.now - timedelta(days=1)).isoformat())
        self.db.log_bodyweight(80.0, ts=(self.now - timedelta(days=2)).isoformat())
        self.db.log_bodyweight(79.8, ts=(self.now - timedelta(days=1)).isoformat())
        out = self.say("/report")
        self.assertIn("Weekly report", out)
        self.assertIn("Nutrition", out)
        self.assertIn("Training", out)
        self.assertIn("squat", out)
        self.assertIn("across", out)
        self.assertIn("Body weight", out)
        self.assertIn("cutting", out)

    def test_report_handles_an_empty_week(self):
        out = self.say("/report")
        self.assertIn("No meals logged this week.", out)
        self.assertIn("No sets logged this week.", out)
        self.assertIn("No weigh-ins this week.", out)


class TestValidation(TempDBTest):
    def test_negative_meal_is_rejected(self):
        out = self.say("/eat nasi goreng -500 20 30 10")
        self.assertIn("negative", out.lower())
        self.assertEqual(self.rows_between("meals"), 0)

    def test_absurd_meal_is_rejected(self):
        self.assertIn("typo", self.say("/eat pizza 99999"))
        self.assertEqual(self.rows_between("meals"), 0)

    def test_negative_target_is_rejected(self):
        self.say("/target -1 100 100 50")
        self.assertEqual(self.db.get_diet_target().kcal, config.DietTarget().kcal)

    def test_out_of_range_bodyweight_is_rejected(self):
        for value in ("-5", "9999"):
            self.assertIn("between 0 and", self.say(f"/weigh {value}"))
        self.assertEqual(self.rows_between("bodyweight"), 0)

    def test_absurd_set_is_rejected(self):
        self.assertIn("typo", self.say("/set bench press 80 99999"))
        self.assertEqual(self.db.all_sets(), [])

    def test_ordinary_entries_still_work(self):
        self.assertIn("Logged", self.say("/eat rice 500 30 60 10"))
        self.assertIn("Body weight logged", self.say("/weigh 78.5"))
        self.assertEqual(self.rows_between("meals"), 1)
        self.assertEqual(self.rows_between("bodyweight"), 1)


if __name__ == "__main__":
    unittest.main()
