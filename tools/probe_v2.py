#!/usr/bin/env python3
"""
Protocol probe v2 — tests ALL known LCD protocols against HONGTAI MONITOR (33c3:7792).

Covers protocols from turing-smart-screen-python Rev A/B/C/D + raw approaches.

Run with sudo:
    sudo /opt/astroshell/.venv/bin/python /opt/astroshell/tools/probe_v2.py

# crafted by effece
"""

import io
import struct
import sys
import time

import serial
from PIL import Image, ImageDraw
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

PORT = "/dev/ttyACM0"
BAUD = 115200
WIDTH, HEIGHT = 320, 320
TIMEOUT = 1.0

results: list[tuple[str, str, str]] = []


def log(name: str, resp: bytes | None, detail: str = ""):
    status = f"[green]RESPONSE {resp.hex()}[/]" if resp else "[dim]no response[/]"
    results.append((name, status, detail))
    if resp:
        console.print(f"  [bold green]HIT![/] {name}: {resp.hex()}")


def open_port(baud: int = BAUD) -> serial.Serial:
    return serial.Serial(PORT, baud, timeout=TIMEOUT, write_timeout=5)


def try_write_read(ser: serial.Serial, data: bytes, label: str, wait: float = 0.3) -> bytes | None:
    ser.reset_input_buffer()
    ser.write(data)
    ser.flush()
    time.sleep(wait)
    resp = ser.read(256)
    return resp if resp else None


def make_test_image() -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), (249, 115, 22))
    draw = ImageDraw.Draw(img)
    draw.text((120, 140), "TEST", fill=(255, 255, 255))
    return img


