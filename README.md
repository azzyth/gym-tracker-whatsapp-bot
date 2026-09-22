# GymBuddy: Gym & Nutrition Tracker WhatsApp Bot

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-62%20passed-brightgreen)](tests/test_core.py)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A personal **gym-progress + food tracker** you talk to over **WhatsApp** (or the terminal). It logs your lifts and meals, then applies **machine learning** to spot the thing every lifter fears: **a plateau**, and it cross-references your nutrition to explain *why*.

Built after 4 years of lifting and hitting a plateau myself: the bot tells me when a lift has stalled and whether my eating is the cause.

> **Runs free:** local CLI with zero dependencies, or WhatsApp via [WPP_Whatsapp](https://github.com/3mora2/WPP_Whatsapp) (QR-code login, no server, no per-message cost).

## Ringkasan (Bahasa Indonesia)

Bot pelacak **progres gym + nutrisi** yang bisa kamu ajak ngobrol lewat **WhatsApp** (atau terminal). Catat angkatan & makanan, lalu bot memakai **machine learning** untuk mendeteksi **plateau** dan mengecek log makanan + berat badanmu untuk menjelaskan *penyebabnya* (mis. lagi defisit kalori, atau memang programnya yang perlu di-deload). Ada juga `/undo` untuk membatalkan catatan yang salah, `/prs` untuk rekor pribadi, `/rename` untuk merapikan nama latihan, dan laporan mingguan otomatis tiap hari Minggu.

---

## Features

- **Food logging**: `/eat` dengan makro lengkap (kalori, protein, karbohidrat, lemak), target harian yang bisa diatur, ringkasan `/today` dan `/week`.
- **Training logging**: `/set` untuk mencatat beberapa set sekaligus, perhitungan **1RM estimasi (Epley)**.
- **Progress visualization**: `/progress` menampilkan *sparkline* kekuatan + tren % per minggu.
- **Plateau detection (the ML part)**: `/plateau` memfit regresi linier terhadap e1RM per sesi, menghitung tren **recent 3 sesi**, lalu **menyebutkan satu penyebab**: kurang makan, sedang cutting, atau memang programnya yang perlu diubah. `/plateau <latihan>` juga menampilkan angka yang jadi dasar kesimpulannya.
- **Double progression**: `/plan` menyarankan beban/reps sesi berikutnya (aturan hypertrophy 8–12 reps).
- **Body-weight trend**: `/weigh` + `/weight` untuk melihat apakah kamu *cutting / gaining / stable*.
- **Personal records**: `/prs` menampilkan e1RM terbaik per latihan, dan `/set` memberi tanda 🎉 begitu kamu memecahkan rekor.
- **Fix your mistakes**: `/undo [meal|set|weigh] [n]` menghapus catatan terakhir, jadi salah ketik tidak permanen.
- **Tidy log names**: `/rename bench-press -> bench press` menggabungkan satu latihan yang tercatat dengan dua nama.
- **Weekly report**: `/report` kapan saja, plus push otomatis tiap **Minggu 19:00** dari `bot.py`.

## Commands

| Command | What it does |
|---------|--------------|
| `/eat nasi goreng 550 40 60 12` | log a meal (kcal, protein, carbs, fat) |
| `/today` / `/week` | today's / 7-day nutrition vs targets |
| `/target 2600 170 260 70` | view or set daily targets |
| `/set bench press 80 10 10 9` | log 1+ sets (exercise, weight, reps…) |
| `/sets` | today's sets |
| `/weigh 78.5` / `/weight` | log body weight / 8-week trend |
| `/1rm squat` | estimated 1RM |
| `/progress squat 12` | strength trend + sparkline (last 12 weeks) |
| `/plateau bench press` | stagnation check + advice |
| `/plan bench press` | next-session suggestion (double progression) |
| `/prs` | all-time best estimated 1RM per lift |
| `/rename bench-press -> bench press` | rename or merge a lift across your history |
| `/undo [meal\|set\|weigh] [n]` | delete your most recent entries |
| `/report` | weekly summary (also pushed every Sunday) |
| `/demo` | seed 8 weeks of sample data |
| `/help` | full list |

## The ML in 50 words

For each lift the bot groups your sets into daily **e1RM** points, fits **least-squares regression** on the full 6-week window *and* on the last 3 sessions, and converts each slope to `%/week`. A flat-or-negative recent slope marks a stall. It then reads your last 14 days of food and body weight and names the cause, in this priority order:

1. **Under-fuelled**: averaging below 90% of your calorie target, so fix the food before the program.
2. **Cutting**: body weight trending down, so a flatline is expected; hold the deload and keep protein high.
3. **Programmed-out**: eating at target with stable or rising weight, so the training is the problem; deload a week, then add volume.
4. **No data**: falls back to the generic checklist.

```
/set data → daily best e1RM → regression (6-week window + last 3 sessions)
         → slope %/week → stall?
         → join 14d calorie average + body-weight slope → which lever to pull
```

## Architecture

Clean separation so the "brain" is testable without WhatsApp:

```
gym-tracker-whatsapp-bot/
├── gymbot/                 # pure-Python core (zero third-party deps)
│   ├── db.py               # SQLite storage
│   ├── plateau.py          # 1RM, regression, plateau detector + nutrition join
│   ├── workout.py          # training views (1rm/progress/plan/prs/weight)
│   ├── food.py             # nutrition summaries + the plateau context
│   ├── report.py           # the weekly report (command + scheduled push)
│   ├── commands.py         # parse + dispatch (shared by CLI & WhatsApp)
│   └── cli.py              # terminal REPL
├── bot.py                  # WhatsApp adapter + weekly report scheduler
├── cli.py                  # python cli.py shortcut
├── tests/test_core.py      # 62 unittest tests (no deps)
├── requirements.txt        # only needed for the WhatsApp layer
└── README.md
```

## Quick start (terminal: zero installs)

```powershell
python -m gymbot.cli        # or: python cli.py
```

Type `/demo` to seed sample data, then `/plateau bench press`, `/progress squat`, `/week`, `/weight`.

## Run it on WhatsApp (free)

1. Install **Node.js LTS** <https://nodejs.org> (WPP_Whatsapp uses WPPConnect under the hood).
2. Install the Python wrapper:

```powershell
pip install WPP-Whatsapp
```

3. Run and scan the QR code with your phone (like WhatsApp Web):

```powershell
python bot.py
```

Message your bot from another chat (send yourself a WhatsApp message) and start with `/help`.

The bot stays alive until you press Ctrl+C, and pushes the weekly report every **Sunday from 19:00** (change `REPORT_WEEKDAY` / `REPORT_HOUR` in `gymbot/config.py`). A missed hour isn't a missed report: if the machine was asleep it sends at the next opportunity that day, and `last_report_date` stops a restart sending it twice.

> ⚠️ This uses the **unofficial** WhatsApp Web protocol via WPPConnect. For personal use it's free and fine; don't spam. For a fully official path, the same `gymbot` core can be wired to the **Meta WhatsApp Cloud API** (free service-conversation tier), the adapter is the only file you'd change.

## Free / low-cost hosting

| Option | Cost | Notes |
|--------|------|-------|
| Your own PC (Raspberry Pi) | free | simplest, bot runs while the machine is on |
| Oracle Cloud *Always Free* VPS | free | a small VM stays online 24/7 |
| Fly.io / Render free tier | free | small Node+Python app |

The bot only needs a tiny always-on machine and a SQLite file, no paid services required.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Roadmap ideas

- Photo-based meal logging (send a food pic → estimate calories).
- Load/recovery management (TRAC-style) using your set RPE.
- Export charts (PNG) for a monthly "physique report".
- Imperial units end-to-end: `WEIGHT_INCREMENT` and `/weigh <kg>` still assume kg even when `UNITS` says `lbs`.

## License

[MIT](LICENSE)
