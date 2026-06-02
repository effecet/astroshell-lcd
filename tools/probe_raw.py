#!/usr/bin/env python3
"""
Extended protocol probe for HONGTAI MONITOR (33c3:7792) LCD at /dev/ttyACM0.

Tries approaches beyond the standard Turing Smart Screen magic bytes:
  1. Raw JPEG push (no framing)
  2. Raw RGB565 push (framebuffer style)
  3. Multi-baud-rate scan with sync probes
  4. Turing revision-style init sequences
  5. USB control transfers via pyusb
  5b. USB bulk write approach (image data via pyusb, bypassing serial)
  6. Listen mode (passive read after port open/reopen)

Best run with sudo for serial access:
    sudo /opt/astroshell/.venv/bin/python tools/probe_raw.py

Without sudo, serial probes (1-4, 6) will be skipped; USB probes (5) still run.

# crafted by effece
"""

from __future__ import annotations

import io
import os
import struct
import time
from typing import Any

import serial
from PIL import Image, ImageDraw, ImageFont
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

PORT = "/dev/ttyACM0"
WIDTH = 320
HEIGHT = 320
DEFAULT_BAUD = 115200
READ_TIMEOUT = 1.0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_test_image() -> Image.Image:
    """Create a 320x320 orange image with white 'TEST' text."""
    img = Image.new("RGB", (WIDTH, HEIGHT), color=(249, 115, 22))  # #f97316
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "TEST", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (WIDTH - tw) // 2
    y = (HEIGHT - th) // 2
    draw.text((x, y), "TEST", fill=(255, 255, 255), font=font)
    return img


