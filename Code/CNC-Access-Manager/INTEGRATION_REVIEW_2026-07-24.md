# Integration Review — Glenn's hardware code + Erik's Pico W proposal
**Mason Wang · 2026-07-24**

Reviewed: `GTcode.py`, `mfrc522_i2c.py` (Glenn, via GitHub commits `b9695df` / `795b113`),
`PicoW.txt`, `HowToUpdateThroughBash.txt` (Erik, via Teams 7/20)
against my current `pico/code.py`, `server.py`, and `schema.sql`.

---

## 1. Glenn's files — comparison result

| File | Status | Action |
|---|---|---|
| `mfrc522_i2c.py` | **Byte-for-byte identical** to my `pico/mfrc522_i2c.py` | None |
| `GTcode.py` (commit `b9695df`, 7/16) | Older version — **no yellow LED** | Superseded |
| `Code/code.py` (commit `795b113`, 7/17) | Current version — adds yellow LED on GP19 | Already matched |

My `pico/code.py` already matches Glenn's latest pin map and timing:

- RC522 I2C: SDA=GP2, SCL=GP3, address `0x28`, 50 kHz ✅
- Keypad: C2=GP4, R1=GP5, C1=GP6, R4=GP7, C3=GP8, R3=GP9, R2=GP10 ✅
- LEDs: yellow=GP19, red=GP20, green=GP21 · buzzer=GP22 ✅
- `KEY_DEBOUNCE_TIME = 0.15`, `PIN_ENTRY_TIMEOUT = 15.0`, `CARD_REMOVAL_DELAY = 0.75` ✅
- Buzzer tones (1700 / 2200+2850 / 550×2 Hz) ✅

**Conclusion: no re-sync needed. My firmware is current with Glenn's 7/17 build.**

### 1a. Three real gaps found

**GAP-1 — Relay pin is unconfirmed (blocker).**
Glenn's code has **no relay/solenoid output at all** — his build stops at LEDs + buzzer.
I use `RELAY_PIN = board.GP16`. Erik's file uses `SOLENOID_PIN = 15`.
Nobody has agreed on this pin. **Must confirm with Glenn before wiring**, or the relay
may collide with a pin he plans to use.

**GAP-2 — No indicator while the machine is enabled.**
In my `code.py`, `granted_fx()` shows green for 1 s, then all LEDs go off while the
relay stays ON. An operator walking up cannot tell the mill is live.
Fix: hold green solid the whole time `machine_on == True`.

**GAP-3 — Card-removal loop is less robust than Glenn's.**
Mine: `except Exception: break` — an I2C glitch exits the wait loop early and lets a
second attempt start with the card still on the reader.
Glenn's: treats `OSError` as "no card" and keeps looping. Adopt Glenn's pattern.

---

## 2. Erik's `PicoW.txt` — analysis

Erik's file is a **completely different architecture**, not an add-on:
MicroPython + Microdot web server running **on the Pico**, with `users.json`,
SHA-256 hashed PINs, and a local `access.log` ring buffer on the device itself.

### Why it cannot be adopted as-is — 4 hard conflicts

1. **Runtime conflict.** Erik: MicroPython (`machine`, `uasyncio`, `ujson`).
   Glenn: CircuitPython (`board`, `digitalio`, `pwmio`). One board, one runtime.
   Switching to Erik's discards Glenn's already-working keypad scan + I2C RC522 driver.
2. **Wiring conflict.** Erik drives the MFRC522 over **SPI** (SCK/MOSI/MISO/CS/RST =
   GP2/3/4/1/0). Glenn's board is **I2C at 0x28**. Physically different hookup, and
   Erik's SPI pins overlap Glenn's I2C + keypad pins (GP2, GP3, GP4).
3. **No keypad.** Erik reads the PIN with `entered = input("PIN: ")` over serial.
   That is also a real bug: `input()` blocks, so inside `asyncio` it freezes the web
   server for as long as someone is typing. Not usable with a physical keypad.
