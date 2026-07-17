# CNC Access Manager — Hardware ↔ Software Integration (Pico 2 W + Wi-Fi)

Connects **Glenn's on-machine hardware** (Raspberry Pi Pico 2 W, I2C MFRC522
RFID reader, 3×4 keypad, LEDs, buzzer, relay) to **Mason's server**
(`server.py` + SQLite `cnc.db`). The card database is the single source of
truth; the Pico asks the server over Wi-Fi to verify each card + PIN, and the
server logs every access. Adding/removing users happens only in the web app.

---

## 1. Data flow

```
  [ RFID card ] + [ PIN pad ]
          │  Glenn's hardware (Pico 2 W, CircuitPython)
          ▼
   Pico 2 W ──Wi-Fi──►  server.py (PC on the same network)
      ▲   │                 POST /api/verify {rfid_hex, pin}
      │   │                 → checks cnc.db (status=active, pin match)
      │   │                 → writes an access_log row
      │   ▼
   green LED + relay ON (machine enabled)   /   red LED (denied)
   tap same card again ──► POST /api/logout (closes the session)
```

## 2. Files on the Pico's CIRCUITPY drive

| File | Purpose |
|------|---------|
| `code.py` | main controller (auto-runs) |
| `mfrc522_i2c.py` | Glenn's I2C RFID driver |
| `settings.toml` | Wi-Fi + server IP + device key |
| `/lib/adafruit_requests.mpy` | HTTP client |
| `/lib/adafruit_connection_manager.mpy` | required by adafruit_requests |

`rfid_test.py` = standalone reader test. `circup-requirements.txt` = library list.

## 3. Wiring (Glenn's build)

- RC522 (I2C): **SDA=GP2, SCL=GP3**, address **0x28**
- Keypad: C2=GP4, R1=GP5, C1=GP6, R4=GP7, C3=GP8, R3=GP9, R2=GP10
- LEDs: yellow=GP19, red=GP20, green=GP21 · Buzzer=GP22
- **Relay (machine enable) = GP16** ← change in `code.py` to match the relay wiring

---

## 4. One-time setup (latest tools)

**a. Flash CircuitPython 10.2.0 (2026) for the Pico 2 W (RP2350)**
Download the `.uf2` from the official board page, hold BOOTSEL while plugging in
USB, and drop the file onto the RP2350 drive:
https://circuitpython.org/board/raspberry_pi_pico2_w/

