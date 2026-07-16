import time
import board
import busio
import digitalio
import pwmio

from mfrc522_i2c import MFRC522_I2C


# ============================================================
# Access credentials
# ============================================================

AUTHORIZED_UID = "A388DB1C"
AUTHORIZED_PIN = "7789"

RC522_ADDRESS = 0x28


# ============================================================
# Pin assignments
# ============================================================

RFID_SDA_PIN = board.GP2
RFID_SCL_PIN = board.GP3

KEYPAD_C2_PIN = board.GP4
KEYPAD_R1_PIN = board.GP5
KEYPAD_C1_PIN = board.GP6
KEYPAD_R4_PIN = board.GP7
KEYPAD_C3_PIN = board.GP8
KEYPAD_R3_PIN = board.GP9
KEYPAD_R2_PIN = board.GP10

RED_LED_PIN = board.GP20
GREEN_LED_PIN = board.GP21
BUZZER_PIN = board.GP22


# ============================================================
# Timing settings
# ============================================================

CARD_REMOVAL_DELAY = 0.75
PIN_ENTRY_TIMEOUT = 15.0
KEY_DEBOUNCE_TIME = 0.18


# ============================================================
# LED setup
# ============================================================

red_led = digitalio.DigitalInOut(RED_LED_PIN)
red_led.direction = digitalio.Direction.OUTPUT

green_led = digitalio.DigitalInOut(GREEN_LED_PIN)
green_led.direction = digitalio.Direction.OUTPUT

red_led.value = True
green_led.value = False


# ============================================================
# Passive buzzer setup
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
    """Positive confirmation tone."""

    tone(2200, 0.08, 0.04)
    tone(2850, 0.12)


def bad_beep():
    """Low double error tone."""

    tone(550, 0.16, 0.10)
    tone(550, 0.16)


# ============================================================
# Visual feedback
# ============================================================

def waiting_state():
    red_led.value = True
    green_led.value = False


def correct_card_feedback():
    red_led.value = False
    green_led.value = True

    good_beep()

    time.sleep(0.20)

    green_led.value = False
    red_led.value = True


def access_granted_feedback():
    red_led.value = False
    green_led.value = True

    good_beep()

    # Keep green on long enough to clearly show success.
    time.sleep(1.0)

    green_led.value = False
    red_led.value = True


def access_denied_feedback():
    green_led.value = False
    red_led.value = True

    bad_beep()

    # Hold red briefly to make the denial obvious.
    time.sleep(0.70)


# ============================================================
# Keypad setup
# ============================================================

# Physical keypad layout:
#
# 1 2 3
# 4 5 6
# 7 8 9
# * 0 #
#
# User-provided wiring:
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

    Returns:
        A key string such as "7", "*", or "#",
        or None if no key is pressed.
    """

    for row_index, row in enumerate(rows):

        # Pull one row low at a time.
        row.value = False

        # Allow the signal to settle.
        time.sleep(0.001)

        for column_index, column in enumerate(columns):
            if not column.value:
                key = key_map[row_index][column_index]

                # Restore row before returning.
                row.value = True

                return key

        row.value = True

    return None


def wait_for_key_release():
    """Wait until the currently pressed key is released."""

    while scan_keypad() is not None:
        time.sleep(0.01)


def get_key():
    """
    Return one debounced key press or None.
    """

    key = scan_keypad()

    if key is None:
        return None

    key_beep()

    wait_for_key_release()
    time.sleep(KEY_DEBOUNCE_TIME)

    return key


# ============================================================
# I2C and RC522 setup
# ============================================================

print()
print("========================================")
print("Pico 2 W RFID + Keypad Access Test")
print("========================================")
print("Authorized UID: {}".format(AUTHORIZED_UID))
print("PIN length: {} digits".format(len(AUTHORIZED_PIN)))
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

waiting_state()


# ============================================================
# PIN entry
# ============================================================

def read_pin():
    """
    Read a PIN from the keypad.

    Rules:
    - Digits are appended.
    - * clears the entered PIN.
    - # submits the current PIN.
    - Entry submits automatically after four digits.
    - Entry times out after PIN_ENTRY_TIMEOUT seconds.
    """

    entered_pin = ""
    start_time = time.monotonic()

    print("Enter PIN:")
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

            # Do not print the actual PIN digits.
            print(
                "PIN: {}".format(
                    "*" * len(entered_pin)
                )
            )

            if len(entered_pin) >= len(AUTHORIZED_PIN):
                return entered_pin


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
        time.sleep(0.25)
        continue

    except Exception as error:
        print("RFID error:")
        print(repr(error))
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


    # Ignore the same card while it remains against the reader.
    if uid_compact == last_uid:
        time.sleep(0.05)
        continue


    last_uid = uid_compact

    print()
    print("========================================")
    print("CARD DETECTED")
    print("UID HEX: {}".format(uid_colon))
    print("========================================")


    # --------------------------------------------------------
    # Wrong card
    # --------------------------------------------------------

    if uid_compact != AUTHORIZED_UID:
        print("ACCESS DENIED: Unauthorized card.")
        access_denied_feedback()
        print("Present an RFID card.")
        print()
        continue


    # --------------------------------------------------------
    # Correct card
    # --------------------------------------------------------

    print("Authorized card accepted.")
    correct_card_feedback()

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
        print("ACCESS DENIED: Incorrect PIN.")
        print()

        access_denied_feedback()


    print("Present an RFID card.")
    print()

    # Require the card to be removed before allowing another
    # complete access attempt with the same card.
    while reader.read_uid() is not None:
        time.sleep(0.10)

    last_uid = None
    waiting_state()