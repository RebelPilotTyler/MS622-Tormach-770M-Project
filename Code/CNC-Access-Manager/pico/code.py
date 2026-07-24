# code.py  —  CNC Access Manager: on-machine controller (Pico 2 W, CircuitPython 10.x)
# =============================================================================
# Integrates Glenn's hardware (I2C MFRC522 RFID + 3x4 keypad + LEDs + buzzer +
# relay) with Mason's server (SQLite `cnc.db`) over Wi-Fi. The card database is
# the single source of truth; the Pico asks the server to verify each card+PIN.
#
# FLOW:  tap card -> enter PIN -> POST /api/verify {rfid_hex, pin}
#        server checks cnc.db (active + pin match) -> logs the access -> yes/no
#        yes -> green + relay ON (machine enabled).  Tap same card again -> sign
#        out (relay OFF + POST /api/logout).  Wrong PIN x3 -> temporary lockout.
#
# ON THE CIRCUITPY DRIVE YOU NEED:
#   /code.py  /mfrc522_i2c.py  /settings.toml
#   /lib/adafruit_requests.mpy  /lib/adafruit_connection_manager.mpy
#   (install libs with:  circup install adafruit_requests adafruit_connection_manager)
#
# WIRING (Glenn's build):
#   RC522 (I2C)  SDA=GP2 SCL=GP3 addr 0x28
#   Keypad C2=GP4 R1=GP5 C1=GP6 R4=GP7 C3=GP8 R3=GP9 R2=GP10
#   LEDs yellow=GP19 red=GP20 green=GP21   Buzzer=GP22   Relay=GP16
# =============================================================================

import os, time, json, board, busio, digitalio, pwmio
import wifi, socketpool, ssl
import adafruit_requests
import adafruit_hashlib as hashlib
from mfrc522_i2c import MFRC522_I2C

# ---------------- config (from settings.toml) ----------------
WIFI_SSID     = os.getenv("WIFI_SSID")
WIFI_PASSWORD = os.getenv("WIFI_PASSWORD")
SERVER_URL    = (os.getenv("SERVER_URL") or "").rstrip("/")
DEVICE_KEY    = os.getenv("DEVICE_KEY") or "pico-770"
# Must match OFFLINE_KEY in server.py — used to check cards during an outage.
OFFLINE_KEY   = (os.getenv("OFFLINE_KEY") or "cnc-770-offline-pepper-change-me").encode()
# Glenn's firmware has no relay output yet, so the pin is still unconfirmed.
# Keeping it in settings.toml means his answer can be applied without a code edit.
RELAY_GP      = int(os.getenv("RELAY_GP") or 16)

# ---------------- tunables ----------------
RC522_ADDRESS      = 0x28
PIN_LENGTH         = 4
PIN_ENTRY_TIMEOUT  = 15.0
KEY_DEBOUNCE_TIME  = 0.15
CARD_REMOVAL_DELAY = 0.75
HTTP_TIMEOUT       = 6          # seconds per request
HTTP_RETRIES       = 1          # extra tries on network error
MAX_PIN_ATTEMPTS   = 3          # wrong PINs before lockout
LOCKOUT_SECONDS    = 30         # lockout duration after too many wrong PINs
WIFI_RETRY_SECONDS = 5
ROSTER_FILE        = "/roster.json"        # offline copy of the authorized list
QUEUE_FILE         = "/offline_queue.json" # taps recorded while the server was down
MAX_QUEUE          = 100        # ring buffer cap, same idea as Erik's MAX_LOG_ENTRIES
ROSTER_REFRESH     = 900        # re-download the roster every 15 minutes

# ---------------- pins ----------------
RFID_SDA_PIN = board.GP2; RFID_SCL_PIN = board.GP3
KEYPAD_C2_PIN = board.GP4; KEYPAD_R1_PIN = board.GP5
KEYPAD_C1_PIN = board.GP6; KEYPAD_R4_PIN = board.GP7
KEYPAD_C3_PIN = board.GP8; KEYPAD_R3_PIN = board.GP9
KEYPAD_R2_PIN = board.GP10
YELLOW_LED_PIN = board.GP19; RED_LED_PIN = board.GP20
GREEN_LED_PIN  = board.GP21; BUZZER_PIN  = board.GP22
RELAY_PIN = getattr(board, "GP%d" % RELAY_GP)

