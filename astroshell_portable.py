"""
Astroshell LCD — Portable single-file version for Windows.
Pushes real-time hardware stats to the Astroshell AIO LCD screen.

Install deps:
    pip install pyserial pillow psutil pynvml

Usage:
    python astroshell_portable.py                     # auto-detect COM port, grid layout
    python astroshell_portable.py --layout mining     # mining layout
    python astroshell_portable.py --port COM3         # manual port
    python astroshell_portable.py --sim               # render to PNG, no hardware
    python astroshell_portable.py --theme matrix      # matrix theme
    python astroshell_portable.py --brightness 80     # set brightness (0-100)

# crafted by effece 🧉
"""

from __future__ import annotations

import argparse
import io
import json
import os
import platform
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil
import serial
import serial.tools.list_ports
from PIL import Image, ImageDraw, ImageFont

# ── Protocol constants ────────────────────────────────────────────────────────

WIDTH = 320
HEIGHT = 240
VENDOR_ID = 0x33C3
PRODUCT_ID = 0x7792
CHUNK_SIZE = 512
STOP_MARKER = b"\xff\xd9\xff\xd9"

CMD_RESTART = 1
CMD_SET_BRIGHTNESS = 3
CMD_GET_INFO = 6
CMD_START_LIVE = 17
CMD_CLOSE = 33


# ── Protocol ─────────────────────────────────────────────────────────────────


def build_command(cmd: int, payload: bytes = b"") -> bytes:
    magic = bytes([0x55, 0xAA])
    length = len(payload) + 7
    packet = magic + bytes([length & 0xFF, (length >> 8) & 0xFF, cmd]) + payload
    checksum = sum(packet) & 0xFFFF
    return packet + bytes([checksum & 0xFF, (checksum >> 8) & 0xFF])


def parse_response(data: bytes) -> dict | None:
    if len(data) < 7 or data[0:2] != b"\x55\xaa":
        return None
    try:
        return json.loads(data[5:-2].decode("utf-8"))
    except Exception:
        return None


def _write_chunked(ser: serial.Serial, data: bytes) -> None:
    for i in range(0, len(data), CHUNK_SIZE):
        ser.write(data[i : i + CHUNK_SIZE])
    ser.flush()


def _read_response(ser: serial.Serial, timeout: float = 1.0) -> bytes:
    ser.timeout = timeout
    header = ser.read(5)
    if len(header) < 5:
        return b""
    length = header[2] | (header[3] << 8)
    remaining = length - 5
    if remaining > 0:
        body = ser.read(remaining)
        return header + body
    return header


# ── Device ───────────────────────────────────────────────────────────────────


def find_port() -> str | None:
    for port in serial.tools.list_ports.comports():
        if port.vid == VENDOR_ID and port.pid == PRODUCT_ID:
            print(f"[info] Auto-detected Astroshell at {port.device}")
            return port.device
    return None


def open_device(port: str | None = None, baud: int = 115200) -> serial.Serial:
    target = port or find_port()
    if not target:
        print("[error] Astroshell LCD not found. Use --port COMx to specify manually.")
        sys.exit(1)
    print(f"[info] Opening {target} @ {baud} baud")
    ser = serial.Serial(
        port=target,
        baudrate=baud,
        timeout=1,
        write_timeout=5,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
    )
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return ser


def init_display(ser: serial.Serial) -> dict | None:
    ser.write(STOP_MARKER)
    ser.flush()
    time.sleep(0.2)
    _write_chunked(ser, build_command(CMD_GET_INFO))
    raw = _read_response(ser)
    info = parse_response(raw)
    if info:
        print(f"[info] Device: {info}")
    _write_chunked(ser, build_command(CMD_START_LIVE))
    return info


def set_brightness(ser: serial.Serial, level: int) -> None:
    level = max(0, min(100, level))
    _write_chunked(ser, build_command(CMD_SET_BRIGHTNESS, bytes([level])))


