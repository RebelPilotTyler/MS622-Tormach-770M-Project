#!/usr/bin/env python3
"""
CNC Access Manager — local backend (pure standard library, no pip installs).

Serves the front-end (index.html / style.css / app.js) AND a REST API that
reads/writes a real SQLite database (cnc.db). Every add/edit/delete/disable
from the web page is written to SQLite, so it persists and syncs for anyone
connecting to this server.

RUN:
    python server.py            (Windows: py server.py)
then open   http://localhost:8000   in your browser.

Login: admin / admin
"""

import http.server, socketserver, json, sqlite3, os, urllib.parse, datetime, time
import sys, threading, webbrowser

PORT = 8000
# Works both as a .py script and as a bundled .exe (PyInstaller sets sys.frozen).
if getattr(sys, "frozen", False):
    BASE = os.path.dirname(sys.executable)
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(BASE, "cnc.db")
ROOT = BASE

# --- admin credentials (demo). Change these for real use. ---
ADMIN_USER  = "admin"
ADMIN_PASS  = "admin"
ADMIN_TOKEN = "demo-token-770"
# --- device key: the on-machine Pico sends this to verify a card + PIN ---
DEVICE_KEY  = "pico-770"

def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

# --- last card the reader scanned (for the web "Scan" / enrollment button) ---
LAST_SCAN = {"uid": None, "at": 0.0}

