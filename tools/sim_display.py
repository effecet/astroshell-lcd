#!/usr/bin/env python3
"""
Standalone sim — renders a single frame and opens it.
No hardware needed. Good for fast layout iteration.

Usage:
    python tools/sim_display.py
    python tools/sim_display.py --layout gaming --theme matrix
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from astroshell.stats.collector import StatsCollector, StatsSnapshot
from astroshell.renderer.frame import render


def fake_snapshot() -> StatsSnapshot:
    """Fake snapshot for layout testing without real hardware."""
    return StatsSnapshot(
        timestamp=0,
        cpu_percent=72.4,
        cpu_temp_c=68.0,
        cpu_freq_mhz=4850.0,
        ram_used_gb=28.4,
        ram_total_gb=64.0,
        ram_percent=44.0,
        gpu_percent=91.0,
        gpu_temp_c=74.0,
        gpu_vram_used_mb=8192.0,
        gpu_vram_total_mb=12288.0,
        disk_used_gb=420.0,
        disk_total_gb=1000.0,
        disk_percent=42.0,
        net_sent_mbps=1.2,
        net_recv_mbps=8.4,
        uptime_s=86400 * 2 + 3600 * 5 + 60 * 32,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", default="mining", choices=["mining", "gaming", "minimal"])
    parser.add_argument("--theme", default="effece", choices=["effece", "dark_green", "matrix"])
    parser.add_argument("--live", action="store_true", help="Use real stats instead of fake data")
    parser.add_argument("--out", default="screencap.png")
    args = parser.parse_args()

    if args.live:
        collector = StatsCollector()
        snap = collector.collect()
        print("Using live stats")
    else:
        snap = fake_snapshot()
        print("Using fake stats (pass --live for real data)")

    img = render(snap, args.theme, args.layout)
    img.save(args.out)
    print(f"Saved → {args.out}  ({img.size[0]}×{img.size[1]})")

    # Try to open it
    import subprocess

    for viewer in ("eog", "feh", "xdg-open", "display"):
        try:
            subprocess.Popen(
                [viewer, args.out], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            break
        except FileNotFoundError:
            continue
