#!/usr/bin/env python3
"""
Targeted handshake probe — we know 55 AA works, now figure out the exact
command structure and init sequence.

Response so far: 55 aa 08 00 ff ff 05 03
  - Same response regardless of command — device may be sending device info
  - Need to find the right init to enter "display mode"

sudo .venv/bin/python tools/probe_handshake.py
"""

import struct
import time

import serial
from rich.console import Console

console = Console()
PORT = "/dev/ttyACM0"
BAUD = 115200
MAGIC = b"\x55\xaa"


def send(ser, data: bytes, label: str, wait: float = 0.3) -> bytes | None:
    ser.reset_input_buffer()
    ser.write(data)
    ser.flush()
    time.sleep(wait)
    resp = ser.read(256)
    if resp:
        console.print(f"  [green]{label}: {resp.hex()}[/]")
    else:
        console.print(f"  [dim]{label}: —[/]")
    return resp if resp else None


def main():
    console.print("[bold cyan]Handshake Probe[/]\n")

    ser = serial.Serial(PORT, BAUD, timeout=1, write_timeout=5)
    time.sleep(0.5)

    # ── 1. Just magic bytes alone ─────────────────────────────────────────
    console.print("[bold]1. Bare magic[/]")
    send(ser, MAGIC, "55 AA alone")
    send(ser, MAGIC + b"\x00", "55 AA 00")
    send(ser, MAGIC + b"\x01", "55 AA 01")
    send(ser, MAGIC + b"\x00\x00", "55 AA 00 00")
    send(ser, MAGIC + b"\x00\x00\x00", "55 AA 00 00 00")
    send(ser, MAGIC + b"\x00\x00\x00\x00", "55 AA 00 00 00 00")

    # ── 2. Magic + single byte scan (find which bytes change the response)
    console.print("\n[bold]2. Magic + 1 byte (key opcodes)[/]")
    responses = {}
    for b in range(256):
        ser.reset_input_buffer()
        ser.write(MAGIC + bytes([b]))
        ser.flush()
        time.sleep(0.1)
        resp = ser.read(256)
        if resp:
            h = resp.hex()
            if h not in responses:
                responses[h] = []
            responses[h].append(b)

    for resp_hex, opcodes in responses.items():
        if len(opcodes) <= 10:
            ops = ", ".join(f"0x{o:02x}" for o in opcodes)
        else:
            ops = f"{len(opcodes)} opcodes (0x{opcodes[0]:02x}..0x{opcodes[-1]:02x})"
        console.print(f"  [green]Response {resp_hex}[/] ← {ops}")

    if not responses:
        console.print("  [dim]No responses to single-byte commands[/]")

    # ── 3. Magic + HELLO ──────────────────────────────────────────────────
    console.print("\n[bold]3. Magic + HELLO variants[/]")
    send(ser, MAGIC + bytes([0x45] * 6), "55AA + HELLO (45x6)")
    send(ser, MAGIC + bytes([0x45] * 4), "55AA + HELLO (45x4)")
    send(ser, MAGIC + b"\x69", "55AA + 0x69 (HELLO opcode)")

    # ── 4. Structured command formats ─────────────────────────────────────
    console.print("\n[bold]4. Structured formats: MAGIC + CMD + LEN + DATA[/]")

    # Format A: 55 AA CMD LEN_LE PAYLOAD
    for cmd in [0x00, 0x01, 0x02, 0x04, 0x05, 0x06, 0x10, 0x45, 0x65, 0x69]:
        pkt = MAGIC + bytes([cmd]) + struct.pack("<H", 0)
        send(ser, pkt, f"55AA {cmd:02x} len=0 (LE)", wait=0.15)

    # Format B: 55 AA LEN CMD PAYLOAD
    console.print("\n  [cyan]Format B: 55 AA LEN CMD[/]")
    for cmd in [0x00, 0x01, 0x02, 0x45, 0x65, 0x69, 0xC5]:
        pkt = MAGIC + struct.pack("<H", 1) + bytes([cmd])
        send(ser, pkt, f"55AA len=1 cmd={cmd:02x}", wait=0.15)

    # ── 5. Response 05 03 exploration ─────────────────────────────────────
    # Maybe 05 03 is telling us something — try protocol version negotiation
    console.print("\n[bold]5. Protocol version responses[/]")
    send(ser, MAGIC + b"\x05\x03", "55AA + 05 03 (echo version?)")
    send(ser, MAGIC + b"\x03\x05", "55AA + 03 05 (swapped)")
    send(ser, MAGIC + b"\x08\x00\xff\xff\x05\x03", "55AA + full response echo")

    # ── 6. Init sequences from other LCD families ─────────────────────────
    console.print("\n[bold]6. Other init sequences[/]")
    # Some devices need DTR/RTS signals
    ser.dtr = True
    ser.rts = True
    time.sleep(0.2)
    send(ser, MAGIC, "55AA after DTR+RTS=HIGH")

    ser.dtr = False
    ser.rts = False
    time.sleep(0.2)
    ser.dtr = True
    ser.rts = True
    time.sleep(0.2)
    send(ser, MAGIC + b"\x01", "55AA 01 after DTR toggle")

    # Break signal
    ser.send_break(duration=0.1)
    time.sleep(0.2)
    send(ser, MAGIC, "55AA after BREAK")

    # ── 7. Length field experiments ────────────────────────────────────────
    console.print("\n[bold]7. What minimum packet gets a response?[/]")
    for length in range(1, 12):
        pkt = MAGIC + b"\x00" * length
        r = send(ser, pkt, f"55AA + {length} zero bytes", wait=0.15)

    # ── 8. Try interpreting response as "send me N bytes" ─────────────────
    console.print("\n[bold]8. Response might be 'ready for data' — try follow-up[/]")
    # Send command, get response, then immediately send image data
    from PIL import Image
    import io

    img = Image.new("RGB", (320, 320), (249, 115, 22))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    jpeg = buf.getvalue()

    # Approach: magic + zeros (trigger response), then stream JPEG
    ser.reset_input_buffer()
    ser.write(MAGIC + b"\x00" * 6)
    ser.flush()
    time.sleep(0.3)
    resp1 = ser.read(256)
    if resp1:
        console.print(f"  [green]Got ack: {resp1.hex()} — now sending JPEG...[/]")
        # Send JPEG immediately after ack
        for i in range(0, len(jpeg), 512):
            ser.write(jpeg[i : i + 512])
        ser.flush()
        time.sleep(1.0)
        resp2 = ser.read(256)
        if resp2:
            console.print(f"  [green]Post-JPEG response: {resp2.hex()}[/]")
        else:
            console.print("  [dim]No post-JPEG response[/]")
    else:
        console.print("  [dim]No initial ack[/]")

    # Same but with RGB565
    console.print("  Trying RGB565 after ack...")
    ser.reset_input_buffer()
    ser.write(MAGIC + b"\x00" * 6)
    ser.flush()
    time.sleep(0.3)
    resp1 = ser.read(256)
    if resp1:
        console.print(f"  [green]Got ack: {resp1.hex()} — now sending RGB565...[/]")
        pixels = list(img.convert("RGB").getdata())
        chunk = bytearray()
        for r, g, b in pixels[: 320 * 10]:  # first 10 rows only
            chunk += struct.pack("<H", ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
        ser.write(bytes(chunk))
        ser.flush()
        time.sleep(1.0)
        resp2 = ser.read(256)
        if resp2:
            console.print(f"  [green]Post-RGB565 response: {resp2.hex()}[/]")
        else:
            console.print("  [dim]No post-RGB565 response[/]")

    ser.close()
    console.print("\n[bold]Done. Check the LCD![/]")


if __name__ == "__main__":
    main()