def image_to_jpeg(img: Image.Image, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def image_to_rgb565(img: Image.Image) -> bytes:
    """Convert to RGB565 big-endian, 2 bytes per pixel."""
    img = img.convert("RGB")
    pixels = img.load()
    data = bytearray()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = pixels[x, y]
            val = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            data += struct.pack(">H", val)
    return bytes(data)


def can_open_serial() -> bool:
    """Check if we have permission to open the serial port."""
    try:
        s = serial.Serial(PORT, DEFAULT_BAUD, timeout=0.1)
        s.close()
        return True
    except (serial.SerialException, PermissionError):
        return False


def open_serial(baud: int = DEFAULT_BAUD, timeout: float = READ_TIMEOUT) -> serial.Serial:
    return serial.Serial(
        port=PORT,
        baudrate=baud,
        timeout=timeout,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
    )


def drain_read(ser: serial.Serial, wait: float = 0.5, max_bytes: int = 4096) -> bytes:
    """Read whatever is available after a short wait."""
    time.sleep(wait)
    return ser.read(max_bytes)


def hexdump(data: bytes, prefix: str = "  ") -> str:
    if not data:
        return f"{prefix}(empty)"
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i : i + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        ascpart = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{prefix}{i:04x}: {hexpart:<48s}  {ascpart}")
    return "\n".join(lines)


def section(title: str) -> None:
    console.print(f"\n[bold cyan]{'=' * 60}[/]")
    console.print(f"[bold cyan]  {title}[/]")
    console.print(f"[bold cyan]{'=' * 60}[/]")


def report(label: str, data: bytes | None) -> None:
    if data:
        console.print(f"  [bold green]GOT RESPONSE[/] ({len(data)} bytes) for {label}:")
        console.print(hexdump(data))
    else:
        console.print(f"  [dim]no response[/] for {label}")


# ---------------------------------------------------------------------------
# Probe 1: Raw JPEG push (serial)
# ---------------------------------------------------------------------------


def probe_raw_jpeg() -> dict[str, Any]:
    section("1. Raw JPEG push (no framing)")
    img = make_test_image()
    jpeg_data = image_to_jpeg(img)
    console.print(f"  JPEG size: {len(jpeg_data)} bytes")

    results: dict[str, Any] = {}

    ser = open_serial()
    time.sleep(0.3)
    ser.reset_input_buffer()

    console.print("  Writing raw JPEG to port (full write)...")
    ser.write(jpeg_data)
    ser.flush()
    resp = drain_read(ser, wait=1.0)
    report("raw JPEG (full write)", resp)
    results["jpeg_full"] = resp

    ser.reset_input_buffer()
    console.print("  Writing JPEG in 512-byte chunks...")
    for i in range(0, len(jpeg_data), 512):
        ser.write(jpeg_data[i : i + 512])
    ser.flush()
    resp = drain_read(ser, wait=1.0)
    report("raw JPEG (512B chunks)", resp)
    results["jpeg_chunked"] = resp

    ser.close()
    return results


# ---------------------------------------------------------------------------
# Probe 2: Raw RGB565 push (serial)
# ---------------------------------------------------------------------------


def probe_raw_rgb565() -> dict[str, Any]:
    section("2. Raw RGB565 push (framebuffer style)")
    img = make_test_image()
    console.print("  Converting to RGB565 (big-endian)...")
    rgb_data = image_to_rgb565(img)
    console.print(f"  RGB565 size: {len(rgb_data)} bytes ({WIDTH}x{HEIGHT}x2)")

    results: dict[str, Any] = {}

    ser = open_serial()
    time.sleep(0.3)
    ser.reset_input_buffer()

    console.print("  Writing RGB565 in 512-byte chunks (BE)...")
    for i in range(0, len(rgb_data), 512):
        ser.write(rgb_data[i : i + 512])
    ser.flush()
    resp = drain_read(ser, wait=1.5)
    report("raw RGB565 (BE)", resp)
    results["rgb565_be"] = resp

    console.print("  Trying RGB565 little-endian variant...")
    le_data = bytearray()
    for i in range(0, len(rgb_data), 2):
        le_data.append(rgb_data[i + 1])
        le_data.append(rgb_data[i])
    ser.reset_input_buffer()
    for i in range(0, len(le_data), 512):
        ser.write(le_data[i : i + 512])
    ser.flush()
    resp = drain_read(ser, wait=1.5)
    report("raw RGB565 (LE)", resp)
    results["rgb565_le"] = resp

    ser.close()
    return results


# ---------------------------------------------------------------------------
# Probe 3: Multi-baud scan (serial)
# ---------------------------------------------------------------------------


def probe_baud_rates() -> dict[str, Any]:
    section("3. Multi-baud-rate scan")
    bauds = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]
    probes = {
        "sync_55aa": b"\x55\xaa\x00\x00\x00",
        "sync_aa55": b"\xaa\x55\x00\x00\x00",
        "three_zeros": b"\x00\x00\x00",
        "newline": b"\r\n",
        "AT_cmd": b"AT\r\n",
        "AT_query": b"AT+V\r\n",
        "question": b"?\r\n",
    }

    results: dict[str, Any] = {}

    for baud in bauds:
        console.print(f"\n  [yellow]Baud {baud}[/]")
        try:
            ser = serial.Serial(PORT, baud, timeout=0.5)
            time.sleep(0.2)
        except serial.SerialException as e:
            console.print(f"    [red]Cannot open at {baud}: {e}[/]")
            continue

        for probe_name, probe_data in probes.items():
            ser.reset_input_buffer()
            ser.write(probe_data)
            ser.flush()
            time.sleep(0.3)
            resp = ser.read(256)
            key = f"{baud}_{probe_name}"
            results[key] = resp
            if resp:
                console.print(f"    [bold green]RESPONSE[/] to {probe_name}: {resp.hex()}")
                console.print(hexdump(resp, prefix="      "))
            else:
                console.print(f"    [dim]no response to {probe_name}[/]")

        ser.reset_input_buffer()
        time.sleep(0.5)
        passive = ser.read(256)
        if passive:
            console.print(f"    [bold green]PASSIVE DATA[/] at {baud}: {passive.hex()}")
            console.print(hexdump(passive, prefix="      "))
        results[f"{baud}_passive"] = passive

        ser.close()

    return results


# ---------------------------------------------------------------------------
# Probe 4: Turing revision-style init sequences (serial)
# ---------------------------------------------------------------------------


