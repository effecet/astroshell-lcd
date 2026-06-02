#!/usr/bin/env python3
"""
REAL protocol implementation — extracted from Jungle Leopard Display JS source.

Packet: 55 AA [len_lo len_hi] [cmd] [payload...] [checksum_lo checksum_hi]
  - len = payload_length + 7
  - checksum = sum(all_bytes_before_checksum) & 0xFFFF, LE

Init: FF D9 FF D9 → getDeviceInfo(6) → startLive(17) → stream JPEG

sudo .venv/bin/python tools/probe_real.py
"""

import io
import sys
import time

import serial
from PIL import Image, ImageDraw
from rich.console import Console

console = Console()
PORT = "/dev/ttyACM0"
BAUD = 115200


def build_command(cmd: int, payload: bytes = b"") -> bytes:
    """Build a framed command packet with checksum."""
    magic = bytes([0x55, 0xAA])
    length = len(payload) + 7
    header = magic + bytes([length & 0xFF, (length >> 8) & 0xFF]) + bytes([cmd])
    packet = header + payload
    checksum = sum(packet) & 0xFFFF
    packet += bytes([checksum & 0xFF, (checksum >> 8) & 0xFF])
    return packet


def send_cmd(
    ser: serial.Serial,
    cmd: int,
    payload: bytes = b"",
    label: str = "",
    wait: float = 0.5,
    expect_json: bool = False,
) -> bytes:
    """Send command and read response."""
    pkt = build_command(cmd, payload)
    console.print(f"  TX {label}: {pkt.hex()}")
    ser.reset_input_buffer()
    ser.write(pkt)
    ser.flush()
    time.sleep(wait)

    # Read response — may need multiple reads for JSON
    resp = b""
    for _ in range(5):
        chunk = ser.read(4096)
        if chunk:
            resp += chunk
        elif resp:
            break
        time.sleep(0.1)

    if resp:
        console.print(f"  RX {label}: {resp.hex()}")
        if expect_json and len(resp) > 7:
            # Parse: strip 5 header bytes and 2 checksum bytes
            json_hex = resp[5:-2]
            try:
                json_str = bytes.fromhex(json_hex.hex()).decode("utf-8")
                console.print(f"  [green]JSON: {json_str}[/]")
            except Exception:
                console.print(f"  [dim]Raw payload: {json_hex.hex()}[/]")
    else:
        console.print(f"  [dim]RX {label}: no response[/]")
    return resp


def send_raw(ser: serial.Serial, data: bytes, label: str = ""):
    """Send raw bytes (no framing)."""
    console.print(f"  TX raw {label}: {data[:16].hex()}... ({len(data)} bytes)")
    ser.write(data)
    ser.flush()


def make_test_jpeg(quality: int = 80) -> bytes:
    """Create a 320x320 test JPEG."""
    img = Image.new("RGB", (320, 320), (249, 115, 22))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 40, 40], fill=(34, 211, 238))
    draw.line([(0, 160), (319, 160)], fill=(255, 255, 255), width=2)
    draw.line([(160, 0), (160, 319)], fill=(255, 255, 255), width=2)
    draw.text((80, 140), "ASTROSHELL", fill=(255, 255, 255))
    draw.text((80, 280), "effece", fill=(82, 82, 82))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def main():
    console.print("[bold cyan]Astroshell Real Protocol Test[/]\n")

    try:
        ser = serial.Serial(PORT, BAUD, timeout=1, write_timeout=5)
    except serial.SerialException as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    time.sleep(0.5)

    # ── Step 1: Stop (FF D9 FF D9) ───────────────────────────────────────
    console.print("[bold]Step 1: Stop current display (FF D9 FF D9)[/]")
    send_raw(ser, bytes([0xFF, 0xD9, 0xFF, 0xD9]), "stop")
    time.sleep(0.3)
    resp = ser.read(1024)
    if resp:
        console.print(f"  [green]Stop response: {resp.hex()}[/]")

    # ── Step 2: Get device info (key 6) ───────────────────────────────────
    console.print("\n[bold]Step 2: getDeviceInfo (cmd=6)[/]")
    resp = send_cmd(ser, 6, b"", "getDeviceInfo", wait=1.0, expect_json=True)

    # ── Step 3: Start live mode (key 17) ──────────────────────────────────
    console.print("\n[bold]Step 3: Start live mode (cmd=17)[/]")
    send_cmd(ser, 17, b"", "startLive", wait=0.5)

    # ── Step 4: Send test JPEG frame ──────────────────────────────────────
    console.print("\n[bold]Step 4: Send JPEG frame[/]")
    jpeg = make_test_jpeg()
    console.print(f"  JPEG size: {len(jpeg)} bytes")
    send_raw(ser, jpeg, "JPEG frame")
    time.sleep(1)
    resp = ser.read(1024)
    if resp:
        console.print(f"  [green]Frame response: {resp.hex()}[/]")
    else:
        console.print("  [dim]No frame response[/]")

    # ── Step 5: Send keepalive + another frame ────────────────────────────
    console.print("\n[bold]Step 5: Keepalive (cmd=17) + second frame[/]")
    send_cmd(ser, 17, b"", "keepalive", wait=0.2)
    jpeg2 = make_test_jpeg(quality=90)
    send_raw(ser, jpeg2, "JPEG frame 2")
    time.sleep(1)
    resp = ser.read(1024)
    if resp:
        console.print(f"  [green]Frame 2 response: {resp.hex()}[/]")

    # ── Step 6: Continuous stream ─────────────────────────────────────────
    console.print("\n[bold]Step 6: Continuous JPEG stream (5 frames)[/]")
    for i in range(5):
        if i % 2 == 0:
            send_cmd(ser, 17, b"", f"keepalive {i}", wait=0.1)
        jpeg = make_test_jpeg(quality=80)
        ser.write(jpeg)
        ser.flush()
        console.print(f"  Frame {i}: {len(jpeg)} bytes")
        time.sleep(0.3)

    # ── Step 7: Set brightness ────────────────────────────────────────────
    console.print("\n[bold]Step 7: Set brightness (cmd=3, value=100)[/]")
    send_cmd(ser, 3, bytes([100]), "brightness", wait=0.5)

    # ── Step 8: Restart ───────────────────────────────────────────────────
    console.print("\n[bold]Step 8: Restart (cmd=1)[/]")
    send_cmd(ser, 1, b"", "restart", wait=0.5)

    ser.close()
    console.print("\n[bold yellow]CHECK THE LCD![/]")
    console.print("If you see the orange test pattern with white crosshair — we're done!")


if __name__ == "__main__":
    main()
