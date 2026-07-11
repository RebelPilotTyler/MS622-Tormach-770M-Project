# CNC Access Manager — How to run (SQLite version)

All data now lives in a real SQLite database (`cnc.db`). The web page reads and
writes through a small local server (`server.py`), so every add/edit/delete/disable
is saved to the database and syncs for anyone connecting to that server.

## Files (keep them all in the same folder)
- `server.py`   — backend + REST API + serves the web page (Python standard library only)
- `index.html` / `style.css` / `app.js` — the front-end
- `cnc.db`      — the SQLite database (auto-created/seeded if missing)
- `schema.sql`  — the table definitions (for reference / DB Browser)

## Run it
1. Install Python 3 if you don't have it (python.org).
2. Open a terminal in this folder.
3. Start the server:
   - Windows:  `py server.py`
   - macOS/Linux:  `python3 server.py`
4. Open your browser at:  **http://localhost:8000**
5. Login:  **admin / admin**

Press **Ctrl + C** in the terminal to stop the server.

## What syncs to SQLite
- Add / edit / delete / enable / disable a user  → written to `cnc.db`
- Logs page reads access + event logs from `cnc.db` (names are looked up live, so renaming a user updates the logs)
- The Safety Checklist is a live gate in the browser (not stored)

## View the database directly
Open `cnc.db` in **DB Browser for SQLite** → tab **Browse Data** → pick a table
(`users`, `access_logs`, `event_logs`). You'll see the same rows the website shows.
If you edit in DB Browser, click **Write Changes** to save.

## Connect from another computer (same network)
1. Find this PC's IP (e.g. `192.168.1.50`).
2. On the other PC, open `http://192.168.1.50:8000`.
   (In `app.js`, `API=''` uses the same server automatically — no change needed
   when the page is served by `server.py`.)

## Security notes (already in place / for later)
- Writes require the admin token returned at login (no token → HTTP 401).
- Change `ADMIN_USER` / `ADMIN_PASS` in `server.py` for real use.
- Next step for production: hash the PIN, run over HTTPS, and move this same API
  onto the Raspberry Pi Pico (Microdot) so it talks to the machine relay.