def probe_turing_revisions() -> dict[str, Any]:
    section("4. Turing Smart Screen revision protocols")

    results: dict[str, Any] = {}
    img = make_test_image()
    jpeg_data = image_to_jpeg(img, quality=75)

    ser = open_serial()
    time.sleep(0.3)

    # Rev A style: 3-zero init
    console.print("\n  [yellow]Rev A style: 3-zero-byte init[/]")
    ser.reset_input_buffer()
    ser.write(b"\x00\x00\x00")
    ser.flush()
    resp = drain_read(ser, wait=0.5)
    report("3-zero init", resp)
    results["3zero_init"] = resp

    # Hello probes with various magics
    console.print("\n  [yellow]Turing hello (magic+hello+len)[/]")
    for magic_name, magic in [
        ("55AA", b"\x55\xaa"),
        ("AA55", b"\xaa\x55"),
        ("5AA5", b"\x5a\xa5"),
        ("A55A", b"\xa5\x5a"),
    ]:
        ser.reset_input_buffer()
        pkt = magic + b"\x00\x00\x00"
        ser.write(pkt)
        ser.flush()
        resp = drain_read(ser, wait=0.3)
        report(f"hello {magic_name}", resp)
        results[f"hello_{magic_name}"] = resp

    # Screen dimensions in header
    console.print("\n  [yellow]Dimension-in-header probes[/]")
    dim_headers = {
        "dim_BE": struct.pack(">HH", WIDTH, HEIGHT),
        "dim_LE": struct.pack("<HH", WIDTH, HEIGHT),
        "dim_BE_then_jpeg": struct.pack(">HH", WIDTH, HEIGHT) + jpeg_data[:512],
        "dim_LE_then_jpeg": struct.pack("<HH", WIDTH, HEIGHT) + jpeg_data[:512],
    }
    for name, data in dim_headers.items():
        ser.reset_input_buffer()
        ser.write(data)
        ser.flush()
        resp = drain_read(ser, wait=0.5)
        report(name, resp)
        results[name] = resp

    # Turing display-bitmap framing (LE coords)
    console.print("\n  [yellow]Turing display-bitmap command (LE coords)[/]")
    for magic_name, magic in [("55AA", b"\x55\xaa"), ("AA55", b"\xaa\x55")]:
        for cmd in [0x02, 0x06, 0x10, 0x20, 0xC0, 0xC2]:
            ser.reset_input_buffer()
            header = magic + struct.pack("<BHHHH", cmd, 0, 0, WIDTH, HEIGHT)
            ser.write(header + jpeg_data[:256])
            ser.flush()
            resp = drain_read(ser, wait=0.3)
            key = f"bitmap_{magic_name}_cmd{cmd:02x}"
            results[key] = resp
            if resp:
                console.print(f"    [bold green]RESPONSE[/] {key}: {resp.hex()}")
            else:
                console.print(f"    [dim]{key}[/]")

    # BE coords variant
    console.print("\n  [yellow]Turing bitmap (BE coords)[/]")
    for magic_name, magic in [("55AA", b"\x55\xaa"), ("AA55", b"\xaa\x55")]:
        for cmd in [0x02, 0x06, 0x10, 0x20]:
            ser.reset_input_buffer()
            header = magic + struct.pack(">BHHHH", cmd, 0, 0, WIDTH, HEIGHT)
            ser.write(header + jpeg_data[:256])
            ser.flush()
            resp = drain_read(ser, wait=0.3)
            key = f"bitmap_BE_{magic_name}_cmd{cmd:02x}"
            results[key] = resp
            if resp:
                console.print(f"    [bold green]RESPONSE[/] {key}: {resp.hex()}")
            else:
                console.print(f"    [dim]{key}[/]")

    # Single-byte command probes
    console.print("\n  [yellow]Single-byte command probes[/]")
    for byte_val in [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x10, 0x20, 0x40, 0x80, 0xC0, 0xFE, 0xFF]:
        ser.reset_input_buffer()
        ser.write(bytes([byte_val]))
        ser.flush()
        resp = drain_read(ser, wait=0.2)
        if resp:
            console.print(f"    [bold green]RESPONSE[/] to 0x{byte_val:02x}: {resp.hex()}")
        else:
            console.print(f"    [dim]0x{byte_val:02x}[/]")
        results[f"single_{byte_val:02x}"] = resp

    ser.close()
    return results


