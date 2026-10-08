# RailMind - AI-Powered Railway Booking & Recommendation System
Project Exhibition I (Group 140) - implements the architecture from the Review 1 PPT:
**Bootstrap frontend -> Flask REST/JSON backend <-> MySQL/SQLite database, with an AI/ML engine.**

## Run
```
pip install -r requirements.txt
python app.py            # open http://127.0.0.1:5000  (SQLite file railmind.db is auto-created and seeded)
python test_flow.py      # optional end-to-end API test
```
**MySQL (as in your rail.py):** create an empty DB (`CREATE DATABASE railmind;`) then set env vars before running:
`DB_BACKEND=mysql DB_HOST=localhost DB_USER=root DB_PASSWORD=*** DB_NAME=railmind` (and `pip install mysql-connector-python`).
Tables are created automatically. Also set `SECRET_KEY` to any long random string.

## Features
| Requirement | Where |
|---|---|
| Unique 10-digit PNR (first digit 1-9, DB `UNIQUE` + collision check) | `new_pnr()` in app.py |
| PNR status checker (public, validated `^\d{10}$`) + AI confirmation chance for waitlisted tickets | `GET /api/pnr/<pnr>`, "PNR Status" tab |
| Ticket PDF download after booking (QR code, owner-only access) | `GET /api/ticket/<pnr>.pdf`, ticket_pdf.py |
| Boarding / dropping station + times, coach, seat, berth | booking result, My Bookings, PDF |
| Seat/berth logic from rail.py (SL/3A/2A/1A, coach prefixes S/B/A/H) | seats.py |
| Waitlist (WL/n) when a class is full | `POST /api/book` |
| AI 1: waitlist confirmation prediction (GradientBoosting) | ai_engine.py |
| AI 2: connecting-train safety score + recommended buffer + alternatives | `POST /api/connection` |
| AI 3: Book-Now-or-Wait advisor (occupancy forecast regression) + dynamic fare | shown on every class in search |
| AI 4: personalised train ranking from your booking history | `/api/search` |

## Honest notes (read before your demo/viva)
- **Training data for the AI is synthetic** (ai_engine.py). Trains in the DB are REAL (datameet/railways, CC0): number, name, zone, origin, destination, departure, duration, distance, classes. Delay history, demand and coach counts are simulated.
  Say this clearly; to go real, replace the generators with real PNR-history / delay CSVs using the same feature columns.
- Passwords are hashed and all SQL is parameterised. Not included (listed as future work): CSRF tokens, rate-limiting, payments, email delivery of tickets.
- Seat availability is per whole train run (not per segment). Seat allocation is serialised with a lock + DB unique constraint; for multi-server deployment use `SELECT ... FOR UPDATE`.
- The MySQL path uses the same queries but was only tested on SQLite here.
- **Security warning about rail.py:** it contains your MySQL root password and a Gmail app password in plain text. Treat both as exposed - change the MySQL password, revoke that Gmail app password, and never commit credentials (use env vars as here).

## Real trains (NCR, NER, SER, SR, CR, WCR)
`railmind.db` is pre-loaded with **517 real trains** and ~79,000 real stops (4,698 stations) from `data/trains.json` + `data/schedules.json`
(datameet/railways, CC0): real numbers, names, zones, stop sequence, arrival/departure times, classes.
To rebuild: `python import_railways.py --reset --limit 0` (add `--dry-run` to preview). Settings are at the top of that file.
Skipped on purpose: 1,144 local/MEMU trains without SL/AC classes, 85 circular routes, 69 trains with corrupt/out-of-order times.
Test searches: BPL->NGP, NDLS->BPL, ET->NGP (type a code or city name).
Estimated/simulated (not in the dataset): km at each stop (interpolated from elapsed time), delay history, demand, coach counts.
