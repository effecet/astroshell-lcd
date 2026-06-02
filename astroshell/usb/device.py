"""
Serial device management for the Astroshell LCD (33c3:7792 HONGTAI MONITOR).

Transport: CDC ACM serial over USB → /dev/ttyACM0
Access:    user must be in 'dialout' group
           sudo usermod -aG dialout $USER
"""

import serial
import serial.tools.list_ports
from astroshell.logger import log

VENDOR_ID = 0x33C3
PRODUCT_ID = 0x7792
DEFAULT_PORT = "/dev/ttyACM0"
DEFAULT_BAUD = 115200


def find_port() -> str | None:
    """Auto-detect the Astroshell serial port by VID:PID."""
    for port in serial.tools.list_ports.comports():
        if port.vid == VENDOR_ID and port.pid == PRODUCT_ID:
            log.info(f"Auto-detected Astroshell at {port.device}")
            return port.device
    return None


def open_device(port: str | None = None, baud: int = DEFAULT_BAUD) -> serial.Serial:
    """Open the Astroshell serial port. Falls back to DEFAULT_PORT if not found."""
    target = port or find_port() or DEFAULT_PORT
    log.info(f"Opening serial port {target} @ {baud} baud")
    ser = serial.Serial(
        port=target,
        baudrate=baud,
        timeout=1,
        write_timeout=5,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
    )
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return ser


def close_device(ser: serial.Serial) -> None:
    if ser and ser.is_open:
        ser.close()
        log.info("Serial port closed")
