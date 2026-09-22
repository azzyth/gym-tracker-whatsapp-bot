"""The "machine learning" heart of the bot.

Implemented from scratch (pure Python) on purpose — small, transparent,
and dependency-free:

- ``epley_1rm``        — classic 1-rep-max estimate.
- ``linear_trend``     — ordinary least-squares slope/intercept.
- ``bodyweight_trend`` — kg/week slope, labelled gaining/cutting/stable.
- ``plateau_status``   — fits e1RM over time, flags stagnation, and joins
                         the nutrition context to say *which lever to pull*.
- ``next_session_plan``— double-progression suggestion for hypertrophy.

Everything returns plain dataclasses so the CLI and WhatsApp layers can
format them however they like.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from . import config


@dataclass
class Trend:
    slope_per_week: float
    intercept: float
    n_points: int
    pct_change_per_week: float  # slope as % of current level


@dataclass
class NutritionContext:
    """Recent food and body-weight conditions around a lift.

    Built by ``food.nutrition_context`` and passed into ``plateau_status`` so
    the plateau verdict can name the actual cause. It lives here, next to
    ``PlateauResult``, because it is an *input to the judgement* — that keeps
    this module depending on nothing but ``config`` and the stdlib instead of
    reaching into the storage layer.
    """

    days: int
    avg_kcal: float
    avg_protein: float
    target_kcal: float
    kcal_pct: float
    protein_pct: float
    weight_slope_kg_week: float
    weight_trend: str          # "gaining" | "cutting" | "stable"
    has_food: bool
    has_weight: bool


@dataclass
class PlateauResult:
    exercise: str
    n_sessions: int
    window_weeks: int
    current_e1rm: float
    best_e1rm: float
    trend: Trend
    recent_pct_week: float
    is_plateau: bool
    advice: str
    context: Optional[NutritionContext] = None


@dataclass
class PlanResult:
    exercise: str
    last_weight: float
    last_reps: int
    suggestion: str


def epley_1rm(weight: float, reps: int) -> float:
    """Epley formula: 1RM ~= weight * (1 + reps/30)."""
    if reps <= 0:
        return weight
    return weight * (1.0 + reps / 30.0)


def linear_trend(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Ordinary least squares. Returns (slope, intercept)."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if n == 1 else 0.0)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    slope = num / den if den > 0 else 0.0
    intercept = my - slope * mx
    return slope, intercept


def _days_since_epoch(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp() / 86400.0


def _downsample(values: list[float], width: int) -> list[float]:
    """Average consecutive buckets so the bar never outgrows ``width``.

    A year of sessions would otherwise render a 200-character sparkline into
    a WhatsApp bubble. The last bucket keeps its true value so the tip of the
    bar still means "where you are now".
    """
    if width <= 0 or len(values) <= width:
        return values
    out = []
    for i in range(width):
        start = i * len(values) // width
        end = (i + 1) * len(values) // width
        bucket = values[start:end]
        out.append(sum(bucket) / len(bucket))
    out[-1] = values[-1]
    return out


def _sparkline(values: list[float], width: int = 20) -> str:
    if not values:
        return ""
    values = _downsample(values, width)
    lo, hi = min(values), max(values)
    if hi == lo:
        return "—" * len(values)
    bars = "▁▂▃▄▅▆▇█"
    idx = [int(round((v - lo) / (hi - lo) * (len(bars) - 1))) for v in values]
    return "".join(bars[i] for i in idx)


def session_e1rm(rows: Iterable) -> list[tuple[float, float]]:
    """Group raw sets into (time_days, session-best-e1RM) points.

    A "session" is approximated as a single day: we take the best e1RM of
    that day, which is the right level to track for strength progress.
    """
    by_day: dict[str, float] = {}
    for r in rows:
        day = r["ts"][:10]
        e = epley_1rm(r["weight"], r["reps"])
        by_day[day] = max(by_day.get(day, 0.0), e)
    return [(_days_since_epoch(day), v) for day, v in sorted(by_day.items())]


def bodyweight_trend(rows: Iterable) -> tuple[float, str]:
    """Least-squares body-weight slope in kg/week, plus a label.

    Shared by the /weight view and the plateau nutrition join so both agree
    on what "cutting" means.
    """
    rows = list(rows)
    if len(rows) < 2:
        return 0.0, "stable"
    days = [_days_since_epoch(r["ts"]) for r in rows]
    kgs = [r["kg"] for r in rows]
    slope_week = linear_trend(days, kgs)[0] * 7.0
    if slope_week > config.WEIGHT_TREND_KG_WEEK:
        return slope_week, "gaining"
    if slope_week < -config.WEIGHT_TREND_KG_WEEK:
        return slope_week, "cutting"
    return slope_week, "stable"


def _stalled_advice(exercise: str, current: float, recent_pct: float,
                    pct_week: float, n_sessions: int,
                    context: Optional[NutritionContext]) -> str:
    """Name the most likely cause of a stall instead of listing every option."""
    if context is not None and context.has_food:
        if context.kcal_pct < config.UNDERFED_KCAL_PCT:
            return (
                f"'{exercise}' has stalled ({recent_pct:+.2f}%/week recent) while you "
                f"averaged {context.avg_kcal:.0f} kcal over the last {context.days} days — "
                f"{context.kcal_pct:.0f}% of your {context.target_kcal:.0f} kcal target. "
                f"That is a fuel problem before it is a programming problem: hold the "
                f"deload, eat at target for two weeks, then re-run /plateau."
            )
    if context is not None and context.has_weight and context.weight_trend == "cutting":
        protein = (f", keep protein near {context.avg_protein:.0f}g/day"
                   if context.has_food else "")
        return (
            f"'{exercise}' has stalled ({recent_pct:+.2f}%/week recent) and your body "
            f"weight is trending down {abs(context.weight_slope_kg_week):.2f} "
            f"{config.UNITS}/week. Strength flatlining on a cut is expected — hold the "
            f"deload{protein} and protect your top sets."
        )
    if context is not None and (context.has_food or context.has_weight):
        # Only cite the inputs actually on file: a missing log must not render
        # as "0 kcal" or a flat weight trend.
        known = []
        if context.has_food:
            known.append(f"{context.kcal_pct:.0f}% of calorie target")
        if context.has_weight:
            known.append(f"body weight {context.weight_slope_kg_week:+.2f} "
                         f"{config.UNITS}/week")
        return (
            f"'{exercise}' has stalled ({recent_pct:+.2f}%/week recent, "
            f"{pct_week:+.2f}%/week over {n_sessions} sessions) while your inputs look "
            f"fine — {', '.join(known)}. That makes it a programming problem: deload a "
            f"week (~60% of {current:.1f} {config.UNITS}), then come back and add volume."
        )
    return (
        f"'{exercise}' has stalled — recent trend {recent_pct:+.2f}%/week "
        f"(overall {pct_week:+.2f}%/week across {n_sessions} sessions). "
        f"Try a deload week (~60% of your current {current:.1f} "
        f"{config.UNITS}), then resume and add volume. If body weight or "
        f"calories are dropping (check /week), eat closer to your target — "
        f"a plateau is often a recovery problem."
    )


def plateau_status(rows: Iterable, exercise: str,
                   now: Optional[datetime] = None,
                   context: Optional[NutritionContext] = None) -> PlateauResult:
    """Fit e1RM over the recent window and decide whether the lift is stalled.

    Rules (easy to tune in ``config``):

    - fewer than ``PLATEAU_MIN_SESSIONS`` -> not enough data
    - slope (as % of current e1RM per week) below threshold -> plateau
    - otherwise -> progressing

    Pass ``context`` (from ``food.nutrition_context``) and a stall is explained
    by the food and body-weight numbers rather than a generic checklist.
    """
    now = now or datetime.now()
    points = session_e1rm(rows)
    if len(points) < config.PLATEAU_MIN_SESSIONS:
        return PlateauResult(
            exercise=exercise,
            n_sessions=len(points),
            window_weeks=config.PLATEAU_WINDOW_WEEKS,
            current_e1rm=points[-1][1] if points else 0.0,
            best_e1rm=max(p[1] for p in points) if points else 0.0,
            trend=Trend(0.0, 0.0, len(points), 0.0),
            recent_pct_week=0.0,
            is_plateau=False,
            advice=f"Need at least {config.PLATEAU_MIN_SESSIONS} sessions of "
                   f"'{exercise}' to judge a plateau — keep logging!",
            context=context,
        )

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    slope_day, intercept = linear_trend(xs, ys)          # e1RM per day
    slope_week = slope_day * 7.0
    current = ys[-1]
    pct_week = (slope_week / current * 100.0) if current else 0.0
    best = max(ys)

    # recent trend over the last 3 sessions — a plateau shows up here first,
    # even when the full-window slope is still positive from earlier gains.
    recent = points[-3:]
    if len(recent) >= 2:
        rx = [p[0] for p in recent]
        ry = [p[1] for p in recent]
        r_slope_day, _ = linear_trend(rx, ry)
        recent_pct = (r_slope_day * 7.0) / current * 100.0 if current else 0.0
    else:
        recent_pct = pct_week

    stalled = recent_pct <= 0.0 or pct_week < config.PLATEAU_SLOPE_PCT_WEEK

    if stalled:
        advice = _stalled_advice(exercise, current, recent_pct, pct_week,
                                 len(points), context)
    else:
        advice = (
            f"'{exercise}' is still trending up ({recent_pct:+.2f}%/week recent, "
            f"{pct_week:+.2f}%/week overall). Keep progressing — no deload needed yet."
        )

    return PlateauResult(
        exercise=exercise,
        n_sessions=len(points),
        window_weeks=config.PLATEAU_WINDOW_WEEKS,
        current_e1rm=current,
        best_e1rm=best,
        trend=Trend(slope_week, intercept, len(points), pct_week),
        recent_pct_week=recent_pct,
        is_plateau=stalled,
        advice=advice,
        context=context,
    )


def next_session_plan(rows: Iterable, exercise: str) -> PlanResult:
    """Double progression for hypertrophy.

    - hit (or beat) the top of the rep range  -> add weight, drop to low end
    - inside the range                        -> same weight, add a rep
    - below the range                         -> back off ~10% and rebuild
    """
    lo, hi = config.HYPERTROPHY_REP_RANGE
    if not rows:
        return PlanResult(exercise, 0.0, 0,
                          f"No history for '{exercise}' yet. Log a first session "
                          f"with /set {exercise} <weight> <reps> and I'll plan from there.")

    rows = list(rows)
    last = rows[-1]
    w, r = last["weight"], last["reps"]

    if r >= hi:
        new_w = round((w + config.WEIGHT_INCREMENT) * 2) / 2
        suggestion = (f"Hit {r} reps — time to add weight. Next session: "
                      f"~{new_w:.1f} {config.UNITS} for {lo} reps.")
    elif r >= lo:
        suggestion = (f"Good — {r} reps. Next session: same {w:.1f} {config.UNITS}, "
                      f"push for {r + 1} reps.")
    else:
        back = round(w * 0.9 * 2) / 2
        suggestion = (f"Only {r} reps (below your {lo}–{hi} range). Back off to "
                      f"~{back:.1f} {config.UNITS} and rebuild reps.")
    return PlanResult(exercise, w, r, suggestion)


def sparkline(values: list[float], width: int = 20) -> str:
    """Public helper used by the progress view."""
    return _sparkline(values, width)
