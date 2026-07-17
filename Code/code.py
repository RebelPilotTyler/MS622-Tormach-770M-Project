import time
import board
import busio
import digitalio
import pwmio

from mfrc522_i2c import MFRC522_I2C


# ============================================================
# Authorized credentials
# ============================================================

AUTHORIZED_UID = "A388DB1C"
AUTHORIZED_PIN = "7789"

RC522_ADDRESS = 0x28


# ============================================================
# Pin assignments
# ============================================================

# RC522
RFID_SDA_PIN = board.GP2
RFID_SCL_PIN = board.GP3

# Keypad
KEYPAD_C2_PIN = board.GP4
KEYPAD_R1_PIN = board.GP5
KEYPAD_C1_PIN = board.GP6
KEYPAD_R4_PIN = board.GP7
KEYPAD_C3_PIN = board.GP8
KEYPAD_R3_PIN = board.GP9
KEYPAD_R2_PIN = board.GP10

# Indicators
YELLOW_LED_PIN = board.GP19
RED_LED_PIN = board.GP20
GREEN_LED_PIN = board.GP21
BUZZER_PIN = board.GP22


# ============================================================
# Timing
# ============================================================

CARD_REMOVAL_DELAY = 0.75
PIN_ENTRY_TIMEOUT = 15.0
KEY_DEBOUNCE_TIME = 0.15


# ============================================================
# LED setup
# ============================================================

yellow_led = digitalio.DigitalInOut(YELLOW_LED_PIN)
yellow_led.direction = digitalio.Direction.OUTPUT

red_led = digitalio.DigitalInOut(RED_LED_PIN)
red_led.direction = digitalio.Direction.OUTPUT

green_led = digitalio.DigitalInOut(GREEN_LED_PIN)
green_led.direction = digitalio.Direction.OUTPUT


# ============================================================
# Passive buzzer
# ============================================================

buzzer = pwmio.PWMOut(
    BUZZER_PIN,
    duty_cycle=0,
    frequency=2000,
    variable_frequency=True
)


def tone(frequency, duration, pause=0.0):
    """Play one tone on the passive buzzer."""

    buzzer.frequency = frequency
    buzzer.duty_cycle = 32768

    time.sleep(duration)

    buzzer.duty_cycle = 0

    if pause > 0:
        time.sleep(pause)


def key_beep():
    """Short tone for every keypad press."""

    tone(1700, 0.045)


def good_beep():
    """Rising success tone."""

    tone(2200, 0.08, 0.04)
    tone(2850, 0.12)


def bad_beep():
    """Low double-beep denial tone."""

    tone(550, 0.16, 0.10)
    tone(550, 0.16)


# ============================================================
# LED states
# ============================================================

def all_leds_off():
    yellow_led.value = False
    red_led.value = False
    green_led.value = False


def waiting_for_card_state():
    """Yellow indicates that the system is idle and ready."""

    yellow_led.value = True
    red_led.value = False
    green_led.value = False


def waiting_for_pin_state():
    """Yellow indicates that the system is waiting for PIN entry."""

    yellow_led.value = True
    red_led.value = False
    green_led.value = False


def correct_card_feedback():
    """Correct card: yellow off, green on, positive tone."""

    yellow_led.value = False
    red_led.value = False
    green_led.value = True

    good_beep()
    time.sleep(0.30)

    green_led.value = False


def access_granted_feedback():
    """Correct card and PIN: yellow off, green success."""

    yellow_led.value = False
    red_led.value = False
    green_led.value = True

    good_beep()

    time.sleep(1.0)

    green_led.value = False


def access_denied_feedback():
    """Wrong card or PIN: yellow off, red denial."""

    yellow_led.value = False
    green_led.value = False
    red_led.value = True

    bad_beep()

    time.sleep(0.80)

    red_led.value = False


# ============================================================
# Keypad setup
# ============================================================

# Physical layout:
#
# 1 2 3
# 4 5 6
# 7 8 9
# * 0 #
#
# Wiring:
#
# C2 = GP4
# R1 = GP5
# C1 = GP6
# R4 = GP7
# C3 = GP8
# R3 = GP9
# R2 = GP10

row_pins = [
    KEYPAD_R1_PIN,
    KEYPAD_R2_PIN,
    KEYPAD_R3_PIN,
    KEYPAD_R4_PIN
]

column_pins = [
    KEYPAD_C1_PIN,
    KEYPAD_C2_PIN,
    KEYPAD_C3_PIN
]

key_map = [
    ["1", "2", "3"],
    ["4", "5", "6"],
    ["7", "8", "9"],
    ["*", "0", "#"]
]


rows = []

for pin in row_pins:
    row = digitalio.DigitalInOut(pin)
    row.direction = digitalio.Direction.OUTPUT
    row.value = True
    rows.append(row)


columns = []

for pin in column_pins:
    column = digitalio.DigitalInOut(pin)
    column.direction = digitalio.Direction.INPUT
    column.pull = digitalio.Pull.UP
    columns.append(column)


def scan_keypad():
    """
    Scan the keypad once.

    Returns a key string or None.
    """

    for row_index, row in enumerate(rows):
        row.value = False
        time.sleep(0.001)

        for column_index, column in enumerate(columns):
            if not column.value:
                key = key_map[row_index][column_index]

                row.value = True
                return key

        row.value = True

    return None