def push_frame(ser: serial.Serial, image: Image.Image) -> None:
    img = image.convert("RGB").resize((WIDTH, HEIGHT), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    ser.write(buf.getvalue())
    ser.flush()


# ── Theme ────────────────────────────────────────────────────────────────────

THEMES = {
    "effece": {
        "bg": "#0d0d0d",
        "primary": "#f97316",
        "accent": "#22d3ee",
        "text": "#e5e5e5",
        "muted": "#525252",
    },
    "dark_green": {
        "bg": "#0a0a0a",
        "primary": "#22c55e",
        "accent": "#4ade80",
        "text": "#d1fae5",
        "muted": "#374151",
    },
    "matrix": {
        "bg": "#000000",
        "primary": "#00ff41",
        "accent": "#008f11",
        "text": "#00ff41",
        "muted": "#003b00",
    },
}


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb(theme: dict, key: str) -> tuple[int, int, int]:
    return _hex(theme[key])


# ── Font ─────────────────────────────────────────────────────────────────────


def _font(size: int) -> ImageFont.ImageFont:
    # Try JetBrains Mono on both platforms
    candidates = []
    if platform.system() == "Windows":
        candidates = [
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts\JetBrainsMono-Regular.ttf"),
            r"C:\Windows\Fonts\JetBrainsMono-Regular.ttf",
            r"C:\Windows\Fonts\consola.ttf",
            r"C:\Windows\Fonts\cour.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ── Widgets ──────────────────────────────────────────────────────────────────


def draw_bar(
    draw,
    x,
    y,
    width,
    height,
    percent,
    theme,
    color_key="primary",
    bg_key="muted",
    label="",
    value_str="",
):
    bg = rgb(theme, bg_key)
    fg = rgb(theme, color_key)
    txt = rgb(theme, "text")
    draw.rectangle([x, y, x + width, y + height], fill=bg)
    fill_w = int(width * max(0.0, min(1.0, percent / 100.0)))
    if fill_w > 0:
        draw.rectangle([x, y, x + fill_w, y + height], fill=fg)
    if label:
        fnt = _font(max(8, height - 4))
        draw.text((x + 4, y + 1), label, font=fnt, fill=txt)
    if value_str:
        fnt = _font(max(8, height - 4))
        draw.text((x + width - 60, y + 1), value_str, font=fnt, fill=txt)


def draw_text(draw, x, y, text, theme, size=14, color_key="text"):
    fnt = _font(size)
    draw.text((x, y), text, font=fnt, fill=rgb(theme, color_key))


def draw_divider(draw, y, theme, color_key="muted"):
    draw.line([(8, y), (312, y)], fill=rgb(theme, color_key), width=1)


def draw_label_value(draw, x, y, label, value, theme, label_size=11, value_size=18):
    draw_text(draw, x, y, label, theme, size=label_size, color_key="muted")
    draw_text(draw, x, y + label_size + 2, value, theme, size=value_size, color_key="primary")


# ── Stats collector ──────────────────────────────────────────────────────────


@dataclass
class StatsSnapshot:
    cpu_percent: float = 0.0
    cpu_temp_c: float = 0.0
    cpu_freq_mhz: float = 0.0
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    ram_percent: float = 0.0
    cpu_power_w: float = 0.0
    gpu_percent: float = 0.0
    gpu_temp_c: float = 0.0
    gpu_vram_used_mb: float = 0.0
    gpu_vram_total_mb: float = 0.0
    gpu_power_w: float = 0.0
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    disk_percent: float = 0.0
    net_sent_mbps: float = 0.0
    net_recv_mbps: float = 0.0
    uptime_s: float = 0.0
    soc_vddgfx_v: float = 0.0
    soc_vddnb_v: float = 0.0


class StatsCollector:
    def __init__(self):
        self._last_net_sent = 0
        self._last_net_recv = 0
        self._last_net_time = time.time()
        self._gpu_available = False
        try:
            import pynvml

            pynvml.nvmlInit()
            self._gpu_available = True
        except Exception:
            pass
        # Prime cpu_percent baseline
        psutil.cpu_percent(interval=None)

    def collect(self) -> StatsSnapshot:
        snap = StatsSnapshot()

        # CPU
        snap.cpu_percent = psutil.cpu_percent(interval=None)
        freq = psutil.cpu_freq()
        snap.cpu_freq_mhz = freq.current if freq else 0.0
        snap.cpu_temp_c = self._read_cpu_temp()

        # RAM
        mem = psutil.virtual_memory()
        snap.ram_total_gb = mem.total / 1e9
        snap.ram_used_gb = mem.used / 1e9
        snap.ram_percent = mem.percent

        # GPU
        if self._gpu_available:
            (
                snap.gpu_percent,
                snap.gpu_temp_c,
                snap.gpu_vram_used_mb,
                snap.gpu_vram_total_mb,
                snap.gpu_power_w,
            ) = self._read_gpu()

        # Disk
        disk_path = "C:\\" if platform.system() == "Windows" else "/"
        disk = psutil.disk_usage(disk_path)
        snap.disk_total_gb = disk.total / 1e9
        snap.disk_used_gb = disk.used / 1e9
        snap.disk_percent = disk.percent

        # Network
        snap.net_sent_mbps, snap.net_recv_mbps = self._read_net()

        # Uptime
        snap.uptime_s = time.time() - psutil.boot_time()

        return snap

    def _read_cpu_temp(self) -> float:
        if platform.system() == "Windows":
            # psutil.sensors_temperatures() not available on Windows
            # Try WMI via pynvml or return 0
            return 0.0
        try:
            temps = psutil.sensors_temperatures()
            for name in ("k10temp", "zenpower", "coretemp", "cpu_thermal"):
                if name in temps:
                    entries = temps[name]
                    for e in entries:
                        if e.label in ("Tctl", "Tdie", "Package id 0"):
                            return e.current
                    return entries[0].current
        except Exception:
            pass
        return 0.0

    def _read_gpu(self) -> tuple[float, float, float, float, float]:
        try:
            import pynvml

            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
            return float(util.gpu), float(temp), mem.used / 1e6, mem.total / 1e6, power
        except Exception:
            return 0.0, 0.0, 0.0, 0.0, 0.0

    def _read_net(self) -> tuple[float, float]:
        now = time.time()
        net = psutil.net_io_counters()
        dt = max(now - self._last_net_time, 0.001)
        sent = (net.bytes_sent - self._last_net_sent) / dt / 1e6
        recv = (net.bytes_recv - self._last_net_recv) / dt / 1e6
        self._last_net_sent = net.bytes_sent
        self._last_net_recv = net.bytes_recv
        self._last_net_time = now
        return max(0.0, sent), max(0.0, recv)


# ── Layouts ──────────────────────────────────────────────────────────────────


def _layout_grid(draw, snap, theme):
    W, H = 320, 240
    COLS, ROWS = 3, 3
    PAD_L = 6
    FOOTER_H = 20
    GRID_H = H - FOOTER_H
    GRID_W = W - PAD_L
    CELL_W = GRID_W // COLS
    CELL_H = GRID_H // ROWS

    cpu_freq_ghz = snap.cpu_freq_mhz / 1000 if snap.cpu_freq_mhz else 0
    cells = [
        ("CPU TEMP", f"{snap.cpu_temp_c:.0f}\u00b0C", "primary", ""),
        ("GPU TEMP", f"{snap.gpu_temp_c:.0f}\u00b0C", "accent", ""),
        ("RAM USED", f"{snap.ram_used_gb:.1f} GB", "text", ""),
        ("CPU USAGE", f"{snap.cpu_percent:.0f}%", "primary", ""),
        ("GPU USAGE", f"{snap.gpu_percent:.0f}%", "accent", ""),
        ("RAM PCT", f"{snap.ram_percent:.0f}%", "text", ""),
        ("CPU POWER", f"{snap.cpu_power_w:.0f}W", "primary", f"{snap.soc_vddgfx_v:.2f}V"),
        ("GPU POWER", f"{snap.gpu_power_w:.0f}W", "accent", f"{snap.soc_vddnb_v:.2f}V"),
        ("CPU FREQ", f"{cpu_freq_ghz:.2f} GHz", "text", ""),
    ]

    line_color = rgb(theme, "muted")
    for idx, (label, value, color_key, sub) in enumerate(cells):
        row = idx // COLS
        col = idx % COLS
        cx = PAD_L + col * CELL_W
        cy = row * CELL_H
        draw_text(draw, cx + 6, cy + 6, label, theme, size=10, color_key="muted")
        draw_text(draw, cx + 6, cy + 24, value, theme, size=20, color_key=color_key)
        if sub:
            draw_text(draw, cx + 6, cy + 50, sub, theme, size=11, color_key="muted")

    for col in range(1, COLS):
        x = PAD_L + col * CELL_W
        draw.line([(x, 0), (x, GRID_H)], fill=line_color, width=1)
    for row in range(1, ROWS):
        y = row * CELL_H
        draw.line([(PAD_L, y), (W, y)], fill=line_color, width=1)
    draw.line([(PAD_L, GRID_H), (W, GRID_H)], fill=line_color, width=1)

    draw_text(draw, PAD_L + 8, GRID_H + 4, "# crafted by effece", theme, size=10, color_key="muted")
    draw_text(
        draw,
        W - 148,
        GRID_H + 4,
        "github.com/effecet/astroshell-lcd",
        theme,
        size=9,
        color_key="muted",
    )


def _layout_mining(draw, snap, theme):
    y = 8
    draw_text(draw, 8, y, "astroshell-lcd", theme, size=11, color_key="muted")
    draw_text(draw, 220, y, "mining", theme, size=11, color_key="accent")
    y += 20
    draw_divider(draw, y, theme)
    y += 8
    draw_text(draw, 8, y, "CPU", theme, size=11, color_key="muted")
    draw_text(draw, 240, y, f"{snap.cpu_temp_c:.0f}\u00b0C", theme, size=11, color_key="accent")
    y += 14
    draw_bar(
        draw,
        8,
        y,
        304,
        18,
        snap.cpu_percent,
        theme,
        color_key="primary",
        value_str=f"{snap.cpu_percent:.1f}%",
    )
    y += 26
    draw_text(draw, 8, y, "GPU  RTX 5070", theme, size=11, color_key="muted")
    draw_text(draw, 240, y, f"{snap.gpu_temp_c:.0f}\u00b0C", theme, size=11, color_key="accent")
    y += 14
    draw_bar(
        draw,
        8,
        y,
        304,
        18,
        snap.gpu_percent,
        theme,
        color_key="accent",
        value_str=f"{snap.gpu_percent:.1f}%",
    )
    y += 26
    vram_pct = (
        (snap.gpu_vram_used_mb / snap.gpu_vram_total_mb * 100) if snap.gpu_vram_total_mb else 0
    )
    draw_text(draw, 8, y, "VRAM", theme, size=11, color_key="muted")
    draw_text(
        draw,
        200,
        y,
        f"{snap.gpu_vram_used_mb / 1024:.1f}/{snap.gpu_vram_total_mb / 1024:.1f} GB",
        theme,
        size=11,
        color_key="text",
    )
    y += 14
    draw_bar(draw, 8, y, 304, 14, vram_pct, theme, color_key="accent")
    y += 22
    draw_text(draw, 8, y, "RAM", theme, size=11, color_key="muted")
    draw_text(
        draw,
        200,
        y,
        f"{snap.ram_used_gb:.1f}/{snap.ram_total_gb:.0f} GB",
        theme,
        size=11,
        color_key="text",
    )
    y += 14
    draw_bar(draw, 8, y, 304, 14, snap.ram_percent, theme, color_key="primary")
    y += 22
    draw_divider(draw, y, theme)
    y += 8
    hours = int(snap.uptime_s // 3600)
    minutes = int((snap.uptime_s % 3600) // 60)
    draw_text(draw, 8, y, f"{snap.cpu_freq_mhz / 1000:.2f} GHz", theme, size=12, color_key="text")
    draw_text(draw, 180, y, f"up {hours}h {minutes:02d}m", theme, size=12, color_key="muted")
    y += 20
    draw_text(
        draw,
        8,
        y,
        f"up {snap.net_sent_mbps:.1f} MB/s   dn {snap.net_recv_mbps:.1f} MB/s",
        theme,
        size=11,
        color_key="muted",
    )
    y += 18
    draw_divider(draw, y, theme)
    y += 6
    draw_text(draw, 8, y, "# crafted by effece", theme, size=10, color_key="muted")


def _layout_gaming(draw, snap, theme):
    y = 8
    draw_text(draw, 8, y, "astroshell-lcd", theme, size=11, color_key="muted")
    draw_text(draw, 220, y, "gaming", theme, size=11, color_key="primary")
    y += 20
    draw_divider(draw, y, theme)
    y += 12
    draw_label_value(draw, 8, y, "CPU", f"{snap.cpu_percent:.0f}%", theme)
    draw_label_value(draw, 170, y, "GPU", f"{snap.gpu_percent:.0f}%", theme)
    y += 44
    draw_label_value(draw, 8, y, "CPU\u00b0", f"{snap.cpu_temp_c:.0f}\u00b0C", theme, value_size=18)
    draw_label_value(
        draw, 170, y, "GPU\u00b0", f"{snap.gpu_temp_c:.0f}\u00b0C", theme, value_size=18
    )
    y += 44
    draw_divider(draw, y, theme)
    y += 10
    draw_bar(
        draw,
        8,
        y,
        304,
        16,
        snap.ram_percent,
        theme,
        label="RAM",
        value_str=f"{snap.ram_used_gb:.1f}/{snap.ram_total_gb:.0f}GB",
    )
    y += 28
    vram_pct = (
        (snap.gpu_vram_used_mb / snap.gpu_vram_total_mb * 100) if snap.gpu_vram_total_mb else 0
    )
    draw_bar(
        draw,
        8,
        y,
        304,
        16,
        vram_pct,
        theme,
        color_key="accent",
        label="VRAM",
        value_str=f"{snap.gpu_vram_used_mb / 1024:.1f}GB",
    )
    y += 36
    draw_text(draw, 8, y, "# crafted by effece", theme, size=10, color_key="muted")


def _layout_minimal(draw, snap, theme):
    y = 20
    draw_bar(
        draw,
        8,
        y,
        304,
        28,
        snap.cpu_percent,
        theme,
        label="CPU",
        value_str=f"{snap.cpu_percent:.0f}%",
    )
    y += 48
    draw_bar(
        draw,
        8,
        y,
        304,
        28,
        snap.gpu_percent,
        theme,
        color_key="accent",
        label="GPU",
        value_str=f"{snap.gpu_percent:.0f}%",
    )
    y += 48
    draw_bar(
        draw,
        8,
        y,
        304,
        28,
        snap.ram_percent,
        theme,
        label="RAM",
        value_str=f"{snap.ram_percent:.0f}%",
    )
    y += 60
    draw_text(
        draw,
        8,
        y,
        f"CPU {snap.cpu_temp_c:.0f}\u00b0C   GPU {snap.gpu_temp_c:.0f}\u00b0C",
        theme,
        size=14,
        color_key="accent",
    )


LAYOUTS = {
    "grid": _layout_grid,
    "mining": _layout_mining,
    "gaming": _layout_gaming,
    "minimal": _layout_minimal,
}


def render(snap, theme_name="effece", layout="grid") -> Image.Image:
    theme = THEMES.get(theme_name, THEMES["effece"])
    size = (320, 240) if layout == "grid" else (320, 320)
    img = Image.new("RGB", size, rgb(theme, "bg"))
    draw = ImageDraw.Draw(img)
    LAYOUTS.get(layout, _layout_grid)(draw, snap, theme)
    return img


# ── Main loop ────────────────────────────────────────────────────────────────

_running = True


def _handle_signal(sig, frame):
    global _running
    print("\n[info] Shutting down...")
    _running = False


def main():
    parser = argparse.ArgumentParser(description="Astroshell LCD — portable stats display")
    parser.add_argument("--port", default=None, help="Serial port (e.g. COM3, /dev/ttyACM0)")
    parser.add_argument("--layout", default="grid", choices=["grid", "mining", "gaming", "minimal"])
    parser.add_argument("--theme", default="effece", choices=list(THEMES.keys()))
    parser.add_argument("--interval", type=float, default=1.0, help="Refresh interval in seconds")
    parser.add_argument("--brightness", type=int, default=None, help="Set brightness (0-100)")
    parser.add_argument(
        "--sim", action="store_true", help="Simulate — render to screencap.png, no hardware"
    )
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_signal)
    if platform.system() != "Windows":
        signal.signal(signal.SIGTERM, _handle_signal)

    collector = StatsCollector()
    time.sleep(0.5)  # let cpu_percent baseline settle

    if args.sim:
        print(f"[info] SIM MODE — layout={args.layout} theme={args.theme}")
        out = Path("screencap.png")
        while _running:
            snap = collector.collect()
            img = render(snap, args.theme, args.layout)
            img.save(out)
            print(f"[info] Frame saved -> {out}")
            time.sleep(args.interval)
        return

    ser = open_device(args.port)
    init_display(ser)

    if args.brightness is not None:
        set_brightness(ser, args.brightness)
        print(f"[info] Brightness set to {args.brightness}")

    print(f"[info] Running — layout={args.layout} theme={args.theme} interval={args.interval}s")
    print("[info] Press Ctrl+C to stop")

    try:
        while _running:
            t0 = time.monotonic()
            snap = collector.collect()
            img = render(snap, args.theme, args.layout)
            push_frame(ser, img)
            elapsed = time.monotonic() - t0
            sleep_t = max(0.0, args.interval - elapsed)
            time.sleep(sleep_t)
    finally:
        ser.close()
        print("[info] Serial port closed")


if __name__ == "__main__":
    main()
