"""WhatsApp adapter for GymBot.

Uses `WPP_Whatsapp` (WPPConnect's official Python wrapper) — free, connects
by scanning a QR code like WhatsApp Web, and needs no server. See README for
installation (requires Node.js, which WPPConnect uses under the hood).

Run from the repo root:

    python bot.py

On startup you pick ONE contact from a menu; the bot only answers that
contact, so it never spams the rest of your chat list.

The heavy lifting (commands, storage, ML) lives in the `gymbot` package and
is fully testable without WhatsApp via `python -m gymbot.cli`.
"""
from __future__ import annotations

import os

from gymbot import commands
from gymbot.db import DB


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

    def on_message(msg: dict) -> None:
        body = (msg.get("body") or "").strip()
        chat_id = str(msg.get("from") or "")
        if str(chat_id) != target:
            return  # only answer the selected contact
        if not body or msg.get("isGroupMsg"):
            return  # ignore group chats and empty messages
        reply = commands.handle(db, body)
        client.sendText(chat_id, reply)

    client.onMessage(on_message)
    print(f"GymBot is running and only answering {target}.")


if __name__ == "__main__":
    main()
