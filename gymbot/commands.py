"""Command parsing and dispatch.

Shared by the CLI and the WhatsApp adapter: both call ``handle()`` with
the raw text a user typed and get a formatted string back.

Parsing is done right-to-left so names like ``"chicken rice"`` or
``"bench press"`` work without requiring quotes: trailing numbers are
treated as the numeric arguments, everything before them is the name.
"""
from __future__ import annotations

import shlex
from datetime import datetime, timedelta

from . import config, food, workout
from .db import DB, normalize_exercise


def _is_number(token: str) -> bool:
    try:
        float(token)
        return True
    except ValueError:
        return False


def _parse_food(db: DB, args: list[str], now: datetime) -> str:
    """/eat <name> <kcal> [protein] [carbs] [fat]"""
    nums: list[float] = []
    while args and _is_number(args[-1]):
        nums.insert(0, float(args.pop()))
    name = " ".join(args).strip()
    if not name or not nums:
        return "Usage: /eat <name> <kcal> [protein] [carbs] [fat]"
    kcal = nums[0]
    protein = nums[1] if len(nums) > 1 else 0.0
    carbs = nums[2] if len(nums) > 2 else 0.0
    fat = nums[3] if len(nums) > 3 else 0.0
    db.log_meal(name, kcal, protein, carbs, fat, ts=now.isoformat(timespec="seconds"))
    return (f"✅ Logged *{name}*: {kcal:.0f} kcal · {protein:.0f}p · "
            f"{carbs:.0f}c · {fat:.0f}f")


def _parse_set(db: DB, args: list[str], now: datetime) -> str:
    """/set <exercise> <weight> <reps> [reps...]"""
    nums: list[int] = []
    while args and _is_number(args[-1]):
        nums.insert(0, int(float(args.pop())))
    exercise = normalize_exercise(" ".join(args))
    if not exercise or len(nums) < 2:
        return "Usage: /set <exercise> <weight> <reps> [more reps...]"
    weight, reps = nums[0], nums[1:]
    if weight <= 0 or any(r <= 0 for r in reps):
        return "Weight and reps must be positive."
    for r in reps:
        db.log_set(exercise, float(weight), r, ts=now.isoformat(timespec="seconds"))
    return f"✅ *{exercise}*: {weight:.1f} {config.UNITS} × {', '.join(map(str, reps))}"


def _parse_target(db: DB, args: list[str]) -> str:
    if not args:
        t = db.get_diet_target()
        return (f"Current targets: {t.kcal:.0f} kcal · {t.protein_g:.0f}g protein · "
                f"{t.carbs_g:.0f}g carbs · {t.fat_g:.0f}g fat")
    try:
        vals = [float(a) for a in args[:4]]
    except ValueError:
        return "Usage: /target [kcal protein carbs fat]"
    while len(vals) < 4:
        vals.append(0.0)
    target = config.DietTarget(kcal=vals[0], protein_g=vals[1],
                               carbs_g=vals[2], fat_g=vals[3])
    db.set_diet_target(target)
    return (f"Targets set: {vals[0]:.0f} kcal · {vals[1]:.0f}g protein · "
            f"{vals[2]:.0f}g carbs · {vals[3]:.0f}g fat")


def _parse_progress(db: DB, args: list[str], now: datetime) -> str:
    if not args:
        return "Usage: /progress <exercise> [weeks]"
    weeks = 12
    if args[-1].isdigit():
        weeks = int(args[-1])
        args = args[:-1]
    exercise = normalize_exercise(" ".join(args))
    if not exercise:
        return "Usage: /progress <exercise> [weeks]"
    return workout.format_progress(db, exercise, weeks, now=now)


def handle(db: DB, text: str, now: datetime | None = None) -> str:
    """Route one incoming message to the right handler."""
    now = now or datetime.now()
    text = text.strip()
    if not text.startswith("/"):
        return "Send a command starting with / — try /help"

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    raw_args = parts[1] if len(parts) > 1 else ""

    try:
        args = shlex.split(raw_args) if raw_args else []
    except ValueError:
        args = raw_args.split()

    if cmd == "/help":
        return config.HELP_TEXT

    if cmd == "/eat":
        return _parse_food(db, args, now)

    if cmd == "/today":
        return food.format_today(db, now)

    if cmd == "/week":
        return food.format_week(db, now)

    if cmd == "/target":
        return _parse_target(db, args)

    if cmd == "/set":
        return _parse_set(db, args, now)

    if cmd == "/sets":
        return workout.format_sets_today(db, now)

    if cmd == "/weigh":
        if not args:
            return "Usage: /weigh <kg>"
        try:
            kg = float(args[0])
        except ValueError:
            return "Usage: /weigh <kg>"
        db.log_bodyweight(kg, ts=now.isoformat(timespec="seconds"))
        return f"✅ Body weight logged: {kg:.1f} {config.UNITS}"

    if cmd == "/weight":
        return workout.format_weight(db, now=now)

    if cmd == "/1rm":
        exercise = normalize_exercise(" ".join(args))
        if not exercise:
            return "Usage: /1rm <exercise>"
        return workout.format_1rm(db, exercise, now=now)

    if cmd == "/progress":
        return _parse_progress(db, args, now)

    if cmd == "/plateau":
        exercise = normalize_exercise(" ".join(args))
        if not exercise:
            exs = db.exercises()
            if not exs:
                return "No exercises logged yet. Try /demo first."
            return "\n\n".join(workout.format_plateau(db, ex, now=now) for ex in exs)
        return workout.format_plateau(db, exercise, now=now)

    if cmd == "/plan":
        exercise = normalize_exercise(" ".join(args))
        if not exercise:
            return "Usage: /plan <exercise>"
        return workout.format_plan(db, exercise, now=now)

    if cmd == "/demo":
        _seed_demo(db, now)
        return ("✅ Seeded 8 weeks of demo data (training + food + body weight). "
                "Now try /plateau bench press, /progress squat, /today, /week, /weight.")

    return f"Unknown command '{cmd}'. Try /help"


def _seed_demo(db: DB, now: datetime) -> None:
    """Insert a realistic 8-week history so every command has data to show."""
    # bench press plateaus hard after week 4; squat keeps climbing.
    bench = [80, 82.5, 85, 87.5, 88.75, 89, 89, 89]     # stalls
    squat = [100, 102.5, 105, 107.5, 110, 112.5, 115, 117.5]  # climbs
    dead = [120, 122.5, 125, 127.5, 130, 132.5, 135, 137.5]

    for wk in range(8):
        d = now - timedelta(weeks=8 - wk)
        ts = d.isoformat(timespec="seconds")
        db.log_set("squat", squat[wk], 10, ts=ts)
        db.log_set("squat", squat[wk], 9, ts=ts)
        db.log_set("bench press", bench[wk], 9, ts=ts)
        db.log_set("bench press", bench[wk], 8, ts=ts)
        db.log_set("deadlift", dead[wk], 6, ts=ts)
        db.log_bodyweight(80.5 - wk * 0.4, ts=ts)

    # one week of meals so /today and /week work
    for i in range(7):
        d = now - timedelta(days=i)
        db.log_meal("demo meal", 600, 45, 65, 18, ts=d.isoformat(timespec="seconds"))
