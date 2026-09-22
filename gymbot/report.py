"""The weekly report.

One builder, two consumers: ``/report`` on demand and the scheduled Sunday
push from ``bot.py``. Both render this same string, so the content is
testable without a clock, a WhatsApp session, or a scheduler.

Every number comes from a module that already computes it — nothing here
introduces a second definition of "best e1RM this week".
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import config, food
from .db import DB
from .plateau import bodyweight_trend, plateau_status, session_e1rm


def format_weekly_report(db: DB, now: datetime | None = None) -> str:
    now = now or datetime.now()
    start = datetime(now.year, now.month, now.day) - timedelta(days=6)
    end = now + timedelta(days=1)

    lines = [f"📊 *Weekly report — {start:%d %b} to {now:%d %b}*"]

    # --- nutrition ---------------------------------------------------------
    lines += ["", "🍽 *Nutrition (7-day average)*"]
    meals = db.meals_between(start, end)
    target = db.get_diet_target()
    if meals:
        t = food.totals_for(meals)
        lines.append(
            f"{t.kcal / 7:.0f} kcal · {t.protein / 7:.0f}g protein"
            f"   ({food.pct(t.kcal / 7, target.kcal)} / "
            f"{food.pct(t.protein / 7, target.protein_g)} of target)"
        )
    else:
        lines.append("No meals logged this week.")

    # --- training ----------------------------------------------------------
    lines += ["", "🏋 *Training (7 days)*"]
    sets = db.sets_between(start, end)
    if not sets:
        lines.append("No sets logged this week.")
    else:
        by_exercise = {}
        for s in sets:
            by_exercise.setdefault(s["exercise"], []).append(s)
        lines.append(f"{len(sets)} sets across {len(by_exercise)} lifts")
        prior_start = start - timedelta(days=7)
        ranked = sorted(by_exercise.items(), key=lambda kv: len(kv[1]), reverse=True)
        for exercise, rows in ranked:
            best = max(p[1] for p in session_e1rm(rows))
            delta = ""
            prior = db.sets_between(prior_start, start, exercise)
            if prior:
                prior_best = max(p[1] for p in session_e1rm(prior))
                delta = f" ({best - prior_best:+.1f})"
            # Flag against the full plateau window, not the last 7 days — two
            # sessions in a week is never enough to call a stall.
            history = db.sets_since(
                now - timedelta(weeks=config.PLATEAU_WINDOW_WEEKS), exercise
            )
            flag = "  ⚠️ stalled" if plateau_status(history, exercise, now).is_plateau else ""
            lines.append(f"• {exercise}: {len(rows)} sets · best e1RM "
                         f"{best:.1f} {config.UNITS}{delta}{flag}")

    # --- body weight -------------------------------------------------------
    lines += ["", "⚖ *Body weight*"]
    weights = db.bodyweight_between(start, end)
    if not weights:
        lines.append("No weigh-ins this week.")
    else:
        slope, trend = bodyweight_trend(weights)
        lines.append(f"{weights[-1]['kg']:.1f} {config.UNITS} · {trend} "
                     f"({slope:+.2f} {config.UNITS}/week)")

    # --- nudge -------------------------------------------------------------
    tracked = set(db.exercises())
    untracked = [e for e in config.DEFAULT_EXERCISES if e not in tracked]
    if tracked and len(untracked) > len(config.DEFAULT_EXERCISES) // 2:
        listed = ", ".join(untracked[:5])
        more = f" (+{len(untracked) - 5} more)" if len(untracked) > 5 else ""
        lines += ["", f"🗒 Nothing logged yet for: {listed}{more}"]

    return "\n".join(lines)
