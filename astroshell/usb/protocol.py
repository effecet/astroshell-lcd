"""
Astroshell LCD serial protocol — cracked from Jungle Leopard Display Setup 1.0.42.

Packet format:
    55 AA [len_lo len_hi] [cmd] [payload...] [checksum_lo checksum_hi]

Image streaming:
    1. Send FF D9 FF D9 (stop current display)
    2. Wait 200ms
    3. Send getDeviceInfo (cmd 6)
    4. Send startLive (cmd 17)
    5. Write raw JPEG bytes to serial (no framing)
    6. Re-send cmd 17 every 1.5s as keepalive
"""

import io
import json
import time
import serial
from PIL import Image
from astroshell.logger import log

# ── Constants ─────────────────────────────────────────────────────────────────

WIDTH = 320
HEIGHT = 240

CMD_RESTART = 1
CMD_SET_BRIGHTNESS = 3
CMD_GET_INFO = 6
CMD_START_LIVE = 17
CMD_CLOSE = 33

STOP_MARKER = b"\xff\xd9\xff\xd9"
CHUNK_SIZE = 512


# ── Packet framing ────────────────────────────────────────────────────────────


def build_command(cmd: int, payload: bytes = b"") -> bytes:
    magic = bytes([0x55, 0xAA])
    length = len(payload) + 7
    packet = magic + bytes([length & 0xFF, (length >> 8) & 0xFF, cmd]) + payload
    checksum = sum(packet) & 0xFFFF
    return packet + bytes([checksum & 0xFF, (checksum >> 8) & 0xFF])


def parse_response(data: bytes) -> dict | None:
    if len(data) < 7 or data[0:2] != b"\x55\xaa":
        return None
    try:
        payload = data[5:-2]
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return None


# ── Serial helpers ────────────────────────────────────────────────────────────


def _write_chunked(ser: serial.Serial, data: bytes) -> None:
    for i in range(0, len(data), CHUNK_SIZE):
        ser.write(data[i : i + CHUNK_SIZE])
    ser.flush()


def _read_response(ser: serial.Serial, timeout: float = 1.0) -> bytes:
    ser.timeout = timeout
    header = ser.read(5)
    if len(header) < 5:
        return b""
    length = header[2] | (header[3] << 8)
    remaining = length - 5  # length includes header
    if remaining > 0:
        body = ser.read(remaining)
        return header + body
    return header


# ── JPEG encoding ─────────────────────────────────────────────────────────────


def encode_jpeg(image: Image.Image, quality: int = 85) -> bytes:
    img = image.convert("RGB").resize((WIDTH, HEIGHT), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


# ── Public API ────────────────────────────────────────────────────────────────


def stop_display(ser: serial.Serial) -> None:
    ser.write(STOP_MARKER)
    ser.flush()
    log.debug("Sent stop marker (FF D9 FF D9)")


def get_device_info(ser: serial.Serial) -> dict | None:
    cmd = build_command(CMD_GET_INFO)
    _write_chunked(ser, cmd)
    raw = _read_response(ser)
    info = parse_response(raw)
    if info:
        log.info(f"Device info: {info}")
    else:
        log.warning("No response to getDeviceInfo")
    return info


def start_live(ser: serial.Serial) -> None:
    cmd = build_command(CMD_START_LIVE)
    _write_chunked(ser, cmd)
    log.debug("Sent startLive (cmd 17)")


def set_brightness(ser: serial.Serial, level: int) -> None:
    level = max(0, min(100, level))
    cmd = build_command(CMD_SET_BRIGHTNESS, bytes([level]))
    _write_chunked(ser, cmd)
    log.debug(f"Set brightness to {level}")


def restart_device(ser: serial.Serial) -> None:
    cmd = build_command(CMD_RESTART)
    _write_chunked(ser, cmd)
    log.info("Sent restart command")


def close_display(ser: serial.Serial) -> None:
    cmd = build_command(CMD_CLOSE)
    _write_chunked(ser, cmd)
    log.debug("Sent close (cmd 33)")


def init_display(ser: serial.Serial) -> dict | None:
    stop_display(ser)
    time.sleep(0.2)
    info = get_device_info(ser)
    start_live(ser)
    return info


def push_frame(ser: serial.Serial, image: Image.Image) -> None:
    payload = encode_jpeg(image)
    ser.write(payload)
    ser.flush()
    log.debug(f"Pushed frame: {len(payload)} bytes JPEG")