# ---------------- outputs ----------------
def _out(pin, value=False):
    d = digitalio.DigitalInOut(pin); d.direction = digitalio.Direction.OUTPUT
    d.value = value; return d
yellow_led = _out(YELLOW_LED_PIN); red_led = _out(RED_LED_PIN)
green_led  = _out(GREEN_LED_PIN);  relay   = _out(RELAY_PIN, False)

buzzer = pwmio.PWMOut(BUZZER_PIN, duty_cycle=0, frequency=2000, variable_frequency=True)
def tone(freq, dur, pause=0.0):
    buzzer.frequency = freq; buzzer.duty_cycle = 32768
    time.sleep(dur); buzzer.duty_cycle = 0
    if pause: time.sleep(pause)
def key_beep():  tone(1700, 0.045)
def good_beep(): tone(2200, 0.08, 0.04); tone(2850, 0.12)
def bad_beep():  tone(550, 0.16, 0.10);  tone(550, 0.16)

def leds(y=False, r=False, g=False):
    yellow_led.value = y; red_led.value = r; green_led.value = g
def waiting():    leds(y=True)
def running():    leds(g=True)   # green stays solid the whole time the mill is live
def granted_fx(): leds(g=True); good_beep(); time.sleep(1.0)
def denied_fx():  leds(r=True); bad_beep(); time.sleep(0.8); leds(y=True)
def offline_fx():
    # two short yellow blinks = "granted from the cached roster, server is down"
    for _ in range(2):
        leds(); time.sleep(0.12); leds(y=True); time.sleep(0.12)
def lockout_fx():
    for _ in range(int(LOCKOUT_SECONDS)):
        leds(r=True); time.sleep(0.5); leds(); time.sleep(0.5)
    waiting()

# ---------------- keypad ----------------
row_pins = [KEYPAD_R1_PIN, KEYPAD_R2_PIN, KEYPAD_R3_PIN, KEYPAD_R4_PIN]
col_pins = [KEYPAD_C1_PIN, KEYPAD_C2_PIN, KEYPAD_C3_PIN]
key_map = [["1","2","3"], ["4","5","6"], ["7","8","9"], ["*","0","#"]]
rows = []
for p in row_pins:
    r = digitalio.DigitalInOut(p); r.direction = digitalio.Direction.OUTPUT
    r.value = True; rows.append(r)
cols = []
for p in col_pins:
    c = digitalio.DigitalInOut(p); c.direction = digitalio.Direction.INPUT
    c.pull = digitalio.Pull.UP; cols.append(c)
def scan_keypad():
    for ri, r in enumerate(rows):
        r.value = False; time.sleep(0.001)
        for ci, c in enumerate(cols):
            if not c.value:
                r.value = True; return key_map[ri][ci]
        r.value = True
    return None
def get_key():
    k = scan_keypad()
    if k is None: return None
    key_beep()
    while scan_keypad() is not None: time.sleep(0.01)
    time.sleep(KEY_DEBOUNCE_TIME)
    return k
def read_pin():
    entered = ""; start = time.monotonic()
    print("Enter PIN  (* clear, # submit)")
    while True:
        if time.monotonic() - start >= PIN_ENTRY_TIMEOUT:
            print("PIN timeout."); return None
        k = get_key()
        if k is None: time.sleep(0.01); continue
        if k == "*": entered = ""; print("cleared"); continue
        if k == "#": return entered
        if k.isdigit():
            entered += k; print("PIN:", "*" * len(entered))
            if len(entered) >= PIN_LENGTH: return entered

# ---------------- Wi-Fi + HTTP (robust) ----------------
pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

def ensure_wifi():
    """Connect (or reconnect) Wi-Fi. Returns True when connected."""
    if wifi.radio.connected:
        return True
    print("Wi-Fi: connecting to", WIFI_SSID)
    try:
        wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
        print("Wi-Fi OK, IP:", wifi.radio.ipv4_address)
        return True
    except Exception as e:
        print("Wi-Fi failed:", repr(e)); return False

def http_post(path, payload):
    """POST JSON with reconnect + retry. Returns dict or None on failure."""
    for attempt in range(HTTP_RETRIES + 1):
        if not ensure_wifi():
            time.sleep(WIFI_RETRY_SECONDS); continue
        try:
            r = requests.post(SERVER_URL + path, json=payload,
                              headers={"X-Device-Key": DEVICE_KEY},
                              timeout=HTTP_TIMEOUT)
            data = r.json(); r.close()
            return data
        except Exception as e:
            print("HTTP error on", path, ":", repr(e))
            time.sleep(0.5)
    return None

