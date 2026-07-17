# CNC Access Manager (Software — Mason Wang)

Admin web app + backend for the Tormach 770M access & logging system.
This is the software half of the group project: everything that happens
*after* a card is scanned — user management, usage/event logs, and the
pre-start safety checklist. Hardware (RFID reader, keypad, Pico, relay)
is handled by the electrical team.

## What it does
- **Login** — admin sign-in (writes are token-protected).
- **Users** — add / edit / delete / enable / disable users (name, RFID hex, PIN, cert level, status).
- **Logs** — access log (who used the machine, when) + event log (crash / dull bit / broken bit / clean sign-off). Names are looked up live, so renaming a user updates the logs.
- **Safety Checklist** — the machine only "unlocks" when every required item is checked.
- All data is stored in a real **SQLite** database (`cnc.db`) via a Python backend, so changes persist and sync for anyone on the server.

## Files
| File | Purpose |
|------|---------|
| `server.py`   | Backend: serves the app + REST API, reads/writes `cnc.db` (Python standard library only) |
| `index.html`  | Front-end (5 screens) |
| `style.css`   | Styling |
| `app.js`      | Front-end logic (calls the API) |
| `schema.sql`  | SQLite table definitions + seed data |
| `RUN.md`      | How to run |
| `start.bat`   | One-click launcher (Windows) |

> `cnc.db` is generated automatically on first run, so it does not need to be committed.

## Run it
1. Install Python 3.
2. In this folder:  `py server.py`  (Windows) or `python3 server.py`.
3. Open `http://localhost:8000`  ·  login `admin` / `admin`.

Or on Windows just double-click `start.bat`.

## REST API (for the hardware/Pico team)
| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/login` | returns admin token |
| GET | `/api/users` | list users |
| POST | `/api/users` | add (token required) |
| PUT | `/api/users/{id}` | edit (token required) |
| DELETE | `/api/users/{id}` | delete (token required) |
| GET | `/api/logs` | access + event logs |

## Next steps
- Hash PINs (salted SHA-256) instead of storing plaintext.
- Move this same API onto the Raspberry Pi Pico W (Microdot) to drive the machine relay.
- Serve over HTTPS on the lab network.
