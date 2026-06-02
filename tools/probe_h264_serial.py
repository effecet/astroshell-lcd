#!/usr/bin/env python3
"""
H.264 via serial — send encoded H.264 through /dev/ttyACM0.
The device responds to 55 AA via serial, so try H.264 there too.

sudo .venv/bin/python tools/probe_h264_serial.py
"""

import os
import struct
import subprocess
import sys
import tempfile
import time

import serial
from PIL import Image, ImageDraw
from rich.console import Console

console = Console()
PORT = "/dev/ttyACM0"
BAUD = 115200
MAGIC = b"\x55\xaa"
W, H = 320, 320


def make_frame(path):
    img = Image.new("RGB", (W, H), (249, 115, 22))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 40, 40], fill=(34, 211, 238))
    draw.text((100, 140), "TEST", fill=(255, 255, 255))
    img.save(path)


def encode(png, out, extra_args=None):
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        png,
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-pix_fmt",
        "yuv420p",
        "-s",
        f"{W}x{H}",
        "-b:v",
        "500k",
        "-g",
        "1",
        "-bf",
        "0",
        "-frames:v",
        "1",
        "-f",
        "h264",
        out,
    ]
    if extra_args:
        cmd = cmd[:-2] + extra_args + cmd[-2:]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def send(ser, data, label, wait=0.5):
    ser.reset_input_buffer()
    ser.write(data)
    ser.flush()
    time.sleep(wait)
    resp = ser.read(512)
    if resp:
        console.print(f"  [green]{label}: {resp.hex()}[/]")
    else:
        console.print(f"  [dim]{label}: no response[/]")
    return resp


def main():
    console.print("[bold cyan]H.264 Serial Probe[/]\n")

    tmp = tempfile.mkdtemp()
    png = os.path.join(tmp, "test.png")
    h264 = os.path.join(tmp, "test.h264")

    make_frame(png)
    encode(png, h264)
    h264_data = open(h264, "rb").read()
    console.print(f"H.264: {len(h264_data)} bytes, starts: {h264_data[:12].hex()}")

    # Also make raw JPEG via ffmpeg
    jpeg_path = os.path.join(tmp, "test.jpg")
    subprocess.run(
        ["ffmpeg", "-y", "-i", png, "-s", f"{W}x{H}", "-q:v", "5", jpeg_path], capture_output=True
    )
    jpeg_data = open(jpeg_path, "rb").read()

    try:
        ser = serial.Serial(PORT, BAUD, timeout=1, write_timeout=5)
    except serial.SerialException as e:
        console.print(f"[red]{e}[/]")
        sys.exit(1)

    time.sleep(0.5)

    # 1. Handshake first
    console.print("\n[bold]1. Handshake[/]")
    send(ser, MAGIC + b"\x00" * 5, "55AA + 5 zeros")

    # 2. Raw H.264 after handshake
    console.print("\n[bold]2. Raw H.264 after handshake[/]")
    send(ser, MAGIC + b"\x00" * 5, "handshake")
    time.sleep(0.1)
    ser.write(h264_data)
    ser.flush()
    time.sleep(1)
    resp = ser.read(512)
    if resp:
        console.print(f"  [green]Post-H264: {resp.hex()}[/]")
    else:
        console.print("  [dim]Post-H264: no response[/]")

    # 3. MAGIC + length + H.264
    console.print("\n[bold]3. MAGIC + length(LE) + H.264[/]")
    pkt = MAGIC + struct.pack("<I", len(h264_data)) + h264_data
    send(ser, pkt, "MAGIC+len+H264", wait=1)

    # 4. MAGIC + length + H.264 (BE)
    console.print("\n[bold]4. MAGIC + length(BE) + H.264[/]")
    pkt = MAGIC + struct.pack(">I", len(h264_data)) + h264_data
    send(ser, pkt, "MAGIC+len(BE)+H264", wait=1)

    # 5. H.264 with 55 AA 08 00 ff ff 05 03 as init (echo the device's own response)
    console.print("\n[bold]5. Device response echo + H.264[/]")
    init = bytes.fromhex("55aa0800ffff0503")
    send(ser, init, "echo device response")
    time.sleep(0.1)
    ser.write(h264_data)
    ser.flush()
    time.sleep(1)
    resp = ser.read(512)
    if resp:
        console.print(f"  [green]Post-echo-H264: {resp.hex()}[/]")

    # 6. Try JPEG via serial with MAGIC framing
    console.print("\n[bold]6. MAGIC + len + JPEG[/]")
    pkt = MAGIC + struct.pack("<I", len(jpeg_data)) + jpeg_data
    send(ser, pkt, "MAGIC+len+JPEG", wait=1)

    # 7. Continuous H.264 stream via serial
    console.print("\n[bold]7. Continuous H.264 stream (5x)[/]")
    stream = h264_data * 5
    send(ser, MAGIC + b"\x00" * 5, "handshake")
    time.sleep(0.1)
    for i in range(0, len(stream), 512):
        ser.write(stream[i : i + 512])
        time.sleep(0.002)
    ser.flush()
    time.sleep(1)
    resp = ser.read(512)
    if resp:
        console.print(f"  [green]Post-stream: {resp.hex()}[/]")

    # 8. Try the response bytes as a "mode switch" command
    console.print("\n[bold]8. Response as mode switch[/]")
    # Maybe 0800 ffff 0503 means something we need to acknowledge
    for cmd in [
        b"\x08\x00",
        b"\x05\x03",
        b"\xff\xff",
        b"\x08\x00\xff\xff\x05\x03",
        b"\x00\x08\x03\x05",
    ]:
        pkt = MAGIC + cmd + b"\x00" * max(0, 5 - len(cmd))
        send(ser, pkt, f"MAGIC + {cmd.hex()}", wait=0.3)

    ser.close()
    console.print("\n[bold]Check the LCD![/]")


if __name__ == "__main__":
    main()