def server_ok():
    """Boot health check."""
    if not ensure_wifi():
        return False
    try:
        r = requests.get(SERVER_URL + "/api/health", timeout=HTTP_TIMEOUT)
        ok = bool(r.json().get("ok")); r.close(); return ok
    except Exception as e:
        print("health check failed:", repr(e)); return False

def http_get(path):
    """GET JSON with the device key. Returns dict or None."""
    if not ensure_wifi():
        return None
    try:
        r = requests.get(SERVER_URL + path,
                         headers={"X-Device-Key": DEVICE_KEY}, timeout=HTTP_TIMEOUT)
        data = r.json(); r.close()
        return data
    except Exception as e:
        print("HTTP GET error on", path, ":", repr(e)); return None


# =============================================================================
# Offline operation (v1.3)
# -----------------------------------------------------------------------------
# Before this, a Wi-Fi drop or a sleeping admin PC meant /api/verify failed and
# the mill could not be started at all — the lab lost the machine because of a
# laptop. The reader now keeps its own copy of the authorized list and falls
# back to it, then uploads whatever it recorded once the server returns.
#
# NOTE: writing to the CIRCUITPY drive requires boot.py to remount it writable.
# If that is missing, the cache degrades gracefully to in-RAM only.
# =============================================================================

def _hmac_sha256(key, msg):
    """HMAC-SHA256 — adafruit_hashlib has no hmac module, so it is done by hand."""
    block = 64
    if len(key) > block:
        key = hashlib.sha256(key).digest()
    key = key + b"\x00" * (block - len(key))
    inner = hashlib.sha256(bytes(b ^ 0x36 for b in key) + msg).digest()
    return hashlib.sha256(bytes(b ^ 0x5C for b in key) + inner).hexdigest()

def offline_hash(uid_hex, pin):
    return _hmac_sha256(OFFLINE_KEY, (uid_hex.upper() + ":" + pin).encode())

def _read_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def _write_json(path, obj):
    try:
        with open(path, "w") as f:
            json.dump(obj, f)
        return True
    except Exception as e:
        print("cannot write", path, "-", repr(e), "(is boot.py remounting the drive?)")
        return False

roster = _read_json(ROSTER_FILE, {"users": []})
queue  = _read_json(QUEUE_FILE, [])
last_roster_sync = 0.0

def refresh_roster(force=False):
    """Pull the authorized list from the server and cache it on the drive."""
    global roster, last_roster_sync
    if not force and time.monotonic() - last_roster_sync < ROSTER_REFRESH:
        return
    data = http_get("/api/roster")
    if data and data.get("ok"):
        roster = {"users": data.get("users", []), "issued_at": data.get("issued_at")}
        _write_json(ROSTER_FILE, roster)
        last_roster_sync = time.monotonic()
        print("Roster cached:", len(roster["users"]), "active users")

def queue_entry(entry):
    """Append to the local ring buffer (oldest dropped past MAX_QUEUE)."""
    queue.append(entry)
    while len(queue) > MAX_QUEUE:
        queue.pop(0)
    _write_json(QUEUE_FILE, queue)

def flush_queue():
    """Upload anything buffered while offline, then clear it."""
    global queue
    if not queue:
        return
    result = http_post("/api/sync", {"entries": queue})
    if result and result.get("ok"):
        print("Synced", result.get("saved"), "buffered record(s).")
        queue = []
        _write_json(QUEUE_FILE, queue)

def check_offline(uid_hex, pin):
    """Verify a card + PIN against the cached roster."""
    want = offline_hash(uid_hex, pin)
    for u in roster.get("users", []):
        if u.get("rfid_hex", "").upper() == uid_hex.upper():
            if u.get("offline_hash") == want:
                return {"authorized": True, "name": u.get("name"),
                        "cert_level": u.get("cert_level"), "offline": True}
            return {"authorized": False, "reason": "bad pin", "offline": True}
    return {"authorized": False, "reason": "unknown card", "offline": True}

def check_access(uid_hex, pin):
    data = http_post("/api/verify", {"rfid_hex": uid_hex, "pin": pin})
    if data is None:
        print("Server unreachable — falling back to the cached roster.")
        result = check_offline(uid_hex, pin)
        if result.get("authorized"):
            queue_entry({"kind": "login", "rfid_hex": uid_hex, "at": None})
        else:
            queue_entry({"kind": "event", "rfid_hex": uid_hex, "type": "denied_offline",
                         "note": "denied against cached roster: " + str(result.get("reason")),
                         "at": None})
        return result
    return data

