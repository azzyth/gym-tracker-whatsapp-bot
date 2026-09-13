# Development Log

A running record of what I build and improve in this project. This is my
"passion in coding" proof — one dogfooding project, grown over time.

## 2026-09-13

- Fixed the WhatsApp adapter: `client.onMessage(...)` instead of the
  non-existent `client.on_message(...)`.
- Made the bot selective — it now shows a contact menu on startup and only
  answers the one contact you pick (no more replying to everyone).
- Fixed a SQLite cross-thread crash by making the DB connection thread-safe
  (`check_same_thread=False` + `RLock`).
- Added GitHub Actions CI to run the 13-test suite on every push and PR.
- Started this log to track the journey.