# ---------------------------------------------------------------------------
# Probe 5: USB control transfers + bulk via pyusb
# ---------------------------------------------------------------------------


def probe_usb_control() -> dict[str, Any]:
    section("5. USB control transfers and bulk I/O (pyusb)")
    results: dict[str, Any] = {}

    try:
        import usb.core
        import usb.util
    except ImportError:
        console.print("  [red]pyusb not installed. Skipping.[/]")
        return results

    dev = usb.core.find(idVendor=0x33C3, idProduct=0x7792)
    if dev is None:
        console.print("  [red]Device 33c3:7792 not found via pyusb.[/]")
        return results

    console.print(f"  [green]Found device[/]: Bus {dev.bus} Addr {dev.address}")
    try:
        console.print(f"  Manufacturer: {dev.manufacturer}")
        console.print(f"  Product:      {dev.product}")
        console.print(f"  Serial:       {dev.serial_number}")
    except Exception as e:
        console.print(f"  [yellow]Cannot read strings: {e}[/]")
    console.print(f"  Configs: {dev.bNumConfigurations}")

    # enumerate all interfaces and endpoints
    ep_out_addr = None
    ep_in_addr = None
    ep_out_maxpkt = 512

    for cfg in dev:
        console.print(f"\n  [yellow]Configuration {cfg.bConfigurationValue}[/]")
        for intf in cfg:
            console.print(
                f"    Interface {intf.bInterfaceNumber}, Alt {intf.bAlternateSetting}, "
                f"Class={intf.bInterfaceClass:#04x}, SubClass={intf.bInterfaceSubClass:#04x}, "
                f"Protocol={intf.bInterfaceProtocol:#04x}"
            )
            for ep in intf:
                direction = (
                    "IN"
                    if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN
                    else "OUT"
                )
                xfer_type = {0: "CTRL", 1: "ISO", 2: "BULK", 3: "INTR"}[
                    usb.util.endpoint_type(ep.bmAttributes)
                ]
                console.print(
                    f"      EP 0x{ep.bEndpointAddress:02x} ({direction}) "
                    f"MaxPkt={ep.wMaxPacketSize} Type={xfer_type}"
                )
                # remember bulk endpoints for later
                if xfer_type == "BULK":
                    if direction == "OUT" and ep_out_addr is None:
                        ep_out_addr = ep.bEndpointAddress
                        ep_out_maxpkt = ep.wMaxPacketSize
                    if direction == "IN" and ep_in_addr is None:
                        ep_in_addr = ep.bEndpointAddress

    # detach kernel driver (cdc_acm) so we can use pyusb directly
    detached = []
    for intf_num in range(3):  # try 0, 1, 2 in case there are more
        try:
            if dev.is_kernel_driver_active(intf_num):
                console.print(f"  Detaching kernel driver from interface {intf_num}...")
                dev.detach_kernel_driver(intf_num)
                detached.append(intf_num)
        except Exception:
            pass  # interface may not exist

    try:
        dev.set_configuration()
        console.print("  [green]Configuration set.[/]")
    except Exception as e:
        console.print(f"  [yellow]set_configuration: {e}[/]")

    # ---- Control transfer probes ----
    console.print("\n  [yellow]USB control transfer probes[/]")

    control_probes = [
        (0x80, 0x06, 0x0100, 0x0000, 18, "GET_DESCRIPTOR device"),
        (0x80, 0x06, 0x0200, 0x0000, 64, "GET_DESCRIPTOR config"),
        (0x80, 0x06, 0x0300, 0x0000, 64, "GET_DESCRIPTOR string idx0"),
        (0x80, 0x00, 0x0000, 0x0000, 2, "GET_STATUS device"),
        # CDC class requests (GET_LINE_CODING)
        (0xA1, 0x21, 0x0000, 0x0000, 7, "CDC GET_LINE_CODING intf0"),
        (0xA1, 0x21, 0x0000, 0x0001, 7, "CDC GET_LINE_CODING intf1"),
        # Vendor IN
        (0xC0, 0x00, 0x0000, 0x0000, 64, "VENDOR IN req=0x00"),
        (0xC0, 0x01, 0x0000, 0x0000, 64, "VENDOR IN req=0x01"),
        (0xC0, 0x02, 0x0000, 0x0000, 64, "VENDOR IN req=0x02"),
        (0xC0, 0x04, 0x0000, 0x0000, 64, "VENDOR IN req=0x04"),
        (0xC0, 0x05, 0x0000, 0x0000, 64, "VENDOR IN req=0x05"),
        (0xC0, 0x10, 0x0000, 0x0000, 64, "VENDOR IN req=0x10"),
        (0xC0, 0x20, 0x0000, 0x0000, 64, "VENDOR IN req=0x20"),
        (0xC0, 0x51, 0x0000, 0x0000, 64, "VENDOR IN req=0x51"),
        (0xC0, 0x80, 0x0000, 0x0000, 64, "VENDOR IN req=0x80"),
        (0xC0, 0xFE, 0x0000, 0x0000, 64, "VENDOR IN req=0xFE"),
        (0xC0, 0xFF, 0x0000, 0x0000, 64, "VENDOR IN req=0xFF"),
    ]

    for bmreq, breq, wval, widx, length, label in control_probes:
        try:
            resp = dev.ctrl_transfer(bmreq, breq, wval, widx, length, timeout=1000)
            resp_bytes = bytes(resp)
            console.print(
                f"    [bold green]RESPONSE[/] {label} ({len(resp_bytes)}B): {resp_bytes.hex()}"
            )
            if len(resp_bytes) <= 64:
                console.print(hexdump(resp_bytes, prefix="      "))
            results[label] = resp_bytes
        except Exception as e:
            err_str = str(e).lower()
            if "pipe" in err_str or "stall" in err_str:
                console.print(f"    [dim]STALL[/]  {label}")
            elif "timeout" in err_str:
                console.print(f"    [dim]TIMEOUT[/] {label}")
            else:
                console.print(f"    [yellow]{label}: {e}[/]")
            results[label] = None

    # ---- Vendor OUT control transfers ----
    console.print("\n  [yellow]Vendor OUT control transfers[/]")
    vendor_out_probes = [
        (0x40, 0x00, 0x0000, 0x0000, b"\x00", "VENDOR OUT req=0x00"),
        (0x40, 0x01, 0x0000, 0x0000, b"\x00", "VENDOR OUT req=0x01"),
        (0x40, 0x01, 0x0001, 0x0000, b"\x00", "VENDOR OUT req=0x01 wVal=1"),
        (0x40, 0x02, 0x0000, 0x0000, b"\x00", "VENDOR OUT req=0x02"),
        (0x40, 0x10, 0x0000, 0x0000, b"\x00", "VENDOR OUT req=0x10"),
    ]

    for bmreq, breq, wval, widx, data, label in vendor_out_probes:
        try:
            ret = dev.ctrl_transfer(bmreq, breq, wval, widx, data, timeout=1000)
            console.print(f"    [bold green]OK[/] {label} -> {ret}")
            results[label] = ret
        except Exception as e:
            err_str = str(e).lower()
            if "pipe" in err_str or "stall" in err_str:
                console.print(f"    [dim]STALL[/]  {label}")
            else:
                console.print(f"    [yellow]{label}: {e}[/]")
            results[label] = None

    # ---- Bulk reads (any unsolicited data?) ----
    console.print("\n  [yellow]Bulk endpoint reads (unsolicited data)[/]")
    if ep_in_addr is not None:
        try:
            data = dev.read(ep_in_addr, 4096, timeout=2000)
            data_bytes = bytes(data)
            console.print(f"    [bold green]DATA[/] from EP 0x{ep_in_addr:02x}: {len(data_bytes)}B")
            console.print(hexdump(data_bytes, prefix="      "))
            results[f"bulk_read_ep{ep_in_addr:02x}"] = data_bytes
        except Exception as e:
            console.print(f"    [dim]EP 0x{ep_in_addr:02x}: {e}[/]")
            results[f"bulk_read_ep{ep_in_addr:02x}"] = None
    else:
        console.print("    [dim]No bulk IN endpoint found[/]")

    # ---- 5b: USB Bulk write probes (bypass serial, write directly) ----
    if ep_out_addr is not None:
        console.print(f"\n  [yellow]5b. USB bulk write probes (EP OUT 0x{ep_out_addr:02x})[/]")
        img = make_test_image()
        jpeg_data = image_to_jpeg(img, quality=75)

        # Write magic probes via bulk OUT and read response
        bulk_probes: list[tuple[str, bytes]] = [
            ("bulk_3zeros", b"\x00\x00\x00"),
            ("bulk_55AA_hello", b"\x55\xaa\x00\x00\x00"),
            ("bulk_AA55_hello", b"\xaa\x55\x00\x00\x00"),
            ("bulk_AT", b"AT\r\n"),
            ("bulk_jpeg_first_512", jpeg_data[:512]),
            ("bulk_dim_BE_jpeg", struct.pack(">HH", WIDTH, HEIGHT) + jpeg_data[:508]),
        ]

        for label, data in bulk_probes:
            try:
                written = dev.write(ep_out_addr, data, timeout=1000)
                console.print(f"    Wrote {written}B for {label}")
                # try to read response
                time.sleep(0.3)
                if ep_in_addr is not None:
                    try:
                        resp = dev.read(ep_in_addr, 4096, timeout=1000)
                        resp_bytes = bytes(resp)
                        console.print(f"    [bold green]RESPONSE[/] {label}: {resp_bytes.hex()}")
                        console.print(hexdump(resp_bytes, prefix="      "))
                        results[f"usb_{label}_resp"] = resp_bytes
                    except Exception:
                        console.print(f"    [dim]no read response for {label}[/]")
                        results[f"usb_{label}_resp"] = None
            except Exception as e:
                console.print(f"    [yellow]{label} write failed: {e}[/]")
                results[f"usb_{label}"] = None

        # Try writing full JPEG via bulk
        console.print("\n    [yellow]Full JPEG via bulk OUT...[/]")
        try:
            total_written = 0
            for i in range(0, len(jpeg_data), ep_out_maxpkt):
                chunk = jpeg_data[i : i + ep_out_maxpkt]
                written = dev.write(ep_out_addr, chunk, timeout=1000)
                total_written += written
            console.print(f"    Wrote {total_written}B total JPEG via bulk")
            time.sleep(1.0)
            if ep_in_addr is not None:
                try:
                    resp = dev.read(ep_in_addr, 4096, timeout=1000)
                    resp_bytes = bytes(resp)
                    console.print(f"    [bold green]RESPONSE[/] full JPEG bulk: {resp_bytes.hex()}")
                    results["usb_bulk_full_jpeg_resp"] = resp_bytes
                except Exception:
                    console.print("    [dim]no read response after full JPEG bulk[/]")
                    results["usb_bulk_full_jpeg_resp"] = None
        except Exception as e:
            console.print(f"    [yellow]Full JPEG bulk write failed: {e}[/]")

        # Try writing Turing-framed JPEG via bulk
        console.print("\n    [yellow]Turing-framed JPEG via bulk OUT...[/]")
        for magic_name, magic in [("55AA", b"\x55\xaa"), ("AA55", b"\xaa\x55")]:
            for cmd in [0x02, 0xC2]:
                header = magic + struct.pack("<BHHHH", cmd, 0, 0, WIDTH, HEIGHT)
                framed = header + jpeg_data
                label = f"usb_bulk_turing_{magic_name}_cmd{cmd:02x}"
                try:
                    total_written = 0
                    for i in range(0, len(framed), ep_out_maxpkt):
                        chunk = framed[i : i + ep_out_maxpkt]
                        written = dev.write(ep_out_addr, chunk, timeout=1000)
                        total_written += written
                    console.print(f"    Wrote {total_written}B for {label}")
                    time.sleep(0.5)
                    if ep_in_addr is not None:
                        try:
                            resp = dev.read(ep_in_addr, 4096, timeout=1000)
                            resp_bytes = bytes(resp)
                            console.print(
                                f"    [bold green]RESPONSE[/] {label}: {resp_bytes.hex()}"
                            )
                            results[label] = resp_bytes
                        except Exception:
                            console.print(f"    [dim]no response for {label}[/]")
                            results[label] = None
                except Exception as e:
                    console.print(f"    [yellow]{label} failed: {e}[/]")
                    results[label] = None
    else:
        console.print("\n  [dim]No bulk OUT endpoint found, skipping 5b[/]")

    # reattach kernel drivers
    for intf_num in detached:
        try:
            dev.attach_kernel_driver(intf_num)
            console.print(f"  Reattached kernel driver to interface {intf_num}")
        except Exception:
            pass

    try:
        usb.util.dispose_resources(dev)
    except Exception:
        pass

    return results


