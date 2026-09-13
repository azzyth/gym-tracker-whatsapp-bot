# GymBuddy   Gym & Nutrition Tracker WhatsApp Bot

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-13%20passed-brightgreen)](tests/test_core.py)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A personal **gym-progress + food tracker** you talk to over **WhatsApp** (or the terminal). It logs your lifts and meals, then applies **machine learning** to spot the thing every lifter fears: **a plateau**   and it cross-references your nutrition to explain *why*.

Built after 4 years of lifting and hitting a plateau myself: the bot tells me when a lift has stalled and whether my eating is the cause.

> **Runs free:** local CLI with zero dependencies, or WhatsApp via [WPP_Whatsapp](https://github.com/3mora2/WPP_Whatsapp) (QR-code login, no server, no per-message cost).

## Ringkasan (Bahasa Indonesia)

Bot pelacak **progres gym + nutrisi** yang bisa kamu ajak ngobrol lewat **WhatsApp** (atau terminal). Catat angkatan & makanan, lalu bot memakai **machine learning** untuk mendeteksi **plateau**   dan mengecek log makananmu untuk menjelaskan *penyebabnya* (mis. lagi defisit kalori).

---

## Features

- **Food logging**   `/eat` dengan makro lengkap (kalori, protein, karbohidrat, lemak), target harian yang bisa diatur, ringkasan `/today` dan `/week`.
- **Training logging**   `/set` untuk mencatat beberapa set sekaligus, perhitungan **1RM estimasi (Epley)**.
- **Progress visualization**   `/progress` menampilkan *sparkline* kekuatan + tren % per minggu.
- **Plateau detection (the ML part)**   `/plateau` memfit regresi linier terhadap e1RM per sesi, menghitung tren **recent 3 sesi**, dan menandai stagnasi. Lalu memberi saran (deload / tambah volume / perbaiki asupan) berdasarkan tren **body weight & kalori** kamu.
- **Double progression**   `/plan` menyarankan beban/reps sesi berikutnya (aturan hypertrophy 8–12 reps).
- **Body-weight trend**   `/weigh` + `/weight` untuk melihat apakah kamu *cutting / gaining / stable*.

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
| `/demo` | seed 8 weeks of sample data |
| `/help` | full list |

## The ML in 50 words

For each lift the bot groups your sets into daily **e1RM** points, fits **least-squares regression** on the full window *and* on the last 3 sessions, and converts the slope to `%/week`. A flat-or-negative recent slope = plateau. It then joins your **calorie + body-weight trend** to decide whether the fix is training or nutrition.

```
/set data → daily best e1RM → linear regression (overall + recent 3)
         → slope %/week → plateau? → advice (deload / volume / nutrition)
```

## Architecture

Clean separation so the "brain" is testable without WhatsApp:

```
gym-tracker-whatsapp-bot/
├── gymbot/                 # pure-Python core (zero third-party deps)
│   ├── db.py               # SQLite storage
│   ├── plateau.py          # 1RM, regression, plateau detector, progression
│   ├── workout.py          # training views (1rm/progress/plan/weight)
│   ├── food.py             # nutrition summaries
│   ├── commands.py         # parse + dispatch (shared by CLI & WhatsApp)
│   └── cli.py              # terminal REPL
├── bot.py                  # WhatsApp adapter (WPP_Whatsapp)
├── cli.py                  # python cli.py shortcut
├── tests/test_core.py      # 13 unittest tests (no deps)
├── requirements.txt        # only needed for the WhatsApp layer
└── README.md
```

## Quick start (terminal   zero installs)

```powershell
python -m gymbot.cli        # or: python cli.py
```

Type `/demo` to seed sample data, then `/plateau bench press`, `/progress squat`, `/week`, `/weight`.

## Run it on WhatsApp (free)

1. Install **Node.js LTS**   <https://nodejs.org> (WPP_Whatsapp uses WPPConnect under the hood).
2. Install the Python wrapper:

```powershell
pip install WPP-Whatsapp
```

3. Run and scan the QR code with your phone (like WhatsApp Web):

```powershell
python bot.py
```

Message your bot from another chat (send yourself a WhatsApp message) and start with `/help`.

> ⚠️ This uses the **unofficial** WhatsApp Web protocol via WPPConnect. For personal use it's free and fine; don't spam. For a fully official path, the same `gymbot` core can be wired to the **Meta WhatsApp Cloud API** (free service-conversation tier)   the adapter is the only file you'd change.

## Free / low-cost hosting

| Option | Cost | Notes |
|--------|------|-------|
| Your own PC (Raspberry Pi) | free | simplest   bot runs while the machine is on |
| Oracle Cloud *Always Free* VPS | free | a small VM stays online 24/7 |
| Fly.io / Render free tier | free | small Node+Python app |

The bot only needs a tiny always-on machine and a SQLite file   no paid services required.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Roadmap ideas

- Weekly progress report sent automatically every Sunday.
- Photo-based meal logging (send a food pic → estimate calories).
- Load/recovery management (TRAC-style) using your set RPE.
- Export charts (PNG) for a monthly "physique report".

## License

[MIT](LICENSE)