def sign_out(uid_hex):
    if http_post("/api/logout", {"rfid_hex": uid_hex}) is None:
        queue_entry({"kind": "logout", "rfid_hex": uid_hex, "at": None})

def log_event(uid_hex, etype, note):
    if http_post("/api/event", {"rfid_hex": uid_hex, "type": etype, "note": note}) is None:
        queue_entry({"kind": "event", "rfid_hex": uid_hex, "type": etype,
                     "note": note, "at": None})

# ---------------- startup ----------------
print("\n==== CNC Access Manager (Pico 2 W) ====")
print("Relay on GP%d" % RELAY_GP)
ensure_wifi()
online = server_ok()
print("Server reachable:", online)
if online:
    refresh_roster(force=True)
    flush_queue()
else:
    print("Starting offline with", len(roster.get("users", [])), "cached user(s).")

i2c = busio.I2C(RFID_SCL_PIN, RFID_SDA_PIN, frequency=50000)
while not i2c.try_lock():
    pass
try:
    print("I2C devices:", ["0x%02X" % a for a in i2c.scan()])
finally:
    i2c.unlock()
reader = MFRC522_I2C(i2c, address=RC522_ADDRESS, debug=False)
print("MFRC522 VersionReg: 0x%02X" % reader.version())
print("Ready. Present a card.\n")
waiting()

# ---------------- main loop ----------------
machine_on = False
current_uid = None
last_uid = None
last_seen = 0.0

while True:
    try:
        uid = reader.read_uid()
    except Exception as e:
        print("RFID error:", repr(e)); waiting(); time.sleep(0.25); continue

    if uid is None:
        if time.monotonic() - last_seen > CARD_REMOVAL_DELAY:
            last_uid = None
        # Idle time is the cheapest moment to refresh the cache and drain the
        # offline queue, so neither ever delays someone standing at the machine.
        if not machine_on:
            refresh_roster()
            if queue:
                flush_queue()
        time.sleep(0.05); continue

    last_seen = time.monotonic()
    uid_hex = "".join("%02X" % b for b in uid)
    if uid_hex == last_uid:
        time.sleep(0.05); continue
    last_uid = uid_hex
    leds()
    print("\nCARD:", uid_hex)

    # tap the active card again -> sign out
    if machine_on and uid_hex == current_uid:
        relay.value = False; machine_on = False; current_uid = None
        print("Signed out. Machine disabled.")
        sign_out(uid_hex)
        good_beep(); waiting()
        flush_queue()
        continue

    # verify with PIN, with a wrong-PIN lockout
    attempts = 0
    granted = False
    while attempts < MAX_PIN_ATTEMPTS:
        pin = read_pin()
        if pin is None:            # timeout counts as a failed attempt
            attempts += 1; denied_fx(); continue
        result = check_access(uid_hex, pin)
        if result.get("authorized"):
            print("GRANTED:", result.get("name"), "level", result.get("cert_level"))
            relay.value = True; machine_on = True; current_uid = uid_hex
            granted_fx()
            if result.get("offline"):
                print("(verified from the cached roster — server offline)")
                offline_fx()
            running()          # green stays on so it is obvious the mill is live
            print("Machine ENABLED. Tap same card to sign out.\n")
            granted = True
            break
        reason = result.get("reason")
        print("DENIED:", reason)
        # only PIN mistakes count toward lockout; unknown/disabled just deny
        if reason == "bad pin":
            attempts += 1; denied_fx()
        else:
            denied_fx(); break

    if not granted and attempts >= MAX_PIN_ATTEMPTS:
        print("Too many wrong PINs. Locked out for", LOCKOUT_SECONDS, "s.")
        log_event(uid_hex, "lockout", "Too many wrong PIN attempts")
        lockout_fx()

    # Require card removal before the next attempt. Following Glenn's firmware,
    # a read error is treated as "no card" rather than breaking out of the wait —
    # otherwise I2C noise lets a second attempt start with the card still down.
    while True:
        try:
            card_still_present = reader.read_uid()
        except OSError:
            card_still_present = None
        except Exception:
            card_still_present = None
        if card_still_present is None:
            break
        time.sleep(0.10)
    last_uid = None
    running() if machine_on else waiting()
