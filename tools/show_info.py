#!/usr/bin/env python3
"""
Display device info on the Astroshell LCD.

sudo .venv/bin/python tools/show_info.py
"""

import io
import json
import time

import psutil
import serial
from PIL import Image, ImageDraw, ImageFont
from rich.console import Console

console = Console()
PORT = "/dev/ttyACM0"
BAUD = 115200
W, H = 320, 240  # confirmed from device


def build_cmd(cmd: int, payload: bytes = b"") -> bytes:
    magic = bytes([0x55, 0xAA])
    length = len(payload) + 7
    packet = magic + bytes([length & 0xFF, (length >> 8) & 0xFF, cmd]) + payload
    chk = sum(packet) & 0xFFFF
    return packet + bytes([chk & 0xFF, (chk >> 8) & 0xFF])


def send(ser, cmd, payload=b"", wait=0.5):
    ser.reset_input_buffer()
    ser.write(build_cmd(cmd, payload))
    ser.flush()
    time.sleep(wait)
    return ser.read(4096)


def get_device_info(ser) -> dict:
    resp = send(ser, 6, wait=1.0)
    if len(resp) > 7:
        try:
            return json.loads(resp[5:-2].decode("utf-8"))
        except Exception:
            pass
    return {}


def font(size=12):
    for path in [
        "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_info(info: dict) -> bytes:
    img = Image.new("RGB", (W, H), (13, 13, 13))
    draw = ImageDraw.Draw(img)

    # Header bar
    draw.rectangle([0, 0, W, 28], fill=(249, 115, 22))
    draw.text((8, 5), "ASTROSHELL LCD", font=font(14), fill=(13, 13, 13))

    # Cyan accent line
    draw.rectangle([0, 30, W, 32], fill=(34, 211, 238))

    y = 40
    data = info.get("data", info)

    lines = [
        ("UID", data.get("uid", "?")),
        ("Model", data.get("model", "?")),
        ("Version", data.get("version", "?")),
        ("Screen", f"{data.get('width', '?')}x{data.get('height', '?')}"),
        ("Brightness", f"{data.get('brightness', '?')}%"),
        ("Shape", data.get("shape", "?")),
        ("Display", "ON" if data.get("diplay_on") else "OFF"),
    ]

    # Add live system stats
    cpu_pct = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    lines.append(("CPU", f"{cpu_pct:.0f}%"))
    lines.append(("RAM", f"{mem.used / 1e9:.1f}/{mem.total / 1e9:.0f} GB"))

    fnt_label = font(11)
    fnt_value = font(11)

    for label, value in lines:
        draw.text((8, y), label, font=fnt_label, fill=(82, 82, 82))
        draw.text((110, y), str(value), font=fnt_value, fill=(229, 229, 229))
        y += 18

    # Footer
    draw.rectangle([0, H - 20, W, H], fill=(13, 13, 13))
    draw.text((8, H - 17), "# crafted by effece", font=font(10), fill=(82, 82, 82))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def main():
    console.print("[bold cyan]Astroshell LCD — Info Display[/]\n")

    ser = serial.Serial(PORT, BAUD, timeout=1, write_timeout=5)
    time.sleep(0.5)

    # Stop current
    ser.write(bytes([0xFF, 0xD9, 0xFF, 0xD9]))
    ser.flush()
    time.sleep(0.3)
    ser.read(1024)

    # Get info
    console.print("Getting device info...")
    info = get_device_info(ser)
    if info:
        console.print(f"  [green]{json.dumps(info, indent=2)}[/]")
    else:
        console.print("  [red]No device info[/]")
        info = {"data": {"uid": "?", "model": "?", "width": W, "height": H}}

    # Start live
    console.print("Starting live mode...")
    send(ser, 17, wait=0.3)

    # Render and send
    console.print("Sending info frame...")
    jpeg = render_info(info)
    console.print(f"  JPEG: {len(jpeg)} bytes")
    ser.write(jpeg)
    ser.flush()

    # Keep alive for 10 seconds
    console.print("Holding display for 10s...")
    for i in range(5):
        time.sleep(1.5)
        send(ser, 17, wait=0.1)
        ser.write(jpeg)
        ser.flush()

    console.print("[bold green]Done![/]")
    ser.close()


if __name__ == "__main__":
    main()
