#!/usr/bin/env python3
"""
Image transfer probe — we know the framing (55 AA + 5+ bytes),
now find the right sequence to push pixels to the screen.

Hypothesis: device uses 55 AA wrapping around Turing Rev A commands.
Tests the full init → orient → brightness → bitmap → data sequence.

sudo .venv/bin/python tools/probe_image.py
"""

import io
import struct
import sys
import time

import serial
from PIL import Image, ImageDraw
from rich.console import Console

console = Console()
PORT = "/dev/ttyACM0"
BAUD = 115200
MAGIC = b"\x55\xaa"
W, H = 320, 320

# Rev A commands
CMD_RESET = 101
CMD_CLEAR = 102
CMD_TO_BLACK = 103
CMD_SCREEN_OFF = 108
CMD_SCREEN_ON = 109
CMD_BRIGHTNESS = 110
CMD_ORIENT = 121
CMD_BITMAP = 197
CMD_PIXELS = 195
CMD_HELLO = 69
CMD_MIRROR = 122


def pack6(x: int, y: int, ex: int, ey: int, cmd: int) -> bytes:
    """Rev A 6-byte packed command."""
    return bytes(
        [
            (x >> 2),
            (((x & 3) << 6) + (y >> 4)),
            (((y & 15) << 4) + (ex >> 6)),
            (((ex & 63) << 2) + (ey >> 8)),
            (ey & 255),
            cmd,
        ]
    )


def pack_orient(orient: int) -> bytes:
    """Rev A SET_ORIENTATION with dimensions (16 bytes)."""
    base = pack6(0, 0, 0, 0, CMD_ORIENT)
    return base + bytes([orient + 100]) + struct.pack(">HH", W, H) + bytes([0] * 5)


def send(ser: serial.Serial, data: bytes, label: str, wait: float = 0.3) -> bytes | None:
    ser.reset_input_buffer()
    ser.write(data)
    ser.flush()
    time.sleep(wait)
    resp = ser.read(256)
    if resp:
        console.print(f"  [green]{label}: {resp.hex()}[/]")
    else:
        console.print(f"  [dim]{label}: no response[/]")
    return resp if resp else None


def send_no_read(ser: serial.Serial, data: bytes):
    """Write without waiting for response."""
    ser.write(data)
    ser.flush()


def make_image() -> Image.Image:
    """Solid orange test pattern — easy to spot on screen."""
    img = Image.new("RGB", (W, H), (249, 115, 22))
    draw = ImageDraw.Draw(img)
    # White crosshair so we can tell orientation
    draw.line([(0, 160), (319, 160)], fill=(255, 255, 255), width=2)
    draw.line([(160, 0), (160, 319)], fill=(255, 255, 255), width=2)
    # Cyan corner marker top-left
    draw.rectangle([0, 0, 30, 30], fill=(34, 211, 238))
    return img


