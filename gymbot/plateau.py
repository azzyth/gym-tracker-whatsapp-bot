"""The "machine learning" heart of the bot.

Implemented from scratch (pure Python) on purpose — small, transparent,
and dependency-free:

- ``epley_1rm``        — classic 1-rep-max estimate.
- ``linear_trend``     — ordinary least-squares slope/intercept.
- ``plateau_status``   — fits e1RM over time and flags stagnation.
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


def _sparkline(values: list[float], width: int = 20) -> str:
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        return "—" * min(len(values), width)
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
    return [(datetime.fromisoformat(day).timestamp() / 86400.0, v)
            for day, v in sorted(by_day.items())]


def plateau_status(rows: Iterable, exercise: str,
                   now: Optional[datetime] = None) -> PlateauResult:
    """Fit e1RM over the recent window and decide whether the lift is stalled.

    Rules (easy to tune in ``config``):

    - fewer than ``PLATEAU_MIN_SESSIONS`` -> not enough data
    - slope (as % of current e1RM per week) below threshold -> plateau
    - otherwise -> progressing
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
        advice = (
            f"'{exercise}' has stalled — recent trend {recent_pct:+.2f}%/week "
            f"(overall {pct_week:+.2f}%/week across {len(points)} sessions). "
            f"Try a deload week (~60% of your current {current:.1f} "
            f"{config.UNITS}), then resume and add volume. If body weight or "
            f"calories are dropping (check /week), eat closer to your target — "
            f"a plateau is often a recovery problem."
        )
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
