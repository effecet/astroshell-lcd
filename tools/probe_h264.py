#!/usr/bin/env python3
"""
H.264 USB bulk transfer probe for Astroshell LCD.

Discovery: The Windows app (SmartMonitor28) uses:
  - libopenh264 to encode frames as H.264
  - libusb/QUsb to send via USB bulk OUT (EP 0x01)
  - Transport class with initEncoder/run loop

This probe:
  1. Generates a test frame with ffmpeg → H.264 elementary stream
  2. Uses pyusb to detach CDC ACM driver, claim interface
  3. Sends H.264 NAL units via bulk OUT endpoint
  4. Tries multiple approaches: raw stream, with 55AA header, chunked

sudo .venv/bin/python tools/probe_h264.py

# crafted by effece
"""

import subprocess
import struct
import sys
import time
import tempfile
import os

from PIL import Image, ImageDraw

VID = 0x33C3
PID = 0x7792
EP_OUT = 0x01
EP_IN = 0x82
W, H = 320, 320


def make_test_frame(path: str):
    """Create a 320x320 orange test PNG."""
    img = Image.new("RGB", (W, H), (249, 115, 22))
    draw = ImageDraw.Draw(img)
    draw.line([(0, 160), (319, 160)], fill=(255, 255, 255), width=3)
    draw.line([(160, 0), (160, 319)], fill=(255, 255, 255), width=3)
    draw.rectangle([0, 0, 40, 40], fill=(34, 211, 238))
    draw.text((100, 140), "ASTROSHELL", fill=(255, 255, 255))
    img.save(path)