def wait_for_key_release():
    """Wait until the current key is released."""

    while scan_keypad() is not None:
        time.sleep(0.01)


def get_key():
    """Return one debounced key press."""

    key = scan_keypad()

    if key is None:
        return None

    key_beep()

    wait_for_key_release()
    time.sleep(KEY_DEBOUNCE_TIME)

    return key


# ============================================================
# PIN entry
# ============================================================

def read_pin():
    """
    Read a PIN.

    * clears the current entry.
    # submits early.
    Four digits submit automatically.
    """

    entered_pin = ""
    start_time = time.monotonic()

    waiting_for_pin_state()

    print()
    print("Enter PIN")
    print("* = clear")
    print("# = submit")

    while True:
        if time.monotonic() - start_time >= PIN_ENTRY_TIMEOUT:
            print("PIN entry timed out.")
            return None

        key = get_key()

        if key is None:
            time.sleep(0.01)
            continue

        if key == "*":
            entered_pin = ""
            print("PIN cleared.")
            continue

        if key == "#":
            print("PIN submitted.")
            return entered_pin

        if key.isdigit():
            entered_pin += key

            print(
                "PIN: {}".format(
                    "*" * len(entered_pin)
                )
            )

            if len(entered_pin) >= len(AUTHORIZED_PIN):
                return entered_pin


# ============================================================
# I2C and RC522 setup
# ============================================================

print()
print("========================================")
print("Pico 2 W RFID + Keypad Access Control")
print("========================================")
print("Authorized UID: {}".format(AUTHORIZED_UID))
print("Authorized PIN length: {}".format(len(AUTHORIZED_PIN)))
print("Yellow LED: GP19")
print("Red LED: GP20")
print("Green LED: GP21")
print("Buzzer: GP22")
print()


i2c = busio.I2C(
    RFID_SCL_PIN,
    RFID_SDA_PIN,
    frequency=50000
)


while not i2c.try_lock():
    pass

try:
    detected_devices = i2c.scan()
finally:
    i2c.unlock()


print(
    "I2C devices:",
    [
        "0x{:02X}".format(address)
        for address in detected_devices
    ]
)


if RC522_ADDRESS not in detected_devices:
    print("ERROR: RC522 not detected at 0x28.")

    while True:
        access_denied_feedback()
        time.sleep(0.50)


try:
    reader = MFRC522_I2C(
        i2c,
        address=RC522_ADDRESS,
        debug=False
    )

    version = reader.version()

except Exception as error:
    print("RC522 initialization failed:")
    print(repr(error))

    while True:
        access_denied_feedback()
        time.sleep(0.50)


print(
    "MFRC522 VersionReg: 0x{:02X}".format(
        version
    )
)

print()
print("System ready.")
print("Present an RFID card.")
print()

waiting_for_card_state()


# ============================================================
# Main access-control loop
# ============================================================

last_uid = None
last_card_seen = 0.0


while True:
    try:
        uid = reader.read_uid()

    except OSError as error:
        print("RFID I2C error:")
        print(repr(error))

        waiting_for_card_state()
        time.sleep(0.25)
        continue

    except Exception as error:
        print("RFID error:")
        print(repr(error))

        waiting_for_card_state()
        time.sleep(0.25)
        continue


    if uid is None:
        if (
            time.monotonic() - last_card_seen
            > CARD_REMOVAL_DELAY
        ):
            last_uid = None

        time.sleep(0.05)
        continue


    last_card_seen = time.monotonic()

    uid_compact = "".join(
        "{:02X}".format(value)
        for value in uid
    )

    uid_colon = ":".join(
        "{:02X}".format(value)
        for value in uid
    )


    # Ignore repeated reads while the same card remains present.
    if uid_compact == last_uid:
        time.sleep(0.05)
        continue


    last_uid = uid_compact

    # A card is now being processed, so yellow turns off.
    all_leds_off()

    print()
    print("========================================")
    print("CARD DETECTED")
    print("UID HEX: {}".format(uid_colon))
    print("========================================")


    # --------------------------------------------------------
    # Unauthorized card
    # --------------------------------------------------------

    if uid_compact != AUTHORIZED_UID:
        print("ACCESS DENIED: Unauthorized card.")

        access_denied_feedback()

        print("Present an RFID card.")
        print()

        waiting_for_card_state()
        continue


    # --------------------------------------------------------
    # Authorized card
    # --------------------------------------------------------

    print("Authorized card accepted.")

    correct_card_feedback()

    # Yellow returns while waiting for the PIN.
    waiting_for_pin_state()

    entered_pin = read_pin()


    # --------------------------------------------------------
    # Correct PIN
    # --------------------------------------------------------

    if entered_pin == AUTHORIZED_PIN:
        print()
        print("ACCESS GRANTED")
        print("Card and PIN are both correct.")
        print()

        access_granted_feedback()


    # --------------------------------------------------------
    # Wrong PIN or timeout
    # --------------------------------------------------------

    else:
        print()
        print("ACCESS DENIED: Incorrect PIN or timeout.")
        print()

        access_denied_feedback()


    print("Remove card.")
    print()

    # Require card removal before another attempt.
    while True:
        try:
            card_still_present = reader.read_uid()

        except OSError:
            card_still_present = None

        if card_still_present is None:
            break

        time.sleep(0.10)


    last_uid = None

    print("Present an RFID card.")
    print()

    waiting_for_card_state()