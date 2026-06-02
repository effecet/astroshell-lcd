#!/usr/bin/env python3
"""
Push a test frame to the Astroshell LCD.

Protocol confirmed: Turing Rev A family
  Magic: 0x55 0xAA
  Response: 55 aa 08 00 ff ff 05 03
  Baud: 115200 / 8N1
  Coords: packed 5-byte format + command byte

Run with sudo:
    sudo /opt/astroshell/.venv/bin/python /opt/astroshell/tools/push_frame.py

# crafted by effece
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
WIDTH, HEIGHT = 320, 320
CHUNK_SIZE = 512

# ── Turing Rev A protocol constants ──────────────────────────────────────────
MAGIC = b"\x55\xaa"

# Rev A commands (from turing-smart-screen-python lcd_comm_rev_a.py)
CMD_RESET = 101
CMD_CLEAR = 102
CMD_TO_BLACK = 103
CMD_SCREEN_OFF = 108
CMD_SCREEN_ON = 109
CMD_SET_BRIGHTNESS = 110
CMD_SET_ORIENT = 121
CMD_DISPLAY_BITMAP = 197
CMD_DISPLAY_PIXELS = 195
CMD_HELLO = 69
CMD_SET_MIRROR = 122


def pack_command(x: int, y: int, ex: int, ey: int, cmd: int) -> bytes:
    """Pack a 6-byte Turing Rev A command with coordinates."""
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


def pack_orient(x: int, y: int, ex: int, ey: int, orient: int, w: int, h: int) -> bytes:
    """Pack SET_ORIENTATION with width/height (16 bytes)."""
    base = pack_command(x, y, ex, ey, CMD_SET_ORIENT)
    return base + bytes([orient + 100]) + struct.pack(">HH", w, h) + bytes([0] * 5)


def encode_rgb565_le(img: Image.Image) -> bytes:
    """Encode image as RGB565 little-endian (Rev A format)."""
    pixels = list(img.convert("RGB").getdata())
    out = bytearray()
    for r, g, b in pixels:
        rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out += struct.pack("<H", rgb565)
    return bytes(out)


def encode_rgb565_be(img: Image.Image) -> bytes:
    """Encode image as RGB565 big-endian."""
    pixels = list(img.convert("RGB").getdata())
    out = bytearray()
    for r, g, b in pixels:
        rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out += struct.pack(">H", rgb565)
    return bytes(out)


def encode_jpeg(img: Image.Image, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def write_chunked(ser: serial.Serial, data: bytes, chunk_size: int = CHUNK_SIZE):
    """Write data in chunk_size byte blocks."""
    for i in range(0, len(data), chunk_size):
        ser.write(data[i : i + chunk_size])
    ser.flush()


def read_response(ser: serial.Serial, wait: float = 0.3) -> bytes | None:
    time.sleep(wait)
    data = ser.read(256)
    return data if data else None


def make_test_image() -> Image.Image:
    """Create effece-branded test image."""
    img = Image.new("RGB", (WIDTH, HEIGHT), (13, 13, 13))  # #0d0d0d
    draw = ImageDraw.Draw(img)

    # Orange bar
    draw.rectangle([0, 0, 319, 40], fill=(249, 115, 22))
    draw.text((80, 10), "ASTROSHELL", fill=(255, 255, 255))

    # Cyan bar
    draw.rectangle([0, 50, 319, 70], fill=(34, 211, 238))

    # Status text
    draw.text((20, 90), "Protocol: 55 AA", fill=(229, 229, 229))
    draw.text((20, 120), "Status: CONNECTED", fill=(34, 211, 238))
    draw.text((20, 150), "Screen: 320x320", fill=(229, 229, 229))
    draw.text((20, 180), "Baud: 115200", fill=(229, 229, 229))

    # Footer
    draw.text((20, 290), "# crafted by effece", fill=(82, 82, 82))

    return img


def try_approach(
    ser: serial.Serial,
    name: str,
    cmd_bytes: bytes,
    image_data: bytes | None = None,
    read_first: bool = True,
):
    """Send command, optionally image data, report results."""
    console.print(f"\n  [cyan]{name}[/]")

    ser.reset_input_buffer()
    ser.write(cmd_bytes)
    ser.flush()

    resp = read_response(ser, 0.3)
    if resp:
        console.print(f"    [green]Command response: {resp.hex()}[/]")
    else:
        console.print("    [dim]No command response[/]")

    if image_data:
        console.print(f"    Sending {len(image_data)} bytes image data...")
        write_chunked(ser, image_data)
        resp2 = read_response(ser, 1.0)
        if resp2:
            console.print(f"    [green]Image response: {resp2.hex()}[/]")
        else:
            console.print("    [dim]No image response[/]")


def main():
    console.print("[bold cyan]Astroshell Frame Push Test[/]")
    console.print(f"Port: {PORT}  Baud: {BAUD}\n")

    try:
        ser = serial.Serial(PORT, BAUD, timeout=1, write_timeout=5)
    except serial.SerialException as e:
        console.print(f"[red]Cannot open {PORT}: {e}[/]")
        sys.exit(1)

    time.sleep(0.5)
    img = make_test_image()
    jpeg_data = encode_jpeg(img)
    rgb565_le = encode_rgb565_le(img)
    rgb565_be = encode_rgb565_be(img)

    console.print(f"  Image: {WIDTH}x{HEIGHT}")
    console.print(f"  JPEG: {len(jpeg_data)} bytes")
    console.print(f"  RGB565: {len(rgb565_le)} bytes")

    # ── 1. HELLO ──────────────────────────────────────────────────────────────
    console.print("\n[bold]═══ Step 1: HELLO ═══[/]")
    hello = bytes([CMD_HELLO] * 6)
    ser.reset_input_buffer()
    ser.write(hello)
    ser.flush()
    resp = read_response(ser, 0.5)
    if resp:
        console.print(f"  [green]HELLO response: {resp.hex()}[/]")
    else:
        console.print("  [dim]No HELLO response[/]")

    # ── 2. SET_ORIENTATION ────────────────────────────────────────────────────
    console.print("\n[bold]═══ Step 2: SET_ORIENTATION ═══[/]")
    for orient_val in [0, 1, 2, 3]:
        orient_cmd = pack_orient(0, 0, 0, 0, orient_val, WIDTH, HEIGHT)
        ser.reset_input_buffer()
        ser.write(orient_cmd)
        ser.flush()
        resp = read_response(ser, 0.3)
        if resp:
            console.print(f"  [green]Orient {orient_val} response: {resp.hex()}[/]")

    # ── 3. SET_BRIGHTNESS ─────────────────────────────────────────────────────
    console.print("\n[bold]═══ Step 3: SET_BRIGHTNESS ═══[/]")
    bright_cmd = pack_command(0, 0, 0, 100, CMD_SET_BRIGHTNESS)
    ser.reset_input_buffer()
    ser.write(bright_cmd)
    ser.flush()
    resp = read_response(ser, 0.3)
    if resp:
        console.print(f"  [green]Brightness response: {resp.hex()}[/]")

    # ── 4. DISPLAY_BITMAP + image data ────────────────────────────────────────
    console.print("\n[bold]═══ Step 4: DISPLAY_BITMAP + image ═══[/]")

    # 4a: Full-screen bitmap command + RGB565 LE (Rev A default)
    bitmap_cmd = pack_command(0, 0, WIDTH - 1, HEIGHT - 1, CMD_DISPLAY_BITMAP)
    try_approach(ser, "DISPLAY_BITMAP + RGB565 LE (Rev A style)", bitmap_cmd, rgb565_le)

    time.sleep(0.5)

    # 4b: Full-screen bitmap + RGB565 BE
    try_approach(ser, "DISPLAY_BITMAP + RGB565 BE", bitmap_cmd, rgb565_be)

    time.sleep(0.5)

    # 4c: Full-screen bitmap + JPEG
    try_approach(ser, "DISPLAY_BITMAP + JPEG", bitmap_cmd, jpeg_data)

    time.sleep(0.5)

    # ── 5. Raw approaches (command + image in one stream) ─────────────────────
    console.print("\n[bold]═══ Step 5: Combined command+image approaches ═══[/]")

    # 5a: Magic + bitmap header + RGB565
    combined_a = MAGIC + bitmap_cmd + rgb565_le
    try_approach(ser, "MAGIC + BITMAP_CMD + RGB565 LE", combined_a)

    time.sleep(0.5)

    # 5b: Magic + bitmap header + JPEG
    combined_b = MAGIC + bitmap_cmd + jpeg_data
    try_approach(ser, "MAGIC + BITMAP_CMD + JPEG", combined_b)

    time.sleep(0.5)

    # ── 6. Row-by-row approach ────────────────────────────────────────────────
    console.print("\n[bold]═══ Step 6: Row-by-row bitmap ═══[/]")
    console.print("  Sending 320 rows, each with its own DISPLAY_BITMAP command...")
    for row in range(0, HEIGHT, HEIGHT // 4):  # test 4 rows only
        row_cmd = pack_command(0, row, WIDTH - 1, row, CMD_DISPLAY_BITMAP)
        row_data = rgb565_le[row * WIDTH * 2 : (row + 1) * WIDTH * 2]
        ser.reset_input_buffer()
        ser.write(row_cmd)
        ser.write(row_data)
        ser.flush()
    time.sleep(0.5)
    resp = read_response(ser, 0.5)
    if resp:
        console.print(f"  [green]Row response: {resp.hex()}[/]")
    else:
        console.print("  [dim]No row response[/]")

    # ── 7. Stripe pattern approach (Rev A chunk size) ─────────────────────────
    console.print("\n[bold]═══ Step 7: Rev A chunk-by-chunk (display_width * 8) ═══[/]")
    bitmap_cmd = pack_command(0, 0, WIDTH - 1, HEIGHT - 1, CMD_DISPLAY_BITMAP)
    ser.reset_input_buffer()
    ser.write(bitmap_cmd)
    ser.flush()
    time.sleep(0.1)
    # Rev A sends RGB565 in chunks of (width * 8) pixels = width * 8 * 2 bytes
    row_chunk = WIDTH * 8 * 2  # 8 rows at a time = 5120 bytes
    for i in range(0, len(rgb565_le), row_chunk):
        ser.write(rgb565_le[i : i + row_chunk])
        time.sleep(0.01)
    ser.flush()
    time.sleep(0.5)
    resp = read_response(ser, 0.5)
    if resp:
        console.print(f"  [green]Chunk response: {resp.hex()}[/]")

    # ── 8. DISPLAY_PIXELS approach ────────────────────────────────────────────
    console.print("\n[bold]═══ Step 8: DISPLAY_PIXELS + data ═══[/]")
    pixels_cmd = pack_command(0, 0, WIDTH - 1, HEIGHT - 1, CMD_DISPLAY_PIXELS)
    try_approach(ser, "DISPLAY_PIXELS + RGB565 LE", pixels_cmd, rgb565_le)

    ser.close()
    console.print("\n[bold]Done. Check the LCD screen — did anything appear?[/]")
    console.print(
        "[dim]If the screen is still showing its default, try unplugging and replugging USB.[/]"
    )


if __name__ == "__main__":
    main()
