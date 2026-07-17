# enroll.py  —  CircuitPython enrollment mode for the admin "Scan" button
# ---------------------------------------------------------------------
# Run this on the Pico when you are ADDING users in the web app. Each time
# you tap a card, its UID is POSTed to the server's /api/scan. In the web
# app, open Add user and press "Scan" — it pulls the card you just tapped.
#
# Needs on CIRCUITPY:  mfrc522_i2c.py, settings.toml,
#   /lib/adafruit_requests.mpy, /lib/adafruit_connection_manager.mpy
# (Rename this to code.py to auto-run, or run it from the REPL.)
# ---------------------------------------------------------------------
import os, time, board, busio
import wifi, socketpool, ssl
import adafruit_requests
from mfrc522_i2c import MFRC522_I2C

SERVER_URL = (os.getenv("SERVER_URL") or "").rstrip("/")
DEVICE_KEY = os.getenv("DEVICE_KEY") or "pico-770"

wifi.radio.connect(os.getenv("WIFI_SSID"), os.getenv("WIFI_PASSWORD"))
print("Wi-Fi OK:", wifi.radio.ipv4_address)
pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

i2c = busio.I2C(board.GP3, board.GP2, frequency=50000)   # SCL=GP3, SDA=GP2
reader = MFRC522_I2C(i2c, address=0x28, debug=False)
print("Reader v0x%02X. ENROLL MODE: tap a card to send it to the web app.\n"
      % reader.version())

last = None
while True:
    try:
        uid = reader.read_uid()
    except Exception as e:
        print("read error:", repr(e)); time.sleep(0.3); continue
    if uid is None:
        last = None; time.sleep(0.05); continue
    uid_hex = "".join("%02X" % b for b in uid)
    if uid_hex == last:
        time.sleep(0.1); continue
    last = uid_hex
    try:
        r = requests.post(SERVER_URL + "/api/scan",
                          json={"uid": uid_hex},
                          headers={"X-Device-Key": DEVICE_KEY}, timeout=6)
        r.close()
        print("sent UID to server:", uid_hex, " -> press Scan in the web app")
    except Exception as e:
        print("send failed:", repr(e))
    time.sleep(0.4)
