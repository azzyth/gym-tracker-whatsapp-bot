"""Nutrition logging and summaries."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from . import config
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


def format_today(db: DB, now: datetime | None = None) -> str:
    now = now or datetime.now()
    t = today_totals(db, now)
    target = db.get_diet_target()
    lines = [
        f"🍽 *Today's nutrition*",
        f"kcal   {t.kcal:6.0f} / {target.kcal:.0f}  ({_pct(t.kcal, target.kcal)})",
        f"protein {t.protein:5.0f}g / {target.protein_g:.0f}g  ({_pct(t.protein, target.protein_g)})",
        f"carbs   {t.carbs:5.0f}g / {target.carbs_g:.0f}g  ({_pct(t.carbs, target.carbs_g)})",
        f"fat     {t.fat:5.0f}g / {target.fat_g:.0f}g  ({_pct(t.fat, target.fat_g)})",
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


def _pct(actual: float, target: float) -> str:
    if target <= 0:
        return "—"
    return f"{actual / target * 100:.0f}%"
