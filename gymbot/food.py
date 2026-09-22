"""Nutrition logging and summaries."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from . import config, plateau
from .db import DB


@dataclass
class DayTotals:
    kcal: float
    protein: float
    carbs: float
    fat: float


def totals_for(meals) -> DayTotals:
    return DayTotals(
        kcal=sum(m["kcal"] for m in meals),
        protein=sum(m["protein"] for m in meals),
        carbs=sum(m["carbs"] for m in meals),
        fat=sum(m["fat"] for m in meals),
    )


def today_totals(db: DB, now: datetime | None = None) -> DayTotals:
    now = now or datetime.now()
    start = datetime(now.year, now.month, now.day)
    return totals_for(db.meals_between(start, start + timedelta(days=1)))


def week_totals(db: DB, now: datetime | None = None) -> DayTotals:
    now = now or datetime.now()
    start = datetime(now.year, now.month, now.day) - timedelta(days=6)
    return totals_for(db.meals_between(start, now + timedelta(days=1)))


def nutrition_context(db: DB, days: int = config.NUTRITION_LOOKBACK_DAYS,
                      now: datetime | None = None) -> "plateau.NutritionContext":
    """Recent intake and body-weight trend, for the plateau cross-reference.

    Averages are over a fixed ``days`` window, not over "days you logged", so
    a week of not logging reads as under-eating rather than as perfect
    adherence — the safer failure for advice you might act on.
    """
    now = now or datetime.now()
    end = now + timedelta(days=1)
    start = now - timedelta(days=days)
    meals = db.meals_between(start, end)
    weights = db.bodyweight_between(start, end)
    target = db.get_diet_target()
    totals = totals_for(meals)
    slope, trend = plateau.bodyweight_trend(weights)
    span = days or 1
    return plateau.NutritionContext(
        days=days,
        avg_kcal=totals.kcal / span,
        avg_protein=totals.protein / span,
        target_kcal=target.kcal,
        kcal_pct=(totals.kcal / span / target.kcal * 100.0) if target.kcal > 0 else 0.0,
        protein_pct=(totals.protein / span / target.protein_g * 100.0)
                    if target.protein_g > 0 else 0.0,
        weight_slope_kg_week=slope,
        weight_trend=trend,
        has_food=bool(meals),
        has_weight=len(weights) >= 2,
    )


def format_today(db: DB, now: datetime | None = None) -> str:
    now = now or datetime.now()
    t = today_totals(db, now)
    target = db.get_diet_target()
    lines = [
        f"🍽 *Today's nutrition*",
        f"kcal   {t.kcal:6.0f} / {target.kcal:.0f}  ({pct(t.kcal, target.kcal)})",
        f"protein {t.protein:5.0f}g / {target.protein_g:.0f}g  ({pct(t.protein, target.protein_g)})",
        f"carbs   {t.carbs:5.0f}g / {target.carbs_g:.0f}g  ({pct(t.carbs, target.carbs_g)})",
        f"fat     {t.fat:5.0f}g / {target.fat_g:.0f}g  ({pct(t.fat, target.fat_g)})",
    ]
    return "\n".join(lines)


def format_week(db: DB, now: datetime | None = None) -> str:
    now = now or datetime.now()
    t = week_totals(db, now)
    target = db.get_diet_target()
    d = 7
    return "\n".join([
        f"📅 *Last 7 days (daily average)*",
        f"kcal   {t.kcal / d:6.0f} / {target.kcal:.0f}",
        f"protein {t.protein / d:5.0f}g / {target.protein_g:.0f}g",
        f"carbs   {t.carbs / d:5.0f}g / {target.carbs_g:.0f}g",
        f"fat     {t.fat / d:5.0f}g / {target.fat_g:.0f}g",
    ])


def pct(actual: float, target: float) -> str:
    if target <= 0:
        return "—"
    return f"{actual / target * 100:.0f}%"