def encode_h264(
    png_path: str, h264_path: str, profile: str = "baseline", bitrate: str = "500k", gop: int = 1
):
    """Encode PNG to H.264 elementary stream using ffmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        png_path,
        "-t",
        "0.1",  # just a few frames
        "-c:v",
        "libx264",
        "-profile:v",
        profile,
        "-level",
        "3.1",
        "-pix_fmt",
        "yuv420p",
        "-s",
        f"{W}x{H}",
        "-b:v",
        bitrate,
        "-g",
        str(gop),  # keyframe every N frames
        "-bf",
        "0",  # no B-frames
        "-f",
        "h264",  # raw H.264 elementary stream (Annex B)
        h264_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffmpeg error: {result.stderr[-500:]}")
        return False
    return True


def encode_h264_single_idr(png_path: str, h264_path: str):
    """Encode just a single IDR frame."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        png_path,
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-level",
        "3.1",
        "-pix_fmt",
        "yuv420p",
        "-s",
        f"{W}x{H}",
        "-b:v",
        "1M",
        "-g",
        "1",
        "-bf",
        "0",
        "-frames:v",
        "1",
        "-f",
        "h264",
        h264_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def encode_mjpeg(png_path: str, mjpeg_path: str):
    """Encode as MJPEG — some devices use this instead of H.264."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        png_path,
        "-c:v",
        "mjpeg",
        "-q:v",
        "5",
        "-s",
        f"{W}x{H}",
        "-frames:v",
        "1",
        "-f",
        "mjpeg",
        mjpeg_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def find_device():
    """Find and open the Astroshell USB device."""
    import usb.core
    import usb.util

    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print("Device not found!")
        sys.exit(1)

    print(f"Found: {dev.manufacturer} {dev.product}")
    print(f"  Bus {dev.bus} Addr {dev.address}")

    # Detach kernel driver from both interfaces
    for intf in [0, 1]:
        if dev.is_kernel_driver_active(intf):
            print(f"  Detaching kernel driver from interface {intf}")
            dev.detach_kernel_driver(intf)

    dev.set_configuration()
    print("  Configuration set")

    return dev


def bulk_write(dev, data: bytes, label: str, chunk_size: int = 512):
    """Write data to bulk OUT endpoint in chunks."""
    import usb.core

    total = 0
    try:
        for i in range(0, len(data), chunk_size):
            chunk = data[i : i + chunk_size]
            dev.write(EP_OUT, chunk, timeout=5000)
            total += len(chunk)
        print(f"  [OK] {label}: wrote {total} bytes")
    except usb.core.USBError as e:
        print(f"  [ERR] {label}: {e} (wrote {total} bytes)")


def bulk_read(dev, label: str = "", size: int = 512, timeout: int = 1000) -> bytes:
    """Try to read from bulk IN endpoint."""
    import usb.core

    try:
        data = dev.read(EP_IN, size, timeout=timeout)
        if data:
            result = bytes(data)
            print(f"  [RECV] {label}: {result[:32].hex()} ({len(result)} bytes)")
            return result
    except usb.core.USBTimeoutError:
        pass
    except usb.core.USBError as e:
        print(f"  [ERR] read: {e}")
    return b""


def main():
    print("=== Astroshell H.264 USB Bulk Probe ===\n")

    # Create test frame
    tmpdir = tempfile.mkdtemp()
    png_path = os.path.join(tmpdir, "test.png")
    h264_path = os.path.join(tmpdir, "test.h264")
    h264_single = os.path.join(tmpdir, "single.h264")
    mjpeg_path = os.path.join(tmpdir, "test.mjpeg")

    print("Generating test frame...")
    make_test_frame(png_path)

    print("Encoding H.264 (baseline, multi-frame)...")
    if not encode_h264(png_path, h264_path):
        print("H.264 encoding failed!")
        sys.exit(1)

    print("Encoding H.264 (single IDR)...")
    encode_h264_single_idr(png_path, h264_single)

    print("Encoding MJPEG...")
    encode_mjpeg(png_path, mjpeg_path)

    h264_data = open(h264_path, "rb").read()
    h264_single_data = open(h264_single, "rb").read() if os.path.exists(h264_single) else b""
    mjpeg_data = open(mjpeg_path, "rb").read() if os.path.exists(mjpeg_path) else b""

    print(f"  H.264 multi: {len(h264_data)} bytes")
    print(f"  H.264 single IDR: {len(h264_single_data)} bytes")
    print(f"  MJPEG: {len(mjpeg_data)} bytes")
    print(f"  H.264 starts with: {h264_data[:16].hex()}")

    # Open USB device
    print("\nOpening USB device...")
    dev = find_device()

    MAGIC = b"\x55\xaa"

    # ── Test 1: Raw H.264 stream via bulk ─────────────────────────────────
    print("\n--- Test 1: Raw H.264 bulk write (multi-frame) ---")
    bulk_write(dev, h264_data, "H264 raw")
    bulk_read(dev, "after H264")

    time.sleep(1)

    # ── Test 2: Single IDR frame ──────────────────────────────────────────
    print("\n--- Test 2: Single H.264 IDR frame ---")
    bulk_write(dev, h264_single_data, "H264 single IDR")
    bulk_read(dev, "after IDR")

    time.sleep(1)

    # ── Test 3: 55 AA header then H.264 ───────────────────────────────────
    print("\n--- Test 3: MAGIC + H.264 ---")
    # Try: 55 AA + length + H264 data
    header = MAGIC + struct.pack("<I", len(h264_data))
    bulk_write(dev, header + h264_data, "MAGIC + len + H264")
    bulk_read(dev, "after MAGIC+H264")

    time.sleep(1)

    # ── Test 4: 55 AA + command + H.264 ───────────────────────────────────
    print("\n--- Test 4: MAGIC + cmd bytes + H.264 ---")
    # 55 AA + 6 zero bytes (triggers the known response) then H264
    handshake = MAGIC + b"\x00" * 5
    bulk_write(dev, handshake, "handshake")
    resp = bulk_read(dev, "handshake resp")
    if resp:
        print("  Got handshake ack, now sending H264...")
        bulk_write(dev, h264_data, "H264 after handshake")
        bulk_read(dev, "after H264")

    time.sleep(1)

    # ── Test 5: MJPEG via bulk ────────────────────────────────────────────
    print("\n--- Test 5: Raw MJPEG bulk write ---")
    bulk_write(dev, mjpeg_data, "MJPEG raw")
    bulk_read(dev, "after MJPEG")

    time.sleep(1)

    # ── Test 6: H.264 with per-chunk 55AA ─────────────────────────────────
    print("\n--- Test 6: H.264 with MAGIC per 512B chunk ---")
    import usb.core

    total = 0
    for i in range(0, len(h264_data), 510):
        chunk = h264_data[i : i + 510]  # 510 + 2 magic = 512
        try:
            dev.write(EP_OUT, MAGIC + chunk, timeout=5000)
            total += len(chunk)
        except usb.core.USBError:
            break
    print(f"  Wrote {total} bytes with per-chunk MAGIC")
    bulk_read(dev, "after chunked MAGIC+H264")

    time.sleep(1)

    # ── Test 7: Continuous H.264 stream (like a video) ────────────────────
    print("\n--- Test 7: Continuous H.264 stream (10 repeats) ---")
    stream = h264_single_data * 10  # repeat the IDR frame
    bulk_write(dev, stream, f"H264 stream ({len(stream)} bytes)")
    bulk_read(dev, "after stream")

    time.sleep(1)

    # ── Test 8: H.264 constrained baseline (OpenH264 compat) ─────────────
    print("\n--- Test 8: H.264 constrained baseline ---")
    h264_cb = os.path.join(tmpdir, "constrained.h264")
    encode_h264(png_path, h264_cb, profile="constrained_baseline", bitrate="300k")
    if os.path.exists(h264_cb):
        cb_data = open(h264_cb, "rb").read()
        print(f"  Constrained baseline: {len(cb_data)} bytes")
        bulk_write(dev, cb_data, "H264 constrained baseline")
        bulk_read(dev, "after CB")

    # ── Cleanup ───────────────────────────────────────────────────────────
    print("\n--- Reattaching kernel driver ---")
    try:
        import usb.util

        usb.util.dispose_resources(dev)
    except Exception:
        pass

    print("\nDone. CHECK THE LCD!")
    print("If nothing showed, the device may need the kernel driver reattached:")
    print(
        "  sudo sh -c 'echo 1-6 > /sys/bus/usb/drivers/usb/unbind && sleep 1 && echo 1-6 > /sys/bus/usb/drivers/usb/bind'"
    )


if __name__ == "__main__":
    main()