def encode_jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def encode_rgb565_be(img: Image.Image) -> bytes:
    pixels = list(img.convert("RGB").getdata())
    out = bytearray()
    for r, g, b in pixels:
        out += struct.pack(">H", ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
    return bytes(out)


def encode_rgb565_le(img: Image.Image) -> bytes:
    pixels = list(img.convert("RGB").getdata())
    out = bytearray()
    for r, g, b in pixels:
        out += struct.pack("<H", ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
    return bytes(out)


# ── Probe functions ──────────────────────────────────────────────────────────


def probe_rev_a(ser: serial.Serial):
    """Turing Rev A: HELLO = 0x45 x6, commands use 6-byte packed format."""
    console.print("\n[bold cyan]═══ Turing Rev A protocol ═══[/]")

    # HELLO
    hello = bytes([0x45] * 6)
    log("Rev A: HELLO (0x45 x6)", try_write_read(ser, hello, "hello"))

    # RESET = 101, CLEAR = 102, SCREEN_ON = 109, SET_BRIGHTNESS = 110
    for name, cmd in [("RESET", 101), ("CLEAR", 102), ("SCREEN_ON", 109), ("SET_BRIGHTNESS", 110)]:
        # 6-byte format: [0,0,0,0,0,cmd]
        pkt = bytes([0, 0, 0, 0, 0, cmd])
        log(f"Rev A: {name} ({cmd})", try_write_read(ser, pkt, name))


def probe_rev_c(ser: serial.Serial):
    """Turing Rev C: magic 0xef 0x69, HELLO = 0x01 0xef 0x69 ..."""
    console.print("\n[bold cyan]═══ Turing Rev C protocol ═══[/]")

    # HELLO
    hello = bytes([0x01, 0xEF, 0x69, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0xC5, 0xD3])
    log("Rev C: HELLO", try_write_read(ser, hello, "hello"))

    # QUERY_STATUS
    qstat = bytes([0xCF, 0xEF, 0x69, 0x00, 0x00, 0x00, 0x01])
    log("Rev C: QUERY_STATUS", try_write_read(ser, qstat, "query"))

    # SET_BRIGHTNESS
    bright = bytes([0x7B, 0xEF, 0x69, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00])
    log("Rev C: SET_BRIGHTNESS", try_write_read(ser, bright, "brightness"))

    # STOP_VIDEO
    stop = bytes([0x79, 0xEF, 0x69, 0x00, 0x00, 0x00, 0x01])
    log("Rev C: STOP_VIDEO", try_write_read(ser, stop, "stop"))

    # OPTIONS
    opts = bytes([0x7D, 0xEF, 0x69, 0x00, 0x00, 0x00, 0x05, 0x00, 0x00, 0x00, 0x2D])
    log("Rev C: OPTIONS", try_write_read(ser, opts, "options"))


def probe_rev_d(ser: serial.Serial):
    """Turing Rev D (Kipye): GETINFO=(71,0,0,0), chunk prefix 0x50."""
    console.print("\n[bold cyan]═══ Turing Rev D protocol ═══[/]")

    # GETINFO
    getinfo = bytes([71, 0, 0, 0])
    log("Rev D: GETINFO", try_write_read(ser, getinfo, "getinfo"))

    # SETORG (portrait)
    setorg = bytes([67, 72, 0, 0])
    log("Rev D: SETORG", try_write_read(ser, setorg, "setorg"))

    # SETBL (brightness 50%)
    setbl = bytes([67, 67, 0, 250])  # 50% * 5 = 250
    log("Rev D: SETBL (brightness)", try_write_read(ser, setbl, "brightness"))

    # DISPCOLOR (red)
    color = bytes([67, 66]) + struct.pack(">H", 0xF800)  # red in RGB565
    log("Rev D: DISPCOLOR (red)", try_write_read(ser, color, "color"))


def probe_original_magic(ser: serial.Serial):
    """Original probe: all Turing-family magic byte combos."""
    console.print("\n[bold cyan]═══ Original magic byte combos ═══[/]")

    magics = {
        "55AA": b"\x55\xaa",
        "AA55": b"\xaa\x55",
        "5AA5": b"\x5a\xa5",
        "3C3C": b"\x3c\x3c",
        "EF69": b"\xef\x69",
    }
    for name, magic in magics.items():
        for opcode in [0x00, 0x01, 0x02, 0x05, 0x06, 0x45, 0x69]:
            cmd = magic + struct.pack("<BH", opcode, 0)
            log(f"Magic {name} + op {hex(opcode)}", try_write_read(ser, cmd, "", wait=0.15))


def probe_raw_image(ser: serial.Serial):
    """Try sending raw image data with no framing."""
    console.print("\n[bold cyan]═══ Raw image push (no framing) ═══[/]")

    img = make_test_image()

    # Raw JPEG
    jpeg = encode_jpeg(img)
    console.print(f"  Sending raw JPEG ({len(jpeg)} bytes)...")
    log("Raw JPEG", try_write_read(ser, jpeg, "jpeg", wait=1.0))

    # Raw RGB565 BE (first 4KB only — full would be 200KB)
    rgb_be = encode_rgb565_be(img)[:4096]
    log("Raw RGB565 BE (4KB)", try_write_read(ser, rgb_be, "rgb565be", wait=0.5))

    # Raw RGB565 LE
    rgb_le = encode_rgb565_le(img)[:4096]
    log("Raw RGB565 LE (4KB)", try_write_read(ser, rgb_le, "rgb565le", wait=0.5))


def probe_at_commands(ser: serial.Serial):
    """Try AT-style commands (device advertises v.25ter AT protocol)."""
    console.print("\n[bold cyan]═══ AT commands (v.25ter) ═══[/]")

    for cmd in [
        b"AT\r\n",
        b"ATI\r\n",
        b"AT+GMI\r\n",
        b"AT+GMM\r\n",
        b"AT+CGMI\r\n",
        b"AT+CGMM\r\n",
        b"AT+CSQ\r\n",
        b"\r\n",
        b"\n",
    ]:
        label = cmd.strip().decode(errors="replace")
        log(f"AT: {label}", try_write_read(ser, cmd, label))


def probe_listen(ser: serial.Serial):
    """Just listen — some devices send init bytes on port open."""
    console.print("\n[bold cyan]═══ Passive listen ═══[/]")

    ser.reset_input_buffer()
    # Toggle DTR/RTS
    ser.dtr = False
    ser.rts = False
    time.sleep(0.2)
    ser.dtr = True
    ser.rts = True
    time.sleep(1.0)
    data = ser.read(256)
    log("Listen (DTR/RTS toggle)", data if data else None)

    # Just wait
    time.sleep(2.0)
    data = ser.read(256)
    log("Listen (2s passive)", data if data else None)


def probe_baud_rates():
    """Try different baud rates."""
    console.print("\n[bold cyan]═══ Baud rate scan ═══[/]")

    for baud in [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]:
        try:
            ser = serial.Serial(PORT, baud, timeout=0.5)
            time.sleep(0.2)
            # Listen
            data = ser.read(64)
            if data:
                log(f"Baud {baud}: passive data", data)
            # Send hello probes
            for probe in [
                bytes([0x45] * 6),
                bytes([0x01, 0xEF, 0x69, 0x00, 0x00, 0x00, 0x01]),
                bytes([71, 0, 0, 0]),
                b"AT\r\n",
            ]:
                resp = try_write_read(ser, probe, "", wait=0.2)
                if resp:
                    log(f"Baud {baud}: response to {probe[:4].hex()}", resp)
            ser.close()
        except Exception as e:
            log(f"Baud {baud}: error", None, str(e))


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    console.print(
        Panel(
            "[bold]Astroshell Protocol Probe v2[/]\n"
            f"Port: {PORT}  Baud: {BAUD}\n"
            "Testing Rev A + Rev C + Rev D + magic combos + raw + AT + listen + baud scan",
            style="cyan",
        )
    )

    try:
        ser = open_port()
    except serial.SerialException as e:
        console.print(f"[red]Cannot open {PORT}: {e}[/]")
        console.print("[yellow]Run with: sudo .venv/bin/python tools/probe_v2.py[/]")
        sys.exit(1)

    time.sleep(0.5)

    probe_listen(ser)
    probe_rev_a(ser)
    probe_rev_c(ser)
    probe_rev_d(ser)
    probe_at_commands(ser)
    probe_original_magic(ser)
    probe_raw_image(ser)
    ser.close()

    probe_baud_rates()

    # Summary
    console.print()
    t = Table(title="Probe v2 Results", show_header=True, header_style="bold")
    t.add_column("Test", style="dim", max_width=40)
    t.add_column("Result")
    t.add_column("Detail", max_width=30)
    for name, status, detail in results:
        t.add_row(name, status, detail)
    console.print(t)

    hits = [r for r in results if "RESPONSE" in r[1]]
    if hits:
        console.print(f"\n[bold green]Found {len(hits)} response(s)! Protocol may be cracked.[/]")
    else:
        console.print(
            "\n[yellow]No responses. Next step: usbmon + Wireshark on Linux to sniff USB packets.[/]"
        )


if __name__ == "__main__":
    main()