# ---------------------------------------------------------------------------
# Probe 6: Listen mode (passive, serial)
# ---------------------------------------------------------------------------


def probe_listen_mode() -> dict[str, Any]:
    section("6. Listen mode (passive / port reopen)")
    results: dict[str, Any] = {}

    # Round 1: just open and listen
    console.print("\n  [yellow]Round 1: Open port, listen 5 seconds[/]")
    ser = open_serial()
    all_data = bytearray()
    start = time.time()
    while time.time() - start < 5.0:
        chunk = ser.read(256)
        if chunk:
            all_data.extend(chunk)
            console.print(
                f"    [green]Received {len(chunk)} bytes at +{time.time() - start:.1f}s[/]"
            )
            console.print(hexdump(chunk, prefix="      "))
    if all_data:
        console.print(f"  [bold green]Total received (round 1): {len(all_data)} bytes[/]")
    else:
        console.print("  [dim]No data received in 5 seconds.[/]")
    results["listen_r1"] = bytes(all_data)
    ser.close()

    # Round 2: close and reopen with DTR/RTS toggle
    console.print(
        "\n  [yellow]Round 2: Close, wait 1s, reopen + DTR/RTS toggle, listen 5 seconds[/]"
    )
    time.sleep(1.0)
    ser = open_serial()
    ser.dtr = False
    ser.rts = False
    time.sleep(0.1)
    ser.dtr = True
    ser.rts = True
    time.sleep(0.1)

    all_data = bytearray()
    start = time.time()
    while time.time() - start < 5.0:
        chunk = ser.read(256)
        if chunk:
            all_data.extend(chunk)
            console.print(
                f"    [green]Received {len(chunk)} bytes at +{time.time() - start:.1f}s[/]"
            )
            console.print(hexdump(chunk, prefix="      "))
    if all_data:
        console.print(f"  [bold green]Total received (round 2): {len(all_data)} bytes[/]")
    else:
        console.print("  [dim]No data received in 5 seconds.[/]")
    results["listen_r2"] = bytes(all_data)
    ser.close()

    # Round 3: DTR=True only
    console.print("\n  [yellow]Round 3: DTR=True, RTS=False, listen 3 seconds[/]")
    ser = open_serial()
    ser.dtr = True
    ser.rts = False
    all_data = bytearray()
    start = time.time()
    while time.time() - start < 3.0:
        chunk = ser.read(256)
        if chunk:
            all_data.extend(chunk)
            console.print(
                f"    [green]Received {len(chunk)} bytes at +{time.time() - start:.1f}s[/]"
            )
            console.print(hexdump(chunk, prefix="      "))
    if all_data:
        console.print(f"  [bold green]Total received (round 3): {len(all_data)} bytes[/]")
    else:
        console.print("  [dim]No data received in 3 seconds.[/]")
    results["listen_r3"] = bytes(all_data)
    ser.close()

    return results


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    console.print(
        Panel(
            "[bold orange1]HONGTAI MONITOR (33c3:7792) Extended Protocol Probe[/]\n"
            f"Port: {PORT}  |  Screen: {WIDTH}x{HEIGHT}\n"
            "Trying: raw JPEG, RGB565, multi-baud, Turing revisions, USB control, listen",
            title="probe_raw.py",
            border_style="cyan",
        )
    )

    serial_ok = can_open_serial()
    is_root = os.geteuid() == 0
    console.print(f"  Running as root: [{'green' if is_root else 'yellow'}]{is_root}[/]")
    console.print(f"  Serial port access: [{'green' if serial_ok else 'red'}]{serial_ok}[/]")
    if not serial_ok:
        console.print("  [bold yellow]Serial probes (1-4, 6) will be SKIPPED.[/]")
        console.print(
            "  [yellow]Run with: sudo /opt/astroshell/.venv/bin/python tools/probe_raw.py[/]"
        )
        console.print("  [yellow]Or add user to dialout: sudo usermod -aG dialout $USER[/]")

    all_results: dict[str, dict] = {}

    # Serial-dependent probes (1-4, 6)
    if serial_ok:
        for label, fn in [
            ("1_jpeg", probe_raw_jpeg),
            ("2_rgb565", probe_raw_rgb565),
            ("3_baud", probe_baud_rates),
            ("4_turing", probe_turing_revisions),
        ]:
            try:
                all_results[label] = fn()
            except Exception as e:
                console.print(f"  [red]Probe {label} failed: {e}[/]")
    else:
        console.print("\n  [dim]Skipping serial probes 1-4...[/]")

    # USB probe (always works)
    try:
        all_results["5_usb"] = probe_usb_control()
    except Exception as e:
        console.print(f"  [red]USB control probe failed: {e}[/]")
        import traceback

        traceback.print_exc()

    # Listen mode (serial-dependent)
    if serial_ok:
        try:
            all_results["6_listen"] = probe_listen_mode()
        except Exception as e:
            console.print(f"  [red]Listen mode failed: {e}[/]")
    else:
        console.print("\n  [dim]Skipping serial listen probe 6...[/]")

    # ---- Summary ----
    section("SUMMARY")

    hits: list[tuple[str, str, bytes]] = []
    total_probes = 0
    for category, probes in all_results.items():
        if not probes:
            continue
        for probe_name, data in probes.items():
            total_probes += 1
            if isinstance(data, (bytes, bytearray)) and len(data) > 0:
                hits.append((category, probe_name, bytes(data)))
            elif isinstance(data, int) and data > 0:
                hits.append((category, probe_name, f"returned={data}".encode()))

    console.print(f"\n  Total probes executed: {total_probes}")

    if hits:
        console.print(f"  [bold green]{len(hits)} probe(s) returned data:[/]\n")
        t = Table(show_header=True, header_style="bold")
        t.add_column("Category")
        t.add_column("Probe")
        t.add_column("Bytes")
        t.add_column("Hex (first 32B)")
        for cat, name, data in hits:
            t.add_row(cat, name, str(len(data)), data[:32].hex())
        console.print(t)

        console.print("\n  [bold]Full hex dumps of responses:[/]")
        for cat, name, data in hits:
            console.print(f"\n  [cyan]{cat} / {name}[/] ({len(data)} bytes):")
            console.print(hexdump(data))
    else:
        console.print("\n  [bold red]No probes returned any data.[/]")
        console.print("  Next steps:")
        console.print("    1. Run with sudo for serial probes (if not done)")
        console.print("    2. Wireshark USB capture of the official Windows app")
        console.print("    3. Check if the device uses a completely different protocol (HID, etc.)")
        console.print(
            "    4. Try the AIDA64 or HWiNFO Windows apps (some LCDs only respond to those)"
        )

    console.print()


if __name__ == "__main__":
    main()
