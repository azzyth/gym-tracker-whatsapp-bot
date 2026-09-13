"""Training logging, 1RM, progress, and body-weight trend views."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import config
from .db import DB
from .plateau import (epley_1rm, linear_trend, next_session_plan,
                      plateau_status, session_e1rm, sparkline)


def format_sets_today(db: DB, now: datetime | None = None) -> str:
    now = now or datetime.now()
    start = datetime(now.year, now.month, now.day)
    sets = db.sets_between(start, start + timedelta(days=1))
    if not sets:
        return "No sets logged today. Log one with /set <exercise> <weight> <reps>"
    lines = [f"🏋 *Today's training ({len(sets)} sets)*"]
    for s in sets:
        lines.append(f"• {s['exercise']}: {s['weight']:.1f} {config.UNITS} × {s['reps']}")
    return "\n".join(lines)


def format_1rm(db: DB, exercise: str, weeks: int = 12,
                now: datetime | None = None) -> str:
    now = now or datetime.now()
    rows = db.sets_since(now - timedelta(weeks=weeks), exercise)
    if not rows:
        return f"No sets for '{exercise}' in the last {weeks} weeks."
    best = max(epley_1rm(r["weight"], r["reps"]) for r in rows)
    latest = rows[-1]
    latest_e = epley_1rm(latest["weight"], latest["reps"])
    return (f"Estimated 1RM for *{exercise}* (Epley):\n"
            f"latest {latest_e:.1f} {config.UNITS} · best {best:.1f} {config.UNITS}")


def format_progress(db: DB, exercise: str, weeks: int = 12,
                    now: datetime | None = None) -> str:
    now = now or datetime.now()
    rows = db.sets_since(now - timedelta(weeks=weeks), exercise)
    if not rows:
        return f"No sets for '{exercise}' in the last {weeks} weeks."
    points = session_e1rm(rows)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    slope_day, _ = linear_trend(xs, ys)
    slope_week = slope_day * 7
    current = ys[-1]
    pct = slope_week / current * 100 if current else 0.0
    return "\n".join([
        f"📈 *{exercise}* — last {weeks} weeks ({len(points)} sessions)",
        f"{sparkline(ys)}",
        f"e1RM {ys[0]:.1f} → {current:.1f} {config.UNITS}  ({pct:+.2f}%/week)",
    ])


def format_plateau(db: DB, exercise: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    rows = db.sets_since(now - timedelta(weeks=config.PLATEAU_WINDOW_WEEKS), exercise)
    result = plateau_status(rows, exercise, now)
    flag = "🚨" if result.is_plateau else "✅"
    return "\n".join([
        f"{flag} *{exercise}* plateau check",
        f"sessions: {result.n_sessions} · e1RM now {result.current_e1rm:.1f} "
        f"{config.UNITS} (best {result.best_e1rm:.1f})",
        f"trend: {result.trend.pct_change_per_week:+.2f}%/week",
        result.advice,
    ])


def format_plan(db: DB, exercise: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    rows = db.sets_since(now - timedelta(days=30), exercise)
    result = next_session_plan(rows, exercise)
    return f"🗓 *Plan for {exercise}*\n{result.suggestion}"


def format_weight(db: DB, weeks: int = 8, now: datetime | None = None) -> str:
    now = now or datetime.now()
    rows = db.bodyweight_between(now - timedelta(weeks=weeks), now + timedelta(days=1))
    if not rows:
        return "No body weight logged yet. Log with /weigh <kg>"
    ys = [r["kg"] for r in rows]
    xs = [r["ts"] for r in rows]
    days = [datetime.fromisoformat(t).timestamp() / 86400.0 for t in xs]
    slope_day, _ = linear_trend(days, ys)
    slope_week = slope_day * 7
    trend = "gaining" if slope_week > 0.1 else ("cutting" if slope_week < -0.1 else "stable")
    return "\n".join([
        f"⚖ *Body weight — last {weeks} weeks ({len(rows)} entries)*",
        f"{sparkline(ys)}",
        f"now {ys[-1]:.1f} {config.UNITS} · {trend} ({slope_week:+.2f} {config.UNITS}/week)",
    ])
