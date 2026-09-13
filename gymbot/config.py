"""Configuration and defaults.

Everything here can be overridden via environment variables or by editing
the dataclasses. Kept free of external imports on purpose.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class DietTarget:
    """Daily nutrition target. Adjust to your TDEE (see README)."""

    kcal: float = 2500.0
    protein_g: float = 160.0
    carbs_g: float = 250.0
    fat_g: float = 70.0


# --- Units & progression rules -------------------------------------------------
UNITS = "kg"                     # "kg" or "lbs" (see README to switch)
WEIGHT_INCREMENT = 2.5           # kg added when you hit the top of the rep range
HYPERTROPHY_REP_RANGE = (8, 12)  # double progression: add reps inside this, then +weight

# --- Plateau detector -----------------------------------------------------------
PLATEAU_WINDOW_WEEKS = 6         # how far back to look for stagnation
PLATEAU_MIN_SESSIONS = 4         # need at least this many sessions to judge
PLATEAU_SLOPE_PCT_WEEK = 0.25    # e1RM growth below this %/week counts as "stalled"

# --- Storage --------------------------------------------------------------------
DB_PATH = os.environ.get("GYMBOT_DB", "gymbot.db")

# --- Suggested exercises for a hypertrophy split -------------------------------
DEFAULT_EXERCISES = [
    "squat", "bench press", "deadlift", "overhead press", "barbell row",
    "lat pulldown", "leg press", "leg curl", "leg extension",
    "incline dumbbell press", "lateral raise", "bicep curl", "tricep pushdown",
    "cable fly", "seated row", "hip thrust", "calf raise",
]

HELP_TEXT = """Available commands:

FOOD
/eat <name> <kcal> [protein] [carbs] [fat]   log a meal
/today                                       today's calories & macros
/week                                        last 7 days nutrition summary
/target [kcal protein carbs fat]             view or set daily targets

TRAINING
/set <exercise> <weight> <reps> [reps...]    log one or more sets
/sets                                        today's sets
/weigh <kg>                                  log body weight
/weight                                      body-weight trend (8 weeks)
/1rm <exercise>                              estimated 1RM (Epley)
/progress <exercise> [weeks]                 strength trend + sparkline
/plateau [exercise]                          stagnation check + advice
/plan <exercise>                             next-session suggestion (double progression)

OTHER
/demo                                        seed sample data to try it out
/help                                        this message

Example:
/set bench press 80 10 10 9
/eat chicken rice 550 40 60 12
"""
