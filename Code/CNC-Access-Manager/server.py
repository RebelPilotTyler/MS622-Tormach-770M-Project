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
import sys, threading, webbrowser, hashlib, hmac, secrets, base64

PORT = 8000
# Works both as a .py script and as a bundled .exe (PyInstaller sets sys.frozen).
if getattr(sys, "frozen", False):
    BASE = os.path.dirname(sys.executable)
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(BASE, "cnc.db")
ROOT = BASE

# --- admin credentials (demo). Change these for real use. ---
# v1.4: the admin password is stretched with PBKDF2 and a fixed salt, the same
# way user PINs are. A bare SHA-256 of a short password is reversible from a
# rainbow table in seconds, which is the exact problem v1.3 fixed for PINs but
# left in place here. Print a new hash for your own password with:
#     python -c "import hashlib;print(hashlib.pbkdf2_hmac('sha256',b'yourpass',b'cnc-admin-salt',100000).hex())"
ADMIN_USER      = "admin"
ADMIN_SALT      = b"cnc-admin-salt"
ADMIN_PASS_HASH = hashlib.pbkdf2_hmac("sha256", b"admin", ADMIN_SALT, 100_000).hex()
ADMIN_TOKEN     = secrets.token_urlsafe(24)   # regenerated on every start
# --- device key: the on-machine Pico sends this to verify a card + PIN ---
DEVICE_KEY  = os.environ.get("CNC_DEVICE_KEY", "pico-770")

def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# =============================================================================
# PIN hashing (v1.3)
# -----------------------------------------------------------------------------
# PINs are only 4 digits, so a plain SHA-256 is trivially reversible with a
# 10,000-entry table. Each user therefore gets a random 16-byte salt and the PIN
# is stretched with PBKDF2-HMAC-SHA256. The database never stores the PIN.
# `hmac.compare_digest` is used so the comparison is constant-time.
# =============================================================================
PIN_ITERATIONS = 100_000

def make_salt():
    return secrets.token_hex(16)

def hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", str(pin).encode(), bytes.fromhex(salt), PIN_ITERATIONS
    ).hex()

def pin_ok(row, pin):
    """Constant-time check of a submitted PIN against a users row."""
    if not row or not row["pin_salt"] or not row["pin_hash"]:
        return False
    return hmac.compare_digest(row["pin_hash"], hash_pin(pin, row["pin_salt"]))


# --- offline verifier for the reader's cache -------------------------------
# The Pico cannot run 100,000 PBKDF2 rounds (it would take minutes per tap), so
# the roster it caches carries a second, cheap verifier: one HMAC-SHA256 keyed
# by OFFLINE_KEY, a secret shared only with the reader. This is deliberately
# weaker than the online path, and it is only ever consulted when the server is
# unreachable. Trade-off accepted so the mill stays usable during an outage.
OFFLINE_KEY = b"cnc-770-offline-pepper-change-me"

def offline_hash(rfid_hex, pin):
    msg = (rfid_hex.strip().upper() + ":" + str(pin).strip()).encode()
    return hmac.new(OFFLINE_KEY, msg, hashlib.sha256).hexdigest()


# =============================================================================
# Encryption at rest (v1.4)
# -----------------------------------------------------------------------------
# Following the cybersecurity review: data should be hashed when it only ever
# needs to be *compared*, and encrypted when it has to be *read back*.
#
#   PIN                 -> hashed  (we only ever ask "does this match?")
#   admin password      -> hashed  (same reason)
#   card UID, user name -> ENCRYPTED. The server has to recover these: the card
#                          UID to match a tap, the name to show on the Logs
#                          page. A hash cannot be reversed, so a hash is the
#                          wrong tool here.
#
# Why this matters: before v1.4, anyone who copied cnc.db walked away with a
# clean list of every authorised card UID. RFID cards are clonable by design --
# the card has to answer any reader that asks -- so that list is the single most
# damaging thing in the file. The PIN pad is what stops a cloned card being
# enough, but the UID list should still not be sitting in the open.
#
# Fernet (AES-128-CBC + HMAC-SHA256, from the `cryptography` package) does the
# encryption. It is an OPTIONAL dependency on purpose: if it is not installed
# the server still runs exactly as it did in v1.3 and says so loudly, so the
# one-file "double-click and go" property is never lost. Install it with:
#     pip install cryptography
#
# Lookups still work because each card also gets a *blind index*: a keyed
# HMAC-SHA256 of the UID, stored in rfid_hex. It is deterministic, so
# "WHERE rfid_hex = ?" is still a single indexed query, but it is one-way, so
# the index itself leaks nothing.
# =============================================================================
try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAVE_FERNET = True
except ImportError:
    _HAVE_FERNET = False

