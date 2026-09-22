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

## 2026-09-22

- **Made the headline claim true.** `/plateau` never actually looked at my
  food or body weight — it just told me to go check `/week` myself, while the
  README promised a cross-reference. Now `food.nutrition_context` builds a
  `NutritionContext` (14-day kcal/protein averages + body-weight slope) and
  the verdict names *one* cause, in priority order: under-fuelled → cutting →
  the programming is the problem → generic fallback. `/plateau <lift>` also
  prints the numbers it drew that conclusion from.
- **Fixed an ordering bug that made `/plan` lie.** One `/set` writes several
  rows with an identical timestamp, and every read was `ORDER BY ts` — so on
  ties SQLite could hand back any order and "your last set" was a coin flip.
  All reads now order by `ts, id`.
- Hardened the WhatsApp adapter: explicit keep-alive loop instead of trusting
  the wrapper's threads, per-message `try/except` so one bad message can't
  kill the listener, a `fromMe` guard, and chat-id normalization (strips
  `@c.us` / `:device` suffixes) so an id-shape change can't silently leave
  the bot answering nobody.
- **`/undo [meal|set|weigh] [n]`** — bare `/undo` removes whatever I logged
  last, whichever table it landed in. A typo is no longer permanent.
- **`/prs`** — all-time best e1RM per lift, plus a 🎉 note when `/set` beats
  an existing record (and only then, not on a first-ever log).
- **`/rename <old> -> <new>`** — merges duplicate lift names such as
  `bench-press` vs `bench press`. Only ever on request; nothing rewrites my
  history on its own.
- **`/report` + the Sunday push.** The weekly summary (nutrition, training
  with week-over-week e1RM deltas and stall flags, body weight) is one
  builder used by both the command and a scheduler thread in `bot.py`.
  `last_report_date` in the settings table stops a restart double-sending.
- Input guards: negative and absurd numbers are rejected with an explanation
  instead of being written to the database.
- Sparklines now downsample to `SPARKLINE_WIDTH` — a year of sessions used to
  render a 200-character bar into a WhatsApp bubble.
- Tests: 13 → 62, covering every branch of the nutrition join, undo, PR
  detection, rename, validation and the tie-break bug.