# --- system update history shown on the System tab ---
CHANGELOG = [
    {"version": "1.2", "date": "2026-07-17", "items": [
        "Pico hardware integration: /api/verify checks card + PIN against SQLite and logs the access",
        "Sign-out closes the session (/api/logout); machine event logging (/api/event)",
        "RFID enrollment: the reader posts to /api/scan and the web Scan button pulls it via /api/last-scan",
        "New System tab: live server / database / reader status + this update history",
        "Boot health check (/api/health)"]},
    {"version": "1.1", "date": "2026-07-09", "items": [
        "Real SQLite backend + REST API (server.py) — every change persists and syncs",
        "Admin login; all writes require a token"]},
    {"version": "1.0", "date": "2026-07-09", "items": [
        "Front-end MVP: Users, Logs, and Safety Checklist screens"]},
]

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  rfid_hex TEXT NOT NULL UNIQUE,
  pin TEXT NOT NULL,
  cert_level TEXT NOT NULL DEFAULT 'none',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS access_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id),
  login_at TEXT, logout_at TEXT
);
CREATE TABLE IF NOT EXISTS event_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id),
  type TEXT, note TEXT, created_at TEXT
);
"""

SEED_USERS = [
    ("Mason Wang",       "A1B2C3D4", "0770", "A",    "active"),
    ("Erik Marshall",    "0F1E2D3C", "1234", "A",    "active"),
    ("Glenn (test card)","A388DB1C", "7789", "A",    "active"),   # real reader test card
    ("Test User",        "99887766", "0000", "B",    "disabled"),
]
SEED_ACCESS = [
    (1, "2026-07-08 14:02", "2026-07-08 14:48"),
    (2, "2026-07-08 15:10", "2026-07-08 16:05"),
    (1, "2026-07-09 09:20", None),
]
SEED_EVENTS = [
    (2, "ok",       "Clean sign-off",          "2026-07-08 16:05"),
    (1, "dull_bit", '1/4" end mill felt dull', "2026-07-08 14:48"),
    (3, "crash",    "Z probe bent - flagged",  "2026-07-07 11:33"),
]


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    fresh = not os.path.exists(DB)
    con = db()
    con.executescript(SCHEMA)
    if fresh or con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        con.executemany(
            "INSERT INTO users(name,rfid_hex,pin,cert_level,status) VALUES(?,?,?,?,?)",
            SEED_USERS)
        con.executemany(
            "INSERT INTO access_logs(user_id,login_at,logout_at) VALUES(?,?,?)",
            SEED_ACCESS)
        con.executemany(
            "INSERT INTO event_logs(user_id,type,note,created_at) VALUES(?,?,?,?)",
            SEED_EVENTS)
        con.commit()
        print("Seeded new database:", DB)
    con.close()


class Handler(http.server.BaseHTTPRequestHandler):

    # ---------- helpers ----------
    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def authed(self):
        return self.headers.get("X-Admin-Token") == ADMIN_TOKEN

    def is_device(self):
        return self.headers.get("X-Device-Key") == DEVICE_KEY

    def serve_static(self, path):
        if path in ("/", "/index.html"):
            fname = "index.html"
        else:
            fname = os.path.basename(path)
        full = os.path.join(ROOT, fname)
        if not os.path.isfile(full):
            self.send_error(404); return
        ctype = {"html": "text/html", "css": "text/css", "js": "application/javascript"}.get(
            fname.rsplit(".", 1)[-1], "application/octet-stream")
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---------- GET ----------
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/health":
            # lightweight reachability check for the Pico at boot
            return self.send_json({"ok": True, "service": "CNC Access Manager",
                                   "version": "1.2"})
        if path == "/api/last-scan":
            # the most recent card the reader posted (for enrollment)
            age = None
            if LAST_SCAN["uid"] and LAST_SCAN["at"]:
                a = round(time.time() - LAST_SCAN["at"], 1)
                age = a if a <= 60 else None
            return self.send_json({"uid": LAST_SCAN["uid"] if age is not None else None,
                                   "age": age})
        if path == "/api/system":
            con = db()
            users = con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            active = con.execute("SELECT COUNT(*) c FROM users WHERE status='active'").fetchone()["c"]
            opens = con.execute("SELECT COUNT(*) c FROM access_logs WHERE logout_at IS NULL").fetchone()["c"]
            con.close()
            scan_age = None
            if LAST_SCAN["at"]:
                a = round(time.time() - LAST_SCAN["at"], 1)
                scan_age = a if a <= 3600 else None
            return self.send_json({"ok": True, "version": "1.2", "users": users,
                                   "active_users": active, "open_sessions": opens,
                                   "last_scan_age": scan_age, "changelog": CHANGELOG})
        if path == "/api/users":
            con = db()
            rows = [dict(r) for r in con.execute(
                "SELECT id,name,rfid_hex,pin,cert_level,status FROM users ORDER BY id")]
            con.close()
            return self.send_json(rows)
        if path == "/api/logs":
            con = db()
            access = [dict(r) for r in con.execute("""
                SELECT a.id, COALESCE(u.name,'Deleted user') AS user,
                       a.login_at AS login, a.logout_at AS logout
                FROM access_logs a LEFT JOIN users u ON u.id=a.user_id
                ORDER BY a.login_at""")]
            events = [dict(r) for r in con.execute("""
                SELECT e.id, COALESCE(u.name,'Deleted user') AS user,
                       e.type, e.note, e.created_at AS time
                FROM event_logs e LEFT JOIN users u ON u.id=e.user_id
                ORDER BY e.created_at DESC""")]
            con.close()
            return self.send_json({"access": access, "events": events})
        return self.serve_static(path)

    # ---------- POST ----------
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/login":
            d = self.body_json()
            if d.get("username") == ADMIN_USER and d.get("password") == ADMIN_PASS:
                return self.send_json({"ok": True, "token": ADMIN_TOKEN})
            return self.send_json({"ok": False}, 401)
        if path == "/api/users":
            if not self.authed():
                return self.send_json({"error": "unauthorized"}, 401)
            d = self.body_json()
            con = db()
            try:
                cur = con.execute(
                    "INSERT INTO users(name,rfid_hex,pin,cert_level,status) VALUES(?,?,?,?,?)",
                    (d["name"], d["rfid_hex"], d["pin"], d.get("cert_level", "none"),
                     d.get("status", "active")))
                con.commit()
                d["id"] = cur.lastrowid
                return self.send_json(d, 201)
            except sqlite3.IntegrityError as e:
                return self.send_json({"error": str(e)}, 400)
            finally:
                con.close()

        # ---- called by the on-machine Pico: check a card + PIN ----
        if path == "/api/verify":
            if not self.is_device():
                return self.send_json({"authorized": False, "error": "bad device key"}, 401)
            d = self.body_json()
            rfid = (d.get("rfid_hex") or "").strip().upper()
            pin  = (d.get("pin") or "").strip()
            con = db()
            row = con.execute(
                "SELECT id,name,cert_level,pin,status FROM users WHERE upper(rfid_hex)=?",
                (rfid,)).fetchone()
            ok = bool(row) and row["status"] == "active" and row["pin"] == pin
            if ok:
                con.execute(
                    "INSERT INTO access_logs(user_id,login_at,logout_at) VALUES(?,?,?)",
                    (row["id"], now_str(), None))
                con.commit()
            con.close()
            if ok:
                return self.send_json({"authorized": True,
                                       "name": row["name"],
                                       "cert_level": row["cert_level"]})
            reason = ("unknown card" if not row
                      else ("disabled" if row["status"] != "active" else "bad pin"))
            return self.send_json({"authorized": False, "reason": reason})

        # ---- reader posts a scanned card UID here (enrollment) ----
        if path == "/api/scan":
            if not self.is_device():
                return self.send_json({"error": "bad device key"}, 401)
            d = self.body_json()
            uid = (d.get("uid") or d.get("rfid_hex") or "").strip().upper()
            if uid:
                LAST_SCAN["uid"] = uid
                LAST_SCAN["at"] = time.time()
            return self.send_json({"ok": True})

        # ---- log a machine event (crash / dull bit / clean) ----
        if path == "/api/event":
            if not (self.is_device() or self.authed()):
                return self.send_json({"error": "unauthorized"}, 401)
            d = self.body_json()
            rfid = (d.get("rfid_hex") or "").strip().upper()
            con = db()
            row = con.execute("SELECT id FROM users WHERE upper(rfid_hex)=?", (rfid,)).fetchone()
            con.execute(
                "INSERT INTO event_logs(user_id,type,note,created_at) VALUES(?,?,?,?)",
                (row["id"] if row else None, d.get("type", "ok"), d.get("note", ""), now_str()))
            con.commit(); con.close()
            return self.send_json({"ok": True})

        # ---- close the current access session (sign out) ----
        if path == "/api/logout":
            if not (self.is_device() or self.authed()):
                return self.send_json({"error": "unauthorized"}, 401)
            d = self.body_json()
            rfid = (d.get("rfid_hex") or "").strip().upper()
            con = db()
            row = con.execute("SELECT id FROM users WHERE upper(rfid_hex)=?", (rfid,)).fetchone()
            if row:
                con.execute("""
                    UPDATE access_logs SET logout_at=?
                    WHERE id = (SELECT id FROM access_logs
                                WHERE user_id=? AND logout_at IS NULL
                                ORDER BY id DESC LIMIT 1)""",
                    (now_str(), row["id"]))
                con.commit()
            con.close()
            return self.send_json({"ok": True})

        self.send_error(404)

    # ---------- PUT ----------
    def do_PUT(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/users/"):
            if not self.authed():
                return self.send_json({"error": "unauthorized"}, 401)
            uid = int(path.rsplit("/", 1)[-1])
            d = self.body_json()
            con = db()
            con.execute(
                "UPDATE users SET name=?,rfid_hex=?,pin=?,cert_level=?,status=? WHERE id=?",
                (d["name"], d["rfid_hex"], d["pin"], d["cert_level"], d["status"], uid))
            con.commit(); con.close()
            return self.send_json({"ok": True})
        self.send_error(404)

    # ---------- DELETE ----------
    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/users/"):
            if not self.authed():
                return self.send_json({"error": "unauthorized"}, 401)
            uid = int(path.rsplit("/", 1)[-1])
            con = db()
            con.execute("DELETE FROM users WHERE id=?", (uid,))
            con.commit(); con.close()
            return self.send_json({"ok": True})
        self.send_error(404)

    def log_message(self, *a):   # quieter console
        pass


if __name__ == "__main__":
    init_db()
    # open the browser automatically ~1s after the server starts (one-click use)
    threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    with socketserver.ThreadingTCPServer(("", PORT), Handler) as httpd:
        print(f"CNC Access Manager running →  http://localhost:{PORT}")
        print("A browser tab will open automatically.  Login: admin / admin")
        print("Keep this window open.  Ctrl+C (or close window) to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