KEY_FILE = os.path.join(BASE, "secret.key")

def _find_key():
    """Look for an existing key: CNC_SECRET_KEY, then secret.key beside the DB.

    Deliberately does NOT create one. Auto-generating a key here would be a trap:
    if secret.key went missing from a database that is already encrypted, a fresh
    key would load cleanly and then quietly fail to decrypt anything. The key is
    only ever created by _create_key(), and only for a database with nothing
    encrypted in it yet.
    """
    env = os.environ.get("CNC_SECRET_KEY")
    if env:
        return env.encode()
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read().strip()
    return None

def _create_key():
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    try:
        os.chmod(KEY_FILE, 0o600)      # no-op on some Windows filesystems
    except OSError:
        pass
    print("Generated a new encryption key:", KEY_FILE, "- back this up somewhere")
    print("  other than next to cnc.db, or the encrypted columns become unreadable.")
    return key

def _use_key(key):
    """Install a key and switch encryption on."""
    global SECRET_KEY, FERNET, ENCRYPTION_ON
    SECRET_KEY    = key
    FERNET        = Fernet(key) if key else None
    ENCRYPTION_ON = FERNET is not None

SECRET_KEY, FERNET, ENCRYPTION_ON = None, None, False
if _HAVE_FERNET:
    _use_key(_find_key())

def enc(text):
    """Encrypt a value that has to be read back later. Returns None if empty."""
    if not ENCRYPTION_ON or text is None or text == "":
        return None
    return FERNET.encrypt(str(text).encode()).decode()

def dec(token, fallback=""):
    """Decrypt a stored token; fall back to the plaintext column if unset."""
    if not token:
        return fallback
    if not ENCRYPTION_ON:
        return fallback
    try:
        return FERNET.decrypt(token.encode()).decode()
    except InvalidToken:
        return fallback

def card_id(rfid):
    """Blind index for a card UID: deterministic, indexable, not reversible."""
    u = (rfid or "").strip().upper()
    if not ENCRYPTION_ON:
        return u
    return hmac.new(SECRET_KEY, u.encode(), hashlib.sha256).hexdigest()

def card_where():
    """WHERE fragment that matches card_id() in both modes."""
    return "rfid_hex=?" if ENCRYPTION_ON else "upper(rfid_hex)=?"

def user_name(row):
    """Name for display, whichever column it actually lives in."""
    try:
        encrypted = row["name_enc"]
    except (IndexError, KeyError):
        encrypted = None
    return dec(encrypted, row["name"] or "")

def user_card(row):
    """Real card UID for display / for the reader, decrypted if necessary."""
    try:
        encrypted = row["rfid_enc"]
    except (IndexError, KeyError):
        encrypted = None
    return dec(encrypted, row["rfid_hex"] or "")


# --- last card the reader scanned (for the web "Scan" / enrollment button) ---
LAST_SCAN = {"uid": None, "at": 0.0}

