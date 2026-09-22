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

from . import config, food, report, workout
from .db import DB, normalize_exercise
from .plateau import epley_1rm

# /undo accepts either the table's own word or the one the commands use.
_UNDO_KINDS = {
    "meal": "meal", "food": "meal", "eat": "meal",
    "set": "set", "sets": "set",
    "weigh": "weigh", "weight": "weigh", "bw": "weigh",
}
_UNDO_LABELS = {"meal": "meal", "set": "set", "weigh": "weigh-in"}


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
    if any(n < 0 for n in nums):
        return "Nothing negative here — send that one again."
    kcal = nums[0]
    if kcal > config.MAX_MEAL_KCAL:
        return (f"{kcal:.0f} kcal looks like a typo (max {config.MAX_MEAL_KCAL}). "
                f"Log it as separate meals if it really was that big.")
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
    if weight > config.MAX_SET_WEIGHT or any(r > config.MAX_SET_REPS for r in reps):
        return (f"That looks like a typo — max {config.MAX_SET_WEIGHT:.0f} "
                f"{config.UNITS} and {config.MAX_SET_REPS} reps per set.")

    # Read the record before writing, so a celebration means a real improvement
    # rather than "you logged your first set".
    previous = [epley_1rm(r["weight"], r["reps"]) for r in db.all_sets(exercise)]

    for r in reps:
        db.log_set(exercise, float(weight), r, ts=now.isoformat(timespec="seconds"))

    reply = f"✅ *{exercise}*: {weight:.1f} {config.UNITS} × {', '.join(map(str, reps))}"
    if previous:
        before = max(previous)
        after = max(epley_1rm(weight, r) for r in reps)
        if after > before:
            reply += (f"\n🎉 New PR — {after:.1f} {config.UNITS} est. 1RM "
                      f"(was {before:.1f})")
    return reply


def _parse_target(db: DB, args: list[str]) -> str:
    if not args:
        t = db.get_diet_target()
        return (f"Current targets: {t.kcal:.0f} kcal · {t.protein_g:.0f}g protein · "
                f"{t.carbs_g:.0f}g carbs · {t.fat_g:.0f}g fat")
    try:
        vals = [float(a) for a in args[:4]]
    except ValueError:
        return "Usage: /target [kcal protein carbs fat]"
    if any(v < 0 for v in vals):
        return "Targets can't be negative."
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


def _describe(kind: str, row) -> str:
    """One-line description of a deleted entry, for the undo confirmation."""
    when = row["ts"][:16].replace("T", " ")
    if kind == "meal":
        return f"*{row['name']}* ({row['kcal']:.0f} kcal, {when})"
    if kind == "set":
        return (f"*{row['exercise']}* {row['weight']:.1f} {config.UNITS} "
                f"× {row['reps']} ({when})")
    return f"{row['kg']:.1f} {config.UNITS} ({when})"


def _parse_undo(db: DB, args: list[str]) -> str:
    """/undo [meal|set|weigh] [n]"""
    kind = None
    count = 1
    for arg in args:
        if arg.lower() in _UNDO_KINDS:
            kind = _UNDO_KINDS[arg.lower()]
        elif arg.isdigit():
            count = max(1, int(arg))
        else:
            return "Usage: /undo [meal|set|weigh] [n]"

    if kind is None:
        if count > 1:
            # "the last 3 of anything" has no single sensible meaning, so make
            # the user say which log they mean.
            return "Say which log: /undo meal|set|weigh <n>"
        # Bare /undo removes whatever you logged most recently, whichever log
        # it landed in.
        latest = db.latest_entries()
        if not latest:
            return "Nothing to undo."
        kind, row = latest[0]
        db.delete_last(kind, 1)
        return f"↩️ Removed last {_UNDO_LABELS[kind]}: {_describe(kind, row)}"

    rows = db.delete_last(kind, count)
    label = _UNDO_LABELS[kind]
    if not rows:
        return f"Nothing to undo — no {label} entries logged."
    if len(rows) == 1:
        return f"↩️ Removed {label}: {_describe(kind, rows[0])}"
    return f"↩️ Removed the last {len(rows)} {label} entries."


def _parse_rename(db: DB, raw: str) -> str:
    """/rename <old> -> <new>

    Takes the raw remainder rather than the shlex-split args so a lift name
    with spaces needs no quoting, and falls back to quoted args. This is the
    only thing that rewrites stored history — never the bot on its own.
    """
    raw = raw.strip()
    if not raw:
        return "Usage: /rename <old> -> <new>"
    if "->" in raw:
        old_raw, _, new_raw = raw.partition("->")
    else:
        try:
            parts = shlex.split(raw)
        except ValueError:
            return "Usage: /rename <old> -> <new>"
        if len(parts) != 2:
            return "Usage: /rename <old> -> <new>  (quote a name containing spaces)"
        old_raw, new_raw = parts

    old = normalize_exercise(old_raw)
    new = normalize_exercise(new_raw)
    if not old or not new:
        return "Usage: /rename <old> -> <new>"
    if old == new:
        return f"'{old}' is already named that."

    already_there = new in db.exercises()
    changed = db.rename_exercise(old, new)
    if not changed:
        return f"No sets logged for '{old}'."
    moved = f"{changed} set" + ("s" if changed != 1 else "")
    if already_there:
        return f"🔁 Merged '{old}' into existing '{new}' ({moved})."
    return f"🔁 Renamed '{old}' → '{new}' ({moved})."


def handle(db: DB, text: str, now: datetime | None = None) -> str:
    """Route one incoming message to the right handler."""
    now = now or datetime.now()
    text = text.strip()
    if not text.startswith("/"):
        return "Send a command starting with / — try /help"

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    raw_args = parts[1] if len(parts) > 1 else ""

    if cmd == "/rename":
        # Needs the raw text so "old -> new" works without quotes.
        return _parse_rename(db, raw_args)

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
        if not 0 < kg <= config.MAX_BODYWEIGHT_KG:
            return (f"Body weight must be between 0 and "
                    f"{config.MAX_BODYWEIGHT_KG:.0f} {config.UNITS}.")
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
            return "\n\n".join(workout.format_plateau(db, ex, now=now, show_evidence=False)
                               for ex in exs)
        return workout.format_plateau(db, exercise, now=now)

    if cmd == "/plan":
        exercise = normalize_exercise(" ".join(args))
        if not exercise:
            return "Usage: /plan <exercise>"
        return workout.format_plan(db, exercise, now=now)

    if cmd == "/prs":
        return workout.format_prs(db)

    if cmd == "/undo":
        return _parse_undo(db, args)

    if cmd == "/report":
        return report.format_weekly_report(db, now)

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