**b. Install the libraries with `circup` (recommended, always latest)**
```
pip install circup
circup install -r circup-requirements.txt
```
`circup` copies the matching-version `.mpy` files straight to CIRCUITPY.
Known quirk: circup sometimes skips the ConnectionManager dependency, so the
requirements file lists it explicitly (Adafruit_CircuitPython_Requests issue #157).

*Manual alternative:* download the CircuitPython **10.x** library bundle and copy
`adafruit_requests.mpy` + `adafruit_connection_manager.mpy` into `/lib`.
Bundle releases: https://github.com/adafruit/Adafruit_CircuitPython_Bundle/releases

**c. Edit `settings.toml`**
- `WIFI_SSID` / `WIFI_PASSWORD` — your lab Wi-Fi (2.4 GHz)
- `SERVER_URL` — the PC running `server.py`, e.g. `http://192.168.1.50:8000`
  (Windows: `ipconfig` → IPv4 Address)
- `DEVICE_KEY` — keep `pico-770` (must match `server.py`)

**d.** Put the PC and Pico on the **same Wi-Fi**, and run `py server.py`.

---

## 5. Confirm the RFID reader actually reads cards

1. Copy `mfrc522_i2c.py` + `rfid_test.py` to the Pico; rename `rfid_test.py`
   to `code.py` (or run from the REPL).
2. Open the serial console (Thonny / Mu / PuTTY). Expect:
   ```
   I2C devices: ['0x28']
   MFRC522 VersionReg: 0x92        (0x91 or 0x92 = a genuine MFRC522)
   CARD UID: A388DB1C   (register this in the web app)
   ```
3. Empty `I2C devices` or missing `0x28` → check SDA/SCL wiring and 3V3 power.
4. **Copy each real card's UID** — you register these in the web app next.

## 6. Register a real card so access is granted

1. Run the server, open `http://localhost:8000` (login `admin` / `admin`).
2. **Users → Add user**: paste the real UID (e.g. `A388DB1C`) into
   **Card (RFID hex)**, set a **PIN**, level, status = active. Save.
3. Put the full networked `code.py` back on the Pico.
4. Tap the card, enter the PIN → green LED + relay ON, and the tap appears on
   the web app's **Logs** page. Tap the same card again to sign out.

### The "Scan" button (enrollment) — how it really works

The admin web page runs on a laptop with **no reader attached**, so the browser
cannot read a card directly. That is why the old Scan button only made up a
random ID. Real options:

1. **Enrollment mode (built in).** Run `enroll.py` on the Pico. Each tap POSTs
   the card UID to `POST /api/scan`; the server remembers the last one. In
   **Add user**, press **Scan** and it pulls the card you just tapped
   (`GET /api/last-scan`). If no reader has scanned recently it tells you to type
   the ID manually — it never invents a fake ID.
2. **USB keyboard-wedge reader.** Many cheap USB RFID readers act like a keyboard:
   click the Card field and tap — the UID is "typed" in. Zero code.
3. **Manual entry.** Read the UID from `rfid_test.py` in the serial console and
   type it into the Card field.

Test enrollment without a Pico (server running):
```
curl -X POST http://localhost:8000/api/scan -H "X-Device-Key: pico-770" ^
  -H "Content-Type: application/json" -d "{\"uid\":\"A388DB1C\"}"
```
Then press **Scan** in Add user within ~12 s and the field fills with `A388DB1C`.

### System tab

The web app's **System** tab shows live status you *can* verify from the laptop —
server reachable, database user counts, open machine sessions, and whether a
reader has scanned recently (so you can see the hardware link working) — plus the
system update history.

## 7. Robustness built into `code.py`

- **Wi-Fi auto-reconnect** before every request (`ensure_wifi`).
- **Timeout + retry** on each HTTP call; if the server is unreachable the card is
  simply denied (fail-safe), never left hanging.
- **Boot health check** (`GET /api/health`) reports whether the server is reachable.
- **Wrong-PIN lockout**: after 3 bad PINs the reader blinks red and locks out for
  30 s (both configurable at the top of `code.py`), and logs a `lockout` event.
- **Proper sign-out**: tapping the active card again calls `/api/logout`, which
  closes the open session (sets `logout_at`) so Duration is correct on the Logs page.

## 8. Server API (for reference)

| Method | Path | Auth | Body | Purpose |
|--------|------|------|------|---------|
| GET  | `/api/health` | none | — | reachability check |
| POST | `/api/verify` | `X-Device-Key` | `{rfid_hex, pin}` | check card+PIN, log access |
| POST | `/api/logout` | device/admin | `{rfid_hex}` | close the open session |
| POST | `/api/event`  | device/admin | `{rfid_hex, type, note}` | log crash/dull-bit/etc. |
| GET  | `/api/users` · POST/PUT/DELETE | admin for writes | — | web-app user management |
| GET  | `/api/logs` | none | — | access + event logs |

Quick test without hardware (server running):
```
curl -X POST http://localhost:8000/api/verify ^
  -H "Content-Type: application/json" -H "X-Device-Key: pico-770" ^
  -d "{\"rfid_hex\":\"A1B2C3D4\",\"pin\":\"0770\"}"
```
→ `{"authorized": true, "name": "Mason Wang", "cert_level": "A"}`

---

## 9. Future-proofing / roadmap

- **Find the server without a fixed IP:** run the server with an mDNS name so the
  Pico can reach `http://cnc-lab.local:8000` instead of a hard-coded IP.
- **Security hardening:** hash PINs on the server (salted SHA-256); move the API to
  HTTPS on the lab network; rotate `DEVICE_KEY`. (Dr. Pacote's cyber audit — noted
  in the stand-up — fits here.)
- **On-machine event entry:** add an LCD + rotary encoder, or let students log a
  crash from the desktop, posting to `/api/event`; optionally email a push
  notification to the instructor when an event is logged.
- **OTA-style updates:** because it's CircuitPython, updating is just replacing
  files on CIRCUITPY — no compile step (this is exactly what Glenn liked about it).
- **Custom PCB:** the same pin map moves onto the Fusion Electronics PCB unchanged.

## 10. Source links (latest)

- CircuitPython 10.2.0 for Pico 2 W — https://circuitpython.org/board/raspberry_pi_pico2_w/
- CircuitPython 10.2.0 release notes — https://blog.adafruit.com/2026/04/22/circuitpython-10-2-0-released/
- Adafruit_CircuitPython_Requests — https://github.com/adafruit/Adafruit_CircuitPython_Requests
- Adafruit_CircuitPython_ConnectionManager — https://github.com/adafruit/Adafruit_CircuitPython_ConnectionManager
- circup (library installer) — https://github.com/adafruit/circup
- CircuitPython library bundle — https://github.com/adafruit/Adafruit_CircuitPython_Bundle/releases
