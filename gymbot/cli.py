"""Interactive terminal mode — test the bot without WhatsApp.

Run:

    python -m gymbot.cli            # uses gymbot.db
    python -m gymbot.cli --db tmp.db
"""
from __future__ import annotations

import argparse
import sys

from . import commands
from .db import DB


def _fix_console_encoding() -> None:
    """Windows console defaults to cp1252, which chokes on the sparkline
    blocks and emojis — force UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def repl(db_path: str | None = None) -> None:
    _fix_console_encoding()
    db = DB(db_path)
    print("GymBot CLI — type /demo to seed sample data, /help for commands.")
    print("Ctrl+C or /quit to exit.\n")
    try:
        while True:
            try:
                text = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye 👋")
                break
            if text in ("/quit", "/exit", "quit", "exit"):
                print("Bye 👋")
                break
            print(commands.handle(db, text))
            print()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GymBot terminal mode")
    parser.add_argument("--db", default=None, help="SQLite file path")
    args = parser.parse_args()
    repl(args.db)