def to_rgb565_le(img: Image.Image) -> bytes:
    raw = img.convert("RGB").tobytes()
    out = bytearray()
    for i in range(0, len(raw), 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        out += struct.pack("<H", ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
    return bytes(out)


def to_rgb565_be(img: Image.Image) -> bytes:
    raw = img.convert("RGB").tobytes()
    out = bytearray()
    for i in range(0, len(raw), 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        out += struct.pack(">H", ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
    return bytes(out)


def to_jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def to_bgra(img: Image.Image) -> bytes:
    """BGRA format used by Rev C with newer firmware."""
    raw = img.convert("RGB").tobytes()
    out = bytearray()
    for i in range(0, len(raw), 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        out += bytes([b, g, r, 255])
    return bytes(out)


def to_bgr(img: Image.Image) -> bytes:
    """BGR format used by Rev C with older firmware."""
    raw = img.convert("RGB").tobytes()
    out = bytearray()
    for i in range(0, len(raw), 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        out += bytes([b, g, r])
    return bytes(out)


# ── Test sequences ─────────────────────────────────────────────────────────


def test_full_reva_with_magic(ser, img_data, fmt_name):
    """Full Rev A sequence: HELLO → ORIENT → BRIGHTNESS → BITMAP + data, all with 55AA."""
    console.print(f"\n  [cyan]Full Rev A + MAGIC sequence ({fmt_name})[/]")

    # HELLO
    send(ser, MAGIC + bytes([CMD_HELLO] * 6), "HELLO")

    # ORIENTATION (portrait)
    send(ser, MAGIC + pack_orient(0), "ORIENT 0")

    # BRIGHTNESS 100%
    send(ser, MAGIC + pack6(0, 0, 0, 100, CMD_BRIGHTNESS), "BRIGHT 100")

    # SCREEN_ON
    send(ser, MAGIC + pack6(0, 0, 0, 0, CMD_SCREEN_ON), "SCREEN_ON")

    # BITMAP command
    bitmap_cmd = MAGIC + pack6(0, 0, W - 1, H - 1, CMD_BITMAP)
    send(ser, bitmap_cmd, "BITMAP cmd")

    # Stream image data in chunks of W*8*2 (Rev A: 8 rows at a time)
    chunk_size = W * 8 * 2  # 5120 bytes per chunk
    console.print(f"  Streaming {len(img_data)} bytes in {chunk_size}B chunks...")
    for i in range(0, len(img_data), chunk_size):
        ser.write(img_data[i : i + chunk_size])
        time.sleep(0.005)
    ser.flush()
    time.sleep(0.5)
    resp = ser.read(256)
    if resp:
        console.print(f"  [green]Post-data: {resp.hex()}[/]")
    else:
        console.print("  [dim]Post-data: no response[/]")


def test_magic_per_chunk(ser, img_data, fmt_name):
    """Maybe each data chunk needs 55 AA prefix."""
    console.print(f"\n  [cyan]55 AA per chunk ({fmt_name})[/]")

    send(ser, MAGIC + bytes([CMD_HELLO] * 6), "HELLO")
    send(ser, MAGIC + pack_orient(0), "ORIENT")
    send(ser, MAGIC + pack6(0, 0, 0, 100, CMD_BRIGHTNESS), "BRIGHT")

    bitmap_cmd = MAGIC + pack6(0, 0, W - 1, H - 1, CMD_BITMAP)
    send(ser, bitmap_cmd, "BITMAP cmd")

    # Send each chunk with MAGIC prefix
    chunk_size = 512
    console.print(f"  Streaming with MAGIC per {chunk_size}B chunk...")
    for i in range(0, len(img_data), chunk_size):
        chunk = img_data[i : i + chunk_size]
        ser.write(MAGIC + chunk)
        time.sleep(0.002)
    ser.flush()
    time.sleep(0.5)
    resp = ser.read(256)
    if resp:
        console.print(f"  [green]Post-data: {resp.hex()}[/]")


def test_bitmap_no_hello(ser, img_data, fmt_name):
    """Skip HELLO, just send BITMAP + data with MAGIC."""
    console.print(f"\n  [cyan]Direct BITMAP + data, no init ({fmt_name})[/]")

    bitmap_cmd = MAGIC + pack6(0, 0, W - 1, H - 1, CMD_BITMAP)
    ser.reset_input_buffer()
    ser.write(bitmap_cmd)
    ser.flush()
    time.sleep(0.1)
    # Don't read response, immediately send data
    for i in range(0, len(img_data), 512):
        ser.write(img_data[i : i + 512])
    ser.flush()
    time.sleep(0.5)
    resp = ser.read(256)
    if resp:
        console.print(f"  [green]Post-data: {resp.hex()}[/]")
    else:
        console.print("  [dim]Post-data: no response[/]")


def test_bitmap_read_ack_then_data(ser, img_data, fmt_name):
    """Send BITMAP, wait for ack, THEN send data."""
    console.print(f"\n  [cyan]BITMAP → wait ack → data ({fmt_name})[/]")

    bitmap_cmd = MAGIC + pack6(0, 0, W - 1, H - 1, CMD_BITMAP)
    resp = send(ser, bitmap_cmd, "BITMAP cmd", wait=0.5)

    if resp:
        console.print("  Got ack, streaming data...")
        # Send data in 512B chunks with small delays
        for i in range(0, len(img_data), 512):
            ser.write(img_data[i : i + 512])
            time.sleep(0.002)
        ser.flush()
        time.sleep(1.0)
        resp2 = ser.read(256)
        if resp2:
            console.print(f"  [green]Post-data: {resp2.hex()}[/]")
        else:
            console.print("  [dim]Post-data: no response[/]")


def test_reva_bare_commands(ser, img_data, fmt_name):
    """Rev A commands WITHOUT 55 AA magic, but with full init sequence."""
    console.print(f"\n  [cyan]Bare Rev A (no magic) full sequence ({fmt_name})[/]")

    # Some devices only need magic for handshake, then bare commands work
    send(ser, MAGIC + bytes([CMD_HELLO] * 6), "HELLO (with magic)")

    # Now try bare commands
    send(ser, pack_orient(0), "ORIENT (bare)")
    send(ser, pack6(0, 0, 0, 100, CMD_BRIGHTNESS), "BRIGHT (bare)")
    send(ser, pack6(0, 0, W - 1, H - 1, CMD_BITMAP), "BITMAP (bare)")

    for i in range(0, len(img_data), W * 8 * 2):
        ser.write(img_data[i : i + W * 8 * 2])
        time.sleep(0.005)
    ser.flush()
    time.sleep(0.5)
    resp = ser.read(256)
    if resp:
        console.print(f"  [green]Post-data: {resp.hex()}[/]")


def test_pixels_command(ser, img_data, fmt_name):
    """Use DISPLAY_PIXELS instead of DISPLAY_BITMAP."""
    console.print(f"\n  [cyan]DISPLAY_PIXELS + data ({fmt_name})[/]")

    send(ser, MAGIC + bytes([CMD_HELLO] * 6), "HELLO")
    send(ser, MAGIC + pack_orient(0), "ORIENT")

    pixels_cmd = MAGIC + pack6(0, 0, W - 1, H - 1, CMD_PIXELS)
    send(ser, pixels_cmd, "PIXELS cmd", wait=0.5)

    for i in range(0, len(img_data), 512):
        ser.write(img_data[i : i + 512])
        time.sleep(0.002)
    ser.flush()
    time.sleep(0.5)
    resp2 = ser.read(256)
    if resp2:
        console.print(f"  [green]Post-data: {resp2.hex()}[/]")


def test_clear_then_bitmap(ser, img_data, fmt_name):
    """CLEAR screen first, then push bitmap."""
    console.print(f"\n  [cyan]CLEAR → BITMAP ({fmt_name})[/]")

    send(ser, MAGIC + pack6(0, 0, 0, 0, CMD_RESET), "RESET")
    time.sleep(0.5)
    send(ser, MAGIC + pack6(0, 0, 0, 0, CMD_CLEAR), "CLEAR")
    time.sleep(0.5)
    send(ser, MAGIC + pack_orient(0), "ORIENT")
    send(ser, MAGIC + pack6(0, 0, 0, 100, CMD_BRIGHTNESS), "BRIGHT")

    bitmap_cmd = MAGIC + pack6(0, 0, W - 1, H - 1, CMD_BITMAP)
    send(ser, bitmap_cmd, "BITMAP")

    for i in range(0, len(img_data), W * 8 * 2):
        ser.write(img_data[i : i + W * 8 * 2])
        time.sleep(0.005)
    ser.flush()
    time.sleep(0.5)
    resp = ser.read(256)
    if resp:
        console.print(f"  [green]Post-data: {resp.hex()}[/]")


def test_row_by_row(ser, img_data, fmt_name):
    """Send one BITMAP command per row, each with MAGIC."""
    console.print(f"\n  [cyan]Row-by-row with MAGIC ({fmt_name})[/]")

    send(ser, MAGIC + bytes([CMD_HELLO] * 6), "HELLO")
    send(ser, MAGIC + pack_orient(0), "ORIENT")

    row_bytes = W * 2  # 640 bytes per row for RGB565
    console.print(f"  Sending {H} rows...")
    for row in range(H):
        cmd = MAGIC + pack6(0, row, W - 1, row, CMD_BITMAP)
        data = img_data[row * row_bytes : (row + 1) * row_bytes]
        ser.write(cmd + data)
        time.sleep(0.002)
    ser.flush()
    time.sleep(0.5)
    resp = ser.read(256)
    if resp:
        console.print(f"  [green]Post-data: {resp.hex()}[/]")
    else:
        console.print("  [dim]Post-data: no response[/]")


def main():
    console.print("[bold cyan]Image Transfer Probe[/]")
    console.print(f"Port: {PORT}  Screen: {W}x{H}\n")

    try:
        ser = serial.Serial(PORT, BAUD, timeout=1, write_timeout=5)
    except serial.SerialException as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    time.sleep(0.5)

    img = make_image()
    rgb565_le = to_rgb565_le(img)
    rgb565_be = to_rgb565_be(img)
    jpeg = to_jpeg(img)
    bgra = to_bgra(img)
    bgr = to_bgr(img)

    console.print(
        f"  RGB565: {len(rgb565_le)}B  JPEG: {len(jpeg)}B  BGRA: {len(bgra)}B  BGR: {len(bgr)}B\n"
    )

    formats = [
        (rgb565_le, "RGB565 LE"),
        (rgb565_be, "RGB565 BE"),
    ]

    # ── Test 1: Full Rev A + MAGIC ────────────────────────────────────────
    console.print("[bold]═══ Test 1: Full Rev A + MAGIC init ═══[/]")
    for data, name in formats:
        test_full_reva_with_magic(ser, data, name)

    # ── Test 2: MAGIC per chunk ───────────────────────────────────────────
    console.print("\n[bold]═══ Test 2: MAGIC per data chunk ═══[/]")
    test_magic_per_chunk(ser, rgb565_le, "RGB565 LE")

    # ── Test 3: Direct bitmap, no init ────────────────────────────────────
    console.print("\n[bold]═══ Test 3: Direct BITMAP, skip init ═══[/]")
    for data, name in formats:
        test_bitmap_no_hello(ser, data, name)

    # ── Test 4: Bitmap ack then data ──────────────────────────────────────
    console.print("\n[bold]═══ Test 4: BITMAP → ack → data ═══[/]")
    for data, name in formats:
        test_bitmap_read_ack_then_data(ser, data, name)

    # ── Test 5: JPEG after ack ────────────────────────────────────────────
    console.print("\n[bold]═══ Test 5: BITMAP → ack → JPEG ═══[/]")
    test_bitmap_read_ack_then_data(ser, jpeg, "JPEG")

    # ── Test 6: BGRA and BGR formats ──────────────────────────────────────
    console.print("\n[bold]═══ Test 6: BGRA and BGR (Rev C formats) ═══[/]")
    test_bitmap_read_ack_then_data(ser, bgra, "BGRA")
    test_bitmap_read_ack_then_data(ser, bgr, "BGR")

    # ── Test 7: Bare Rev A after handshake ────────────────────────────────
    console.print("\n[bold]═══ Test 7: Bare Rev A after MAGIC handshake ═══[/]")
    test_reva_bare_commands(ser, rgb565_le, "RGB565 LE")

    # ── Test 8: DISPLAY_PIXELS ────────────────────────────────────────────
    console.print("\n[bold]═══ Test 8: DISPLAY_PIXELS command ═══[/]")
    test_pixels_command(ser, rgb565_le, "RGB565 LE")

    # ── Test 9: CLEAR then BITMAP ─────────────────────────────────────────
    console.print("\n[bold]═══ Test 9: RESET → CLEAR → BITMAP ═══[/]")
    test_clear_then_bitmap(ser, rgb565_le, "RGB565 LE")

    # ── Test 10: Row by row ───────────────────────────────────────────────
    console.print("\n[bold]═══ Test 10: Row-by-row with per-row BITMAP ═══[/]")
    test_row_by_row(ser, rgb565_le, "RGB565 LE")

    ser.close()
    console.print("\n[bold yellow]CHECK THE LCD after each test.[/]")
    console.print("If you saw ANY flash or color change, even brief, note which test number.")
