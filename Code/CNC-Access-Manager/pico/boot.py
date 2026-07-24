# boot.py  —  runs once at power-up, before code.py
# =============================================================================
# The offline cache (roster.json) and the buffered access queue
# (offline_queue.json) are written by CircuitPython itself, but the CIRCUITPY
# drive is read-only to the board by default. This remounts it writable.
#
# TRADE-OFF: while this file is in place, your PC can still SEE the drive but
# cannot save files to it. To edit code.py from the computer again, hold the
# BOOTSEL/GP0 button (or ground GP18) while plugging the Pico in — that skips
# the remount and hands the drive back to the PC.
# =============================================================================

import board, digitalio, storage

# Hold this pin low at power-up to keep the drive writable from the PC instead.
override = digitalio.DigitalInOut(board.GP18)
override.direction = digitalio.Direction.INPUT
override.pull = digitalio.Pull.UP

if override.value:                      # not grounded -> normal running mode
    storage.remount("/", readonly=False)
    print("boot.py: CIRCUITPY mounted writable for the offline cache.")
else:
    print("boot.py: override pin grounded — drive left writable for the PC.")

override.deinit()
