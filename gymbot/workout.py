"""Training logging, 1RM, progress, and body-weight trend views."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import config, food
from .db import DB
from .plateau import (bodyweight_trend, epley_1rm, linear_trend,
                      next_session_plan, plateau_status, session_e1rm, sparkline)


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
        f"{sparkline(ys, config.SPARKLINE_WIDTH)}",
        f"e1RM {ys[0]:.1f} → {current:.1f} {config.UNITS}  ({pct:+.2f}%/week)",
    ])


def format_plateau(db: DB, exercise: str, now: datetime | None = None,
                   show_evidence: bool = True) -> str:
    """Plateau verdict for one lift.

    ``show_evidence=False`` is for the "check every lift" view, where the same
    food and body-weight numbers would otherwise be repeated per exercise —
    the advice still names them, so nothing is lost.
    """
    now = now or datetime.now()
    rows = db.sets_since(now - timedelta(weeks=config.PLATEAU_WINDOW_WEEKS), exercise)
    context = food.nutrition_context(db, now=now)
    result = plateau_status(rows, exercise, now, context=context)
    flag = "🚨" if result.is_plateau else "✅"
    lines = [
        f"{flag} *{exercise}* plateau check",
        f"sessions: {result.n_sessions} · e1RM now {result.current_e1rm:.1f} "
        f"{config.UNITS} (best {result.best_e1rm:.1f})",
        f"trend: {result.trend.pct_change_per_week:+.2f}%/week",
    ]
    # Show the numbers the verdict was drawn from, so the advice is auditable
    # instead of just asserted.
    if show_evidence and context.has_food:
        lines.append(
            f"nutrition ({context.days}d): {context.avg_kcal:.0f} kcal avg "
            f"({context.kcal_pct:.0f}% of {context.target_kcal:.0f}) · "
            f"protein {context.avg_protein:.0f}g ({context.protein_pct:.0f}%)"
        )
    if show_evidence and context.has_weight:
        lines.append(
            f"body weight: {context.weight_trend} "
            f"({context.weight_slope_kg_week:+.2f} {config.UNITS}/week)"
        )
    lines.append(result.advice)
    return "\n".join(lines)


def format_prs(db: DB) -> str:
    """All-time best estimated 1RM per lift, strongest first."""
    rows = db.all_sets()
    if not rows:
        return "No sets logged yet. Log one with /set <exercise> <weight> <reps>"

    best: dict[str, tuple[float, object]] = {}
    for r in rows:
        e = epley_1rm(r["weight"], r["reps"])
        if r["exercise"] not in best or e > best[r["exercise"]][0]:
            best[r["exercise"]] = (e, r)

    ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)
    lines = [f"🏆 *Personal records* — {len(ranked)} lifts, est. 1RM"]
    for exercise, (e, r) in ranked[:config.PRS_LIMIT]:
        lines.append(f"• {exercise}: {e:.1f} {config.UNITS} "
                     f"({r['weight']:.1f}×{r['reps']} on {r['ts'][:10]})")
    remaining = len(ranked) - config.PRS_LIMIT
    if remaining > 0:
        lines.append(f"… and {remaining} more")
    return "\n".join(lines)


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
    slope_week, trend = bodyweight_trend(rows)
    return "\n".join([
        f"⚖ *Body weight — last {weeks} weeks ({len(rows)} entries)*",
        f"{sparkline(ys, config.SPARKLINE_WIDTH)}",
        f"now {ys[-1]:.1f} {config.UNITS} · {trend} ({slope_week:+.2f} {config.UNITS}/week)",
    ])
