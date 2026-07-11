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

import http.server, socketserver, json, sqlite3, os, urllib.parse

PORT = 8000
DB   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cnc.db")
ROOT = os.path.dirname(os.path.abspath(__file__))

# --- admin credentials (demo). Change these for real use. ---
ADMIN_USER  = "admin"
ADMIN_PASS  = "admin"
ADMIN_TOKEN = "demo-token-770"

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
    ("Mason Wang",    "A1B2C3D4", "0770", "A",    "active"),
    ("Erik Marshall", "0F1E2D3C", "1234", "A",    "active"),
    ("Test User",     "99887766", "0000", "B",    "disabled"),
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
    with socketserver.ThreadingTCPServer(("", PORT), Handler) as httpd:
        print(f"CNC Access Manager running →  http://localhost:{PORT}")
        print("Login: admin / admin   ·   Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
