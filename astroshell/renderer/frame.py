"""
Frame renderer — composes a PIL Image from a StatsSnapshot.

The grid layout renders at 320×240; the others render at 320×320 and are
resized to the panel's 320×240 when encoded for push.
"""

from PIL import Image, ImageDraw
from astroshell.stats.collector import StatsSnapshot
from astroshell.renderer.themes import get_theme, rgb
from astroshell.renderer.widgets import draw_bar, draw_text, draw_divider, draw_label_value


def render(snap: StatsSnapshot, theme_name: str = "effece", layout: str = "grid") -> Image.Image:
    theme = get_theme(theme_name)
    if layout == "grid":
        size = (320, 240)
    else:
        size = (320, 320)
    img = Image.new("RGB", size, rgb(theme, "bg"))
    draw = ImageDraw.Draw(img)

    if layout == "grid":
        _layout_grid(draw, snap, theme)
    elif layout == "mining":
        _layout_mining(draw, snap, theme)
    elif layout == "gaming":
        _layout_gaming(draw, snap, theme)
    elif layout == "minimal":
        _layout_minimal(draw, snap, theme)
    else:
        _layout_grid(draw, snap, theme)

    return img


def _layout_grid(draw: ImageDraw.ImageDraw, snap: StatsSnapshot, theme) -> None:
    """
    3x3 stats grid for 320×240.
    Row 1: CPU Temp | GPU Temp | RAM Used
    Row 2: CPU Usage | GPU Usage | RAM Pct
    Row 3: CPU Power | GPU Power | CPU Freq
    Footer: # crafted by effece 🧉
    """
    W, H = 320, 240
    COLS, ROWS = 3, 3
    PAD_L = 6  # left margin — LCD clips leftmost pixels
    FOOTER_H = 20
    GRID_H = H - FOOTER_H  # 220px for grid
    GRID_W = W - PAD_L
    CELL_W = GRID_W // COLS  # ~104px
    CELL_H = GRID_H // ROWS  # 73px

    # Grid data: (label, value_str, color_key, sub_value) per cell
    cpu_freq_ghz = snap.cpu_freq_mhz / 1000 if snap.cpu_freq_mhz else 0
    cells = [
        # Row 1 — Temperatures
        ("CPU TEMP", f"{snap.cpu_temp_c:.0f}°C", "primary", ""),
        ("GPU TEMP", f"{snap.gpu_temp_c:.0f}°C", "accent", ""),
        ("RAM USED", f"{snap.ram_used_gb:.1f} GB", "text", ""),
        # Row 2 — Usage
        ("CPU USAGE", f"{snap.cpu_percent:.0f}%", "primary", ""),
        ("GPU USAGE", f"{snap.gpu_percent:.0f}%", "accent", ""),
        ("RAM PCT", f"{snap.ram_percent:.0f}%", "text", ""),
        # Row 3 — Power / Freq + voltages
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

        # Label (yellow, small, top of cell)
        draw_text(draw, cx + 6, cy + 6, label, theme, size=10, color_key="label")

        # Value (large)
        draw_text(draw, cx + 6, cy + 24, value, theme, size=20, color_key=color_key)

        # Sub-value (green, below main value)
        if sub:
            draw_text(draw, cx + 6, cy + 50, sub, theme, size=11, color_key="info")

    # Grid lines — vertical
    for col in range(1, COLS):
        x = PAD_L + col * CELL_W
        draw.line([(x, 0), (x, GRID_H)], fill=line_color, width=1)

    # Grid lines — horizontal
    for row in range(1, ROWS):
        y = row * CELL_H
        draw.line([(PAD_L, y), (W, y)], fill=line_color, width=1)

    # Divider above footer
    draw.line([(PAD_L, GRID_H), (W, GRID_H)], fill=line_color, width=1)

    # Footer
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


def _layout_mining(draw: ImageDraw.ImageDraw, snap: StatsSnapshot, theme) -> None:
    """
    Mining layout — optimized for 24/7 display.
    Shows CPU, GPU, RAM, temps, uptime.
    """
    y = 8

    # Title bar
    draw_text(draw, 8, y, "astroshell-lcd", theme, size=11, color_key="muted")
    draw_text(draw, 220, y, "⛏ mining", theme, size=11, color_key="accent")
    y += 20
    draw_divider(draw, y, theme)
    y += 8

    # CPU
    draw_text(draw, 8, y, "CPU", theme, size=11, color_key="muted")
    draw_text(draw, 240, y, f"{snap.cpu_temp_c:.0f}°C", theme, size=11, color_key="accent")
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
        label="",
        value_str=f"{snap.cpu_percent:.1f}%",
    )
    y += 26

    # GPU
    draw_text(draw, 8, y, "GPU  RTX 5070", theme, size=11, color_key="muted")
    draw_text(draw, 240, y, f"{snap.gpu_temp_c:.0f}°C", theme, size=11, color_key="accent")
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

    # VRAM
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

    # RAM
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

    # CPU freq + uptime row
    hours = int(snap.uptime_s // 3600)
    minutes = int((snap.uptime_s % 3600) // 60)
    draw_text(draw, 8, y, f"{snap.cpu_freq_mhz / 1000:.2f} GHz", theme, size=12, color_key="text")
    draw_text(draw, 180, y, f"up {hours}h {minutes:02d}m", theme, size=12, color_key="muted")
    y += 20

    # Network
    draw_text(
        draw,
        8,
        y,
        f"↑ {snap.net_sent_mbps:.1f} MB/s   ↓ {snap.net_recv_mbps:.1f} MB/s",
        theme,
        size=11,
        color_key="muted",
    )
    y += 18

    draw_divider(draw, y, theme)
    y += 6

    # Footer
    draw_text(draw, 8, y, "# crafted by effece 🧉", theme, size=10, color_key="muted")


def _layout_gaming(draw: ImageDraw.ImageDraw, snap: StatsSnapshot, theme) -> None:
    """Gaming layout — larger CPU/GPU numbers, FPS-focused."""
    y = 8
    draw_text(draw, 8, y, "astroshell-lcd", theme, size=11, color_key="muted")
    draw_text(draw, 220, y, "🎮 gaming", theme, size=11, color_key="primary")
    y += 20
    draw_divider(draw, y, theme)
    y += 12

    draw_label_value(draw, 8, y, "CPU", f"{snap.cpu_percent:.0f}%", theme)
    draw_label_value(draw, 170, y, "GPU", f"{snap.gpu_percent:.0f}%", theme)
    y += 44

    draw_label_value(draw, 8, y, "CPU°", f"{snap.cpu_temp_c:.0f}°C", theme, value_size=18)
    draw_label_value(draw, 170, y, "GPU°", f"{snap.gpu_temp_c:.0f}°C", theme, value_size=18)
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

    draw_text(draw, 8, y, "# crafted by effece 🧉", theme, size=10, color_key="muted")


def _layout_minimal(draw: ImageDraw.ImageDraw, snap: StatsSnapshot, theme) -> None:
    """Minimal — 3 big bars, nothing else."""
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
        f"CPU {snap.cpu_temp_c:.0f}°C   GPU {snap.gpu_temp_c:.0f}°C",
        theme,
        size=14,
        color_key="accent",
    )
