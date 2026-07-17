import time


class MFRC522_I2C:
    """Minimal CircuitPython I2C driver for an MFRC522 reader."""

    OK = 0
    NOTAGERR = 1
    ERR = 2

    # PICC commands
    PICC_REQIDL = 0x26
    PICC_REQALL = 0x52
    PICC_ANTICOLL_CL1 = 0x93

    # PCD commands
    PCD_IDLE = 0x00
    PCD_CALC_CRC = 0x03
    PCD_TRANSCEIVE = 0x0C
    PCD_SOFT_RESET = 0x0F

    # Registers
    COMMAND_REG = 0x01
    COM_IEN_REG = 0x02
    COM_IRQ_REG = 0x04
    ERROR_REG = 0x06
    FIFO_DATA_REG = 0x09
    FIFO_LEVEL_REG = 0x0A
    CONTROL_REG = 0x0C
    BIT_FRAMING_REG = 0x0D
    COLL_REG = 0x0E

    MODE_REG = 0x11
    TX_CONTROL_REG = 0x14
    TX_ASK_REG = 0x15

    RFCFG_REG = 0x26
    TMODE_REG = 0x2A
    TPRESCALER_REG = 0x2B
    TRELOAD_REG_H = 0x2C
    TRELOAD_REG_L = 0x2D

    VERSION_REG = 0x37

    def __init__(self, i2c, address=0x28, debug=False):
        self.i2c = i2c
        self.address = address
        self.debug = debug

        self._register = bytearray(1)
        self._write = bytearray(2)
        self._read = bytearray(1)

        self.initialize()

    def _lock(self, timeout=1.0):
        deadline = time.monotonic() + timeout
        while not self.i2c.try_lock():
            if time.monotonic() >= deadline:
                raise RuntimeError("Timed out waiting for I2C bus")
            time.sleep(0.001)

    def _write_register(self, register, value):
        self._write[0] = register & 0x3F
        self._write[1] = value & 0xFF

        self._lock()
        try:
            self.i2c.writeto(self.address, self._write)
        finally:
            self.i2c.unlock()

        if self.debug:
            print("W 0x{:02X} <- 0x{:02X}".format(register, value))

    def _read_register(self, register):
        self._register[0] = register & 0x3F

        self._lock()
        try:
            # MFRC522 I2C register read:
            # write the register address, STOP, then perform a separate read.
            self.i2c.writeto(self.address, self._register)
            self.i2c.readfrom_into(self.address, self._read)
        finally:
            self.i2c.unlock()

        value = self._read[0]

        if self.debug:
            print("R 0x{:02X} -> 0x{:02X}".format(register, value))

        return value

    def _set_bits(self, register, mask):
        self._write_register(
            register,
            self._read_register(register) | mask
        )

    def _clear_bits(self, register, mask):
        self._write_register(
            register,
            self._read_register(register) & (~mask & 0xFF)
        )

    def reset(self):
        self._write_register(self.COMMAND_REG, self.PCD_SOFT_RESET)
        time.sleep(0.08)

    def initialize(self):
        self.reset()

        self._write_register(self.TMODE_REG, 0x8D)
        self._write_register(self.TPRESCALER_REG, 0x3E)
        self._write_register(self.TRELOAD_REG_L, 30)
        self._write_register(self.TRELOAD_REG_H, 0)
        self._write_register(self.TX_ASK_REG, 0x40)
        self._write_register(self.MODE_REG, 0x3D)

        gain = self._read_register(self.RFCFG_REG)
        self._write_register(self.RFCFG_REG, (gain & 0x8F) | 0x70)

        self.antenna_on()

    def antenna_on(self):
        value = self._read_register(self.TX_CONTROL_REG)
        if (value & 0x03) != 0x03:
            self._set_bits(self.TX_CONTROL_REG, 0x03)

    def version(self):
        return self._read_register(self.VERSION_REG)

    def _communicate(self, command, send_data):
        received = []
        received_bits = 0

        if command == self.PCD_TRANSCEIVE:
            irq_enable = 0x77
            wait_irq = 0x30
        else:
            irq_enable = 0x00
            wait_irq = 0x00

        self._write_register(self.COM_IEN_REG, irq_enable | 0x80)
        self._clear_bits(self.COM_IRQ_REG, 0x80)
        self._set_bits(self.FIFO_LEVEL_REG, 0x80)
        self._write_register(self.COMMAND_REG, self.PCD_IDLE)

        for value in send_data:
            self._write_register(self.FIFO_DATA_REG, value)

        self._write_register(self.COMMAND_REG, command)

        if command == self.PCD_TRANSCEIVE:
            self._set_bits(self.BIT_FRAMING_REG, 0x80)

        deadline = time.monotonic() + 0.08
        irq_value = 0

        while time.monotonic() < deadline:
            irq_value = self._read_register(self.COM_IRQ_REG)

            if irq_value & 0x01:
                break

            if irq_value & wait_irq:
                break

        self._clear_bits(self.BIT_FRAMING_REG, 0x80)

        if time.monotonic() >= deadline:
            return self.ERR, received, received_bits

        error_value = self._read_register(self.ERROR_REG)
        if error_value & 0x1B:
            return self.ERR, received, received_bits

        status = self.NOTAGERR if (irq_value & 0x01) else self.OK

        if command == self.PCD_TRANSCEIVE:
            fifo_length = self._read_register(self.FIFO_LEVEL_REG)
            last_bits = self._read_register(self.CONTROL_REG) & 0x07

            if last_bits:
                received_bits = ((fifo_length - 1) * 8) + last_bits
            else:
                received_bits = fifo_length * 8

            if fifo_length > 64:
                fifo_length = 64

            for _ in range(fifo_length):
                received.append(self._read_register(self.FIFO_DATA_REG))

        return status, received, received_bits

    def request(self, request_mode=PICC_REQIDL):
        self._write_register(self.BIT_FRAMING_REG, 0x07)

        status, received, bits = self._communicate(
            self.PCD_TRANSCEIVE,
            [request_mode]
        )

        if status != self.OK or bits != 16 or len(received) < 2:
            return self.ERR, None

        return self.OK, received[:2]

    def anticollision(self):
        self._write_register(self.BIT_FRAMING_REG, 0x00)
        self._write_register(self.COLL_REG, 0x80)

        status, received, _ = self._communicate(
            self.PCD_TRANSCEIVE,
            [self.PICC_ANTICOLL_CL1, 0x20]
        )

        if status != self.OK or len(received) != 5:
            return self.ERR, None

        bcc = received[0] ^ received[1] ^ received[2] ^ received[3]
        if bcc != received[4]:
            return self.ERR, None

        return self.OK, received

    def read_uid(self):
        status, _ = self.request(self.PICC_REQIDL)
        if status != self.OK:
            return None

        status, uid_data = self.anticollision()
        if status != self.OK:
            return None

        return bytes(uid_data[:4])