"""WhatsApp adapter for GymBot.

Uses `WPP_Whatsapp` (WPPConnect's official Python wrapper) — free, connects
by scanning a QR code like WhatsApp Web, and needs no server. See README for
installation (requires Node.js, which WPPConnect uses under the hood).

Run from the repo root:

    python bot.py

On startup you pick ONE contact from a menu; the bot only answers that
contact, so it never spams the rest of your chat list. It also pushes a
weekly report (schedule in ``gymbot/config.py``).

The heavy lifting (commands, storage, ML) lives in the `gymbot` package and
is fully testable without WhatsApp via `python -m gymbot.cli`.
"""
from __future__ import annotations

import os
import threading
import time
import traceback
from datetime import datetime

from gymbot import commands, config
from gymbot.db import DB

# WPP hands back ids in several shapes depending on version and call site.
_CHAT_SUFFIXES = ("@c.us", "@s.whatsapp.net", "@lid", "@g.us", "@broadcast")


def _log(message: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def _normalize_chat_id(raw: object) -> str:
    """Bare user part of a WhatsApp id, for comparing a sender to the target.

    A serialized id looks like ``62812…@c.us`` and multi-device ones carry a
    device suffix (``62812…:12@c.us``), while some code paths return only the
    user part. Comparing the normalized halves means a shape change in the
    wrapper can't silently leave the bot answering nobody.
    """
    if isinstance(raw, dict):
        raw = raw.get("_serialized") or raw.get("user") or ""
    text = str(raw or "")
    for suffix in _CHAT_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text.split(":", 1)[0]


def _chat_id(chat: dict) -> str:
    """Extract the WhatsApp chat id from whatever shape WPP returns."""
    cid = chat.get("id") if isinstance(chat, dict) else None
    if isinstance(cid, dict):
        return str(cid.get("_serialized") or cid.get("user") or cid.get("server") or "")
    return str(cid or chat.get("_serialized") or "")


def _chat_name(chat: dict) -> str:
    """Best-effort human-readable name for a chat."""
    contact = chat.get("contact") or {}
    name = (chat.get("name")
            or chat.get("formattedTitle")
            or contact.get("formattedName")
            or contact.get("name")
            or contact.get("pushname"))
    return str(name or _chat_id(chat) or "Unknown")


def _list_user_chats(client) -> list[dict]:
    """Return individual (non-group) chats, newest first."""
    try:
        chats = client.listChats({"onlyUsers": True}) or []
    except Exception:
        chats = []
    if not chats:
        try:
            chats = [c for c in (client.getAllChats() or [])
                     if not c.get("isGroup") and c.get("isUser")]
        except Exception:
            chats = []
    return [c for c in chats if _chat_id(c)]


def _pick_contact(client) -> str | None:
    chats = _list_user_chats(client)
    if not chats:
        print("No individual chats found. Message this account first, then restart.")
        return None

    print("Select the contact the bot should chat with (it will only reply to this one):")
    for i, chat in enumerate(chats, 1):
        print(f"  {i}. {_chat_name(chat)}  ({_chat_id(chat)})")

    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if raw.lower() in ("q", "quit", "exit"):
            return None
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(chats):
                return _chat_id(chats[idx])
        except ValueError:
            pass
        print("Pick a number from the list (or q to quit).")


def _start_weekly_report(client, target: str, db: DB) -> None:
    """Push the weekly report once, on the configured day.

    The ``last_report_date`` setting is the double-send guard, so a restart
    in the middle of the scheduled day can't produce two reports. The hour
    comparison is ``>=`` on purpose: a laptop that was asleep at the
    scheduled hour still gets its report when it wakes up.
    """

    def loop() -> None:
        while True:
            try:
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                due = (
                    now.weekday() == config.REPORT_WEEKDAY
                    and now.hour >= config.REPORT_HOUR
                    and db.get_setting("last_report_date") != today
                )
                if due:
                    client.sendText(target, commands.handle(db, "/report", now=now))
                    db.set_setting("last_report_date", today)
                    _log("Weekly report sent.")
            except Exception as exc:
                _log(f"Weekly report failed: {exc}")
            time.sleep(60)

    threading.Thread(target=loop, daemon=True, name="weekly-report").start()


def main() -> None:
    db = DB(os.environ.get("GYMBOT_DB"))

    try:
        from WPP_Whatsapp import Create
    except ImportError:
        raise SystemExit(
            "WPP_Whatsapp is not installed.\n"
            "  1. Install Node.js LTS: https://nodejs.org\n"
            "  2. pip install WPP-Whatsapp\n"
            "  3. python bot.py\n"
            "If you'd rather not install it yet, try the CLI: python -m gymbot.cli"
        )

    creator = Create(session="gymbot_session")
    client = creator.start()

    target = _pick_contact(client)
    if not target:
        print("No contact selected — exiting.")
        return

    target_key = _normalize_chat_id(target)

    def on_message(msg: dict) -> None:
        if not isinstance(msg, dict) or msg.get("fromMe"):
            return  # nothing to do, and never answer ourselves
        chat_id = str(msg.get("from") or "")
        if _normalize_chat_id(chat_id) != target_key:
            return  # only answer the selected contact
        if msg.get("isGroupMsg"):
            return
        body = (msg.get("body") or "").strip()
        if not body:
            return
        try:
            reply = commands.handle(db, body)
        except Exception:
            # One malformed message must not take the listener down with it.
            _log("Failed to handle message:\n" + traceback.format_exc())
            reply = "⚠️ Something went wrong handling that — check the console."
        try:
            client.sendText(chat_id, reply)
        except Exception as exc:
            _log(f"Could not send reply: {exc}")

    client.onMessage(on_message)
    _start_weekly_report(client, target, db)
    _log(f"GymBot is running and only answering {target}. Ctrl+C to stop.")

    # Hold the process open explicitly rather than trusting the wrapper's
    # threads to outlive main().
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _log("Stopping GymBot.")
    finally:
        if hasattr(client, "close"):
            try:
                client.close()
            except Exception as exc:
                _log(f"Could not close the WhatsApp client cleanly: {exc}")
        db.close()


if __name__ == "__main__":
    main()