4. **Split source of truth.** His users live in `users.json` on the Pico; mine live in
   `cnc.db` on the PC. Two copies drift apart, and the instructor's admin page would
   no longer reflect what the machine actually enforces.

### Four ideas from Erik that ARE worth adopting

| # | Idea | Why it matters | Priority |
|---|---|---|---|
| E-1 | **Offline fallback cache** on the Pico | Today if Wi-Fi or the PC drops, `/api/verify` fails and the mill is dead. The lab losing access because a laptop slept is a real client problem. Erik's design is offline-native — we should at least cache the authorized list. | **High** |
| E-2 | **SHA-256 PIN hashing** | My `schema.sql` stores PINs in plaintext. Erik's `hash_pin()` confirms this needs fixing — already on my Week 3 task list. | **High** |
| E-3 | **Local ring-buffer log (100 entries) that syncs later** | Accountability is the whole point of the project; offline taps must not vanish. | Medium |
| E-4 | **Hashed admin password + HTTP Basic Auth** | My `/api/login` compares `admin`/`admin` in plaintext. | Medium |

`HowToUpdateThroughBash.txt` is just the curl example for Erik's `POST /admin/update`
endpoint. It does not apply to my server (my equivalent is `POST /api/users` with an
`X-Admin-Token` header), but it is a good reminder to document my API with curl examples.

---

## 3. Recommended update plan

### Do now (before hardware test)
- [ ] **U-1** Confirm the relay pin with Glenn (GP16 vs GP15 vs other) — blocking.
- [ ] **U-2** Keep the green LED solid while `machine_on` is True. (GAP-2)
- [ ] **U-3** Adopt Glenn's `except OSError → treat as no card` in the removal loop. (GAP-3)

### Do this week
- [ ] **U-4** Hash PINs with SHA-256 + per-user salt: add `pin_hash` to `schema.sql`,
      hash on write in `POST /api/users` and `PUT /api/users/<id>`, compare hashes in
      `/api/verify`. Include a one-time migration for existing rows.
- [ ] **U-5** Offline cache on the Pico: pull an authorized list (`rfid_hex` + `pin_hash`
      + `status`) from a new `GET /api/roster` at boot and every N minutes, store it on
      the CIRCUITPY drive, and verify against it when `/api/verify` is unreachable.
      Log offline grants locally and POST them on reconnect.
- [ ] **U-6** Hash `ADMIN_PASS` in `server.py`; stop comparing plaintext.

### Nice to have
- [ ] **U-7** Local ring-buffer log on the Pico (cap 100, like Erik's `MAX_LOG_ENTRIES`).
- [ ] **U-8** Add curl examples to `pico/INTEGRATION.md` for every endpoint.
- [ ] **U-9** Credit Glenn's `mfrc522_i2c.py` and note Erik's offline-cache idea in the
      changelog / `README.md`.

---

## 4. What to add to the Trello stand-up (Week 3/4)

**Accomplishments**
- (Week 3) MW: Reviewed Glenn's 7/17 firmware (`Code/code.py`, `mfrc522_i2c.py`) against
  my Pico integration — pin map, timing, and RC522 driver confirmed identical; no re-sync
  needed.
- (Week 3) MW: Evaluated Erik's MicroPython/Microdot Pico W proposal. Kept our
  CircuitPython + central-SQLite architecture (Erik's build uses SPI RFID and has no
  keypad, which conflicts with Glenn's I2C wiring), but adopted his PIN-hashing and
  offline-operation ideas.

**Tasks for This Week**
- (Week 3) MW: Add SHA-256 PIN hashing to the database and `/api/verify`.
- (Week 3) MW: Add an offline authorization cache to the Pico so the mill stays usable
  if Wi-Fi or the admin PC goes down.

**Blockers**
- (Week 3) MW: Need Glenn to confirm a free GPIO for the relay — his firmware has no
  relay output yet (I assumed GP16; Erik's example used GP15).
