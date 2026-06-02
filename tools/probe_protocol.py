#!/usr/bin/env python3
"""
Protocol probe — tries all known magic byte sequences from the Turing Smart Screen
family to find which one the Astroshell responds to.

Run this BEFORE implementing usb/protocol.py.

Usage:
    python tools/probe_protocol.py

If a sequence gets a response, update MAGIC and CMD_* constants in
astroshell/usb/protocol.py accordingly.
"""

import sys
import time
import struct
import serial
import serial.tools.list_ports
from rich.console import Console
from rich.table import Table

console = Console()

PORT = "/dev/ttyACM0"
BAUD = 115200
TIMEOUT = 1.0
WIDTH = 320
HEIGHT = 320

# Known magic bytes from the Turing/XuanFang/ThermalRight CDC ACM family
MAGIC_CANDIDATES = {
    "Turing Rev A/B": b"\x55\xaa",
    "Turing Rev C": b"\xaa\x55",
    "XuanFang": b"\x5a\xa5",
    "ThermalRight": b"\x3c\x3c",
    "Generic 1": b"\xff\xff",
    "Generic 2": b"\x00\x00",
}

# Typical command opcodes to probe alongside each magic
OPCODES = {
    "hello/ping": 0x00,
    "set_brightness": 0x01,
    "push_frame_start": 0x02,
    "set_orientation": 0x03,
    "clear": 0x06,
}


def try_sequence(ser: serial.Serial, name: str, magic: bytes, opcode: int) -> bytes | None:
    """Send magic+opcode and return any response bytes, or None."""
    ser.reset_input_buffer()
    cmd = magic + struct.pack("<BH", opcode, 0)
    ser.write(cmd)
    ser.flush()
    time.sleep(0.3)
    resp = ser.read(64)
    return resp if resp else None


def run_probe():
    console.print("\n[bold cyan]Astroshell Protocol Probe[/]")
    console.print(f"Port: [green]{PORT}[/]   Baud: [green]{BAUD}[/]\n")

    try:
        ser = serial.Serial(PORT, BAUD, timeout=TIMEOUT)
    except serial.SerialException as e:
        console.print(f"[red]Cannot open {PORT}: {e}[/]")
        console.print("[yellow]Make sure you're in the dialout group:[/]")
        console.print("  sudo usermod -aG dialout $USER  (then log out/in)")
        sys.exit(1)

    time.sleep(0.5)

    results = []

    for magic_name, magic in MAGIC_CANDIDATES.items():
        for opcode_name, opcode in OPCODES.items():
            resp = try_sequence(ser, magic_name, magic, opcode)
            hit = resp is not None
            results.append(
                (
                    magic_name,
                    magic.hex(),
                    opcode_name,
                    hex(opcode),
                    "[green]RESPONSE[/]" if hit else "[dim]—[/]",
                    resp.hex() if hit else "",
                )
            )
            if hit:
                console.print(
                    f"[bold green]✓ HIT![/]  magic={magic.hex()}  opcode={hex(opcode)}  "
                    f"({magic_name} / {opcode_name})"
                )
                console.print(f"   Response: {resp.hex()}")

    ser.close()

    t = Table(title="Probe Results", show_header=True, header_style="bold")
    t.add_column("Magic name")
    t.add_column("Magic bytes")
    t.add_column("Opcode name")
    t.add_column("Opcode")
    t.add_column("Response")
    t.add_column("Bytes")

    for row in results:
        t.add_row(*row)

    console.print(t)
    console.print(
        "\n[dim]No responses = device needs a full framed command (not just a header).[/]"
    )
    console.print("[dim]Next step: capture Wireshark USB traffic from the Windows app.[/]")


if __name__ == "__main__":
    run_probe()