# --- system update history shown on the System tab ---
CHANGELOG = [
    {"version": "1.4", "date": "2026-08-01", "items": [
        "Security review (Dr. Pacote, via Tyler): applied the encrypt-vs-hash rule to every "
        "stored field - hash what is only compared, encrypt what has to be read back",
        "Security: card UIDs and user names are now encrypted at rest with Fernet "
        "(AES-128-CBC + HMAC-SHA256); a copied cnc.db no longer hands over a list of clonable cards",
        "Security: cards are still looked up in one indexed query via a keyed blind index, "
        "so encryption costs nothing at the point of a tap",
        "Security: the admin password moved from bare SHA-256 to PBKDF2 (100k rounds) - "
        "the same weakness v1.3 fixed for PINs was still present here",
        "Security: the admin session token is generated fresh on every start instead of "
        "being a fixed string in the source",
        "Security: GET /api/users now requires the admin token; it used to list every card UID "
        "to anyone on the network",
        "Security: /api/roster sends a hashed card ID instead of the real UID, so a stolen "
        "reader does not leak the card list either",
        "Encryption is an optional dependency - without `cryptography` installed the server "
        "runs exactly as v1.3 did and says so on start"]},
    {"version": "1.3", "date": "2026-07-24", "items": [
        "Security: PINs are now stored as salted PBKDF2-HMAC-SHA256 hashes, never in plaintext "
        "(existing databases are migrated automatically on start)",
        "Security: the admin password is compared as a hash, in constant time",
        "Reliability: the reader keeps a cached roster (/api/roster) so the mill stays usable "
        "if Wi-Fi or this PC goes down",
        "Reliability: access taps recorded while offline are uploaded on reconnect (/api/sync)",
        "Reviewed against Glenn's 7/17 firmware — pin map, timings and RC522 driver confirmed identical"]},
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
  pin TEXT,                       -- legacy plaintext column, emptied by migrate_db()
  pin_hash TEXT,                  -- v1.3: PBKDF2-HMAC-SHA256 of the PIN
  pin_salt TEXT,                  -- v1.3: per-user random salt (hex)
  offline_hash TEXT,              -- v1.3: cheap HMAC verifier for the reader's offline cache
  name_enc TEXT,                  -- v1.4: Fernet-encrypted name (name column blanked)
  rfid_enc TEXT,                  -- v1.4: Fernet-encrypted card UID; rfid_hex holds the blind index
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


def migrate_db(con):
    """Bring an older database up to the current shape. Safe to re-run.

    v1.3 — add pin_hash / pin_salt / offline_hash and hash any plaintext PINs.
    v1.4 — add name_enc / rfid_enc and encrypt the name and card UID in place.
    Both passes only touch rows that still need it, so start-up is a no-op once
    the database is current.
    """
    cols = {r["name"] for r in con.execute("PRAGMA table_info(users)")}
    for col in ("pin_hash", "pin_salt", "offline_hash", "name_enc", "rfid_enc"):
        if col not in cols:
            con.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")

    # ---- v1.3: hash any PIN still stored in the clear ----
    rows = con.execute(
        "SELECT id, rfid_hex, rfid_enc, pin FROM users"
        " WHERE pin_hash IS NULL AND pin IS NOT NULL AND pin != ''"
    ).fetchall()
    for r in rows:
        salt = make_salt()
        raw_card = dec(r["rfid_enc"], r["rfid_hex"] or "")
        con.execute(
            "UPDATE users SET pin_hash=?, pin_salt=?, offline_hash=?, pin='' WHERE id=?",
            (hash_pin(r["pin"], salt), salt, offline_hash(raw_card, r["pin"]), r["id"]))
    if rows:
        con.commit()
        print(f"Migrated {len(rows)} PIN(s) to salted hashes (plaintext cleared).")

    # ---- v1.4: encrypt names and card UIDs ----
    encrypted_rows = con.execute(
        "SELECT COUNT(*) c FROM users WHERE rfid_enc IS NOT NULL").fetchone()["c"]

    if not ENCRYPTION_ON:
        if encrypted_rows and _HAVE_FERNET:
            # A key existed once and is gone now. Starting anyway would leave every
            # card unmatchable, so stop with an explanation instead.
            raise SystemExit(
                "\nThis database is encrypted but no key was found.\n"
                "Restore secret.key next to cnc.db, or set CNC_SECRET_KEY, then start again.\n"
                "(Refusing to continue so the encrypted rows are not damaged.)")
        if encrypted_rows:
            raise SystemExit(
                "\nThis database is encrypted but the `cryptography` package is missing.\n"
                "Run:  pip install cryptography\n")
        if _HAVE_FERNET:
            _use_key(_create_key())     # nothing encrypted yet: safe to start fresh
        else:
            return

    if encrypted_rows:
        # Confirm the key we loaded is the one this database was written with.
        probe = con.execute(
            "SELECT rfid_enc FROM users WHERE rfid_enc IS NOT NULL LIMIT 1").fetchone()
        if not dec(probe["rfid_enc"], ""):
            raise SystemExit(
                "\nThe encryption key does not match this database.\n"
                "secret.key (or CNC_SECRET_KEY) is from a different install.\n"
                "(Refusing to continue so the encrypted rows are not damaged.)")

    pending = con.execute(
        "SELECT id, name, rfid_hex FROM users WHERE rfid_enc IS NULL").fetchall()
    for r in pending:
        raw_card = (r["rfid_hex"] or "").strip().upper()
        con.execute(
            "UPDATE users SET name_enc=?, rfid_enc=?, rfid_hex=?, name='' WHERE id=?",
            (enc(r["name"]), enc(raw_card), card_id(raw_card), r["id"]))
    if pending:
        con.commit()
        print(f"Encrypted {len(pending)} user record(s) at rest "
              f"(names and card UIDs; lookups now use a blind index).")


def seed_user(con, name, rfid, pin, level, status):
    """Insert a user with the PIN hashed and the name / card UID encrypted."""
    salt = make_salt()
    rfid = rfid.strip().upper()
    return con.execute(
        "INSERT INTO users(name,name_enc,rfid_hex,rfid_enc,pin,pin_hash,pin_salt,"
        "                  offline_hash,cert_level,status)"
        " VALUES(?,?,?,?,'',?,?,?,?,?)",
        ("" if ENCRYPTION_ON else name, enc(name),
         card_id(rfid), enc(rfid),
         hash_pin(pin, salt), salt, offline_hash(rfid, pin), level, status))


def init_db():
    fresh = not os.path.exists(DB)
    con = db()
    con.executescript(SCHEMA)
    migrate_db(con)
    if fresh or con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        for u in SEED_USERS:
            seed_user(con, *u)
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
                                   "version": "1.4"})
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
            return self.send_json({"ok": True, "version": "1.4", "users": users,
                                   "active_users": active, "open_sessions": opens,
                                   "last_scan_age": scan_age, "changelog": CHANGELOG})
        if path == "/api/users":
            # v1.4: this used to be open to anyone on the network, which meant the
            # full card list was one curl away. It is admin-only now.
            if not self.authed():
                return self.send_json({"error": "unauthorized"}, 401)
            # v1.3: PINs are hashed, so the admin page can no longer display them.
            # v1.4: names and card UIDs are decrypted here, for this page only.
            con = db()
            rows = []
            for r in con.execute(
                    "SELECT id,name,name_enc,rfid_hex,rfid_enc,cert_level,status,"
                    "       (pin_hash IS NOT NULL) AS has_pin"
                    " FROM users ORDER BY id"):
                rows.append({"id": r["id"], "name": user_name(r),
                             "rfid_hex": user_card(r), "cert_level": r["cert_level"],
                             "status": r["status"], "has_pin": r["has_pin"]})
            con.close()
            return self.send_json(rows)

        # ---- roster for the Pico's offline cache (v1.3) ----
        # Sends hashes only, never PINs, so a stolen Pico does not leak them.
        if path == "/api/roster":
            if not self.is_device():
                return self.send_json({"error": "bad device key"}, 401)
            # v1.4: the reader gets a hashed card id, not the real UID, and no
            # names at all. roster.json on a stolen Pico is then useless as a
            # card list. The Pico hashes the UID it just read and compares.
            con = db()
            rows = []
            for r in con.execute(
                    "SELECT rfid_hex,rfid_enc,cert_level,offline_hash FROM users"
                    " WHERE status='active' AND offline_hash IS NOT NULL"):
                raw = user_card(r).upper()
                rows.append({"rfid_id": hmac.new(OFFLINE_KEY, raw.encode(),
                                                 hashlib.sha256).hexdigest(),
                             "cert_level": r["cert_level"],
                             "offline_hash": r["offline_hash"]})
            con.close()
            return self.send_json({"ok": True, "issued_at": now_str(), "users": rows})
        if path == "/api/logs":
            con = db()
            access, events = [], []
            for r in con.execute("""
                SELECT a.id, u.name AS name, u.name_enc AS name_enc,
                       a.login_at AS login, a.logout_at AS logout
                FROM access_logs a LEFT JOIN users u ON u.id=a.user_id
                ORDER BY a.login_at"""):
                access.append({"id": r["id"], "user": user_name(r) or "Deleted user",
                               "login": r["login"], "logout": r["logout"]})
            for r in con.execute("""
                SELECT e.id, u.name AS name, u.name_enc AS name_enc,
                       e.type, e.note, e.created_at AS time
                FROM event_logs e LEFT JOIN users u ON u.id=e.user_id
                ORDER BY e.created_at DESC"""):
                events.append({"id": r["id"], "user": user_name(r) or "Deleted user",
                               "type": r["type"], "note": r["note"], "time": r["time"]})
            con.close()
            return self.send_json({"access": access, "events": events})
        return self.serve_static(path)

    # ---------- POST ----------
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/login":
            d = self.body_json()
            supplied = hashlib.pbkdf2_hmac(
                "sha256", (d.get("password") or "").encode(), ADMIN_SALT, 100_000).hex()
            if d.get("username") == ADMIN_USER and hmac.compare_digest(supplied, ADMIN_PASS_HASH):
                return self.send_json({"ok": True, "token": ADMIN_TOKEN})
            return self.send_json({"ok": False}, 401)
        if path == "/api/users":
            if not self.authed():
                return self.send_json({"error": "unauthorized"}, 401)
            d = self.body_json()
            pin = str(d.get("pin", "")).strip()
            if not (len(pin) == 4 and pin.isdigit()):
                return self.send_json({"error": "PIN must be exactly 4 digits"}, 400)
            con = db()
            try:
                salt = make_salt()
                raw_card = (d["rfid_hex"] or "").strip().upper()
                cur = con.execute(
                    "INSERT INTO users(name,name_enc,rfid_hex,rfid_enc,pin,pin_hash,"
                    "                  pin_salt,offline_hash,cert_level,status)"
                    " VALUES(?,?,?,?,'',?,?,?,?,?)",
                    ("" if ENCRYPTION_ON else d["name"], enc(d["name"]),
                     card_id(raw_card), enc(raw_card),
                     hash_pin(pin, salt), salt, offline_hash(raw_card, pin),
                     d.get("cert_level", "none"), d.get("status", "active")))
                con.commit()
                d["id"] = cur.lastrowid
                d.pop("pin", None)          # never echo the PIN back
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
                "SELECT id,name,name_enc,cert_level,pin_hash,pin_salt,status FROM users"
                " WHERE " + card_where(), (card_id(rfid),)).fetchone()
            ok = bool(row) and row["status"] == "active" and pin_ok(row, pin)
            if ok:
                con.execute(
                    "INSERT INTO access_logs(user_id,login_at,logout_at) VALUES(?,?,?)",
                    (row["id"], now_str(), None))
                con.commit()
            con.close()
            if ok:
                return self.send_json({"authorized": True,
                                       "name": user_name(row),
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
            row = con.execute("SELECT id FROM users WHERE " + card_where(),
                              (card_id(rfid),)).fetchone()
            con.execute(
                "INSERT INTO event_logs(user_id,type,note,created_at) VALUES(?,?,?,?)",
                (row["id"] if row else None, d.get("type", "ok"), d.get("note", ""), now_str()))
            con.commit(); con.close()
            return self.send_json({"ok": True})

        # ---- the Pico uploads records it buffered while offline (v1.3) ----
        if path == "/api/sync":
            if not self.is_device():
                return self.send_json({"error": "bad device key"}, 401)
            d = self.body_json()
            entries = d.get("entries") or []
            con = db()
            saved = 0
            for e in entries:
                rfid = (e.get("rfid_hex") or "").strip().upper()
                row = con.execute("SELECT id FROM users WHERE " + card_where(),
                                  (card_id(rfid),)).fetchone()
                uid = row["id"] if row else None
                when = e.get("at") or now_str()
                kind = e.get("kind")
                if kind == "login":
                    con.execute("INSERT INTO access_logs(user_id,login_at,logout_at)"
                                " VALUES(?,?,?)", (uid, when, e.get("logout_at")))
                elif kind == "logout":
                    con.execute("""
                        UPDATE access_logs SET logout_at=?
                        WHERE id = (SELECT id FROM access_logs
                                    WHERE user_id=? AND logout_at IS NULL
                                    ORDER BY id DESC LIMIT 1)""", (when, uid))
                else:
                    con.execute("INSERT INTO event_logs(user_id,type,note,created_at)"
                                " VALUES(?,?,?,?)",
                                (uid, e.get("type", "offline"),
                                 e.get("note", "buffered on the reader"), when))
                saved += 1
            con.commit(); con.close()
            return self.send_json({"ok": True, "saved": saved})

        # ---- close the current access session (sign out) ----
        if path == "/api/logout":
            if not (self.is_device() or self.authed()):
                return self.send_json({"error": "unauthorized"}, 401)
            d = self.body_json()
            rfid = (d.get("rfid_hex") or "").strip().upper()
            con = db()
            row = con.execute("SELECT id FROM users WHERE " + card_where(),
                              (card_id(rfid),)).fetchone()
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
            pin = str(d.get("pin", "")).strip()
            con = db()
            raw_card = (d["rfid_hex"] or "").strip().upper()
            con.execute(
                "UPDATE users SET name=?,name_enc=?,rfid_hex=?,rfid_enc=?,"
                "                 cert_level=?,status=? WHERE id=?",
                ("" if ENCRYPTION_ON else d["name"], enc(d["name"]),
                 card_id(raw_card), enc(raw_card),
                 d["cert_level"], d["status"], uid))
            # An empty PIN field means "keep the current PIN" — we cannot show the
            # old one in the form any more, because only its hash is stored.
            if pin:
                if not (len(pin) == 4 and pin.isdigit()):
                    con.close()
                    return self.send_json({"error": "PIN must be exactly 4 digits"}, 400)
                salt = make_salt()
                con.execute(
                    "UPDATE users SET pin='', pin_hash=?, pin_salt=?, offline_hash=? WHERE id=?",
                    (hash_pin(pin, salt), salt, offline_hash(raw_card, pin), uid))
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


def print_security_banner():
    if ENCRYPTION_ON:
        print("Encryption at rest: ON  (names + card UIDs encrypted; key:",
              os.path.basename(KEY_FILE) + ")")
    elif not _HAVE_FERNET:
        print("Encryption at rest: OFF - the `cryptography` package is not installed.")
        print("  PINs and the admin password are still hashed, but card UIDs and names")
        print("  are stored in the clear. Turn it on with:  pip install cryptography")
    else:
        print("Encryption at rest: OFF - no key available.")


if __name__ == "__main__":
    init_db()
    print_security_banner()
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
