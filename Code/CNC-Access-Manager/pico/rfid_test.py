# rfid_test.py  —  CircuitPython test: confirm the RFID reader works
# ---------------------------------------------------------------------
# Put this on the Pico 2 W as code.py (or run it from the REPL) together
# with mfrc522_i2c.py. It just reads cards and prints their UID in the
# exact hex format the database uses (e.g. A388DB1C). Tap each real card,
# copy the printed UID, and register it in the web app (Add user -> Card).
#
# Wiring (Glenn's build): RC522 over I2C  SDA=GP2  SCL=GP3  addr 0x28
# ---------------------------------------------------------------------
import time, board, busio
from mfrc522_i2c import MFRC522_I2C

RC522_ADDRESS = 0x28
i2c = busio.I2C(board.GP3, board.GP2, frequency=50000)   # (SCL, SDA)

while not i2c.try_lock():
    pass
try:
    print("I2C devices:", ["0x%02X" % a for a in i2c.scan()])
finally:
    i2c.unlock()

reader = MFRC522_I2C(i2c, address=RC522_ADDRESS, debug=False)
print("MFRC522 VersionReg: 0x%02X" % reader.version())
print("Reader ready. Tap a card...\n")

last = None
while True:
    try:
        uid = reader.read_uid()
    except Exception as e:
        print("read error:", repr(e)); time.sleep(0.3); continue
    if uid is None:
        last = None
        time.sleep(0.05); continue
    uid_hex = "".join("%02X" % b for b in uid)     # e.g. A388DB1C
    if uid_hex != last:                            # print once per tap
        last = uid_hex
        print("CARD UID:", uid_hex, "  (register this in the web app)")
    time.sleep(0.1)
