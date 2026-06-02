"""
Main daemon loop: collect stats → render frame → push to LCD.
"""

import time
import signal
import threading
from pathlib import Path

from astroshell.config import AppConfig
from astroshell.logger import log
from astroshell.stats.collector import StatsCollector
from astroshell.renderer.frame import render
from astroshell.usb.device import open_device, close_device
from astroshell.usb.protocol import init_display, push_frame, start_live, stop_display


_running = True


def _handle_signal(sig, frame):
    global _running
    log.info("Shutdown signal received")
    _running = False


def _keepalive_loop(ser, lock):
    """Send startLive every 0.8s in a dedicated thread so the device never times out."""
    while _running:
        try:
            with lock:
                start_live(ser)
        except Exception:
            pass
        time.sleep(0.8)


def run(config: AppConfig) -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    collector = StatsCollector(config.stats)

    if config.display.simulate:
        _run_sim(config, collector)
    else:
        _run_live(config, collector)


def _run_live(config: AppConfig, collector: StatsCollector) -> None:
    ser = open_device(config.display.port, config.display.baud)

    # Init sequence: stop → getDeviceInfo → startLive
    info = init_display(ser)
    if info and "data" in info:
        w = info["data"].get("width", config.display.width)
        h = info["data"].get("height", config.display.height)
        log.info(f"LCD: {w}×{h} — {info['data'].get('model', 'unknown')}")

    log.info(
        f"Daemon started — layout={config.display.layout} "
        f"theme={config.display.theme} "
        f"interval={config.display.refresh_interval}s"
    )

    # Serial lock shared between frame push and keepalive thread
    serial_lock = threading.Lock()

    # Keepalive thread — prevents Jungle Leopard splash screen
    ka_thread = threading.Thread(target=_keepalive_loop, args=(ser, serial_lock), daemon=True)
    ka_thread.start()

    try:
        while _running:
            t0 = time.monotonic()
            snap = collector.collect()
            img = render(snap, config.display.theme, config.display.layout)
            with serial_lock:
                push_frame(ser, img)

            elapsed = time.monotonic() - t0
            sleep_t = max(0.0, config.display.refresh_interval - elapsed)
            log.debug(f"Frame pushed in {elapsed:.2f}s — sleeping {sleep_t:.2f}s")
            time.sleep(sleep_t)
    finally:
        stop_display(ser)
        close_device(ser)
        log.info("Daemon stopped")


def _run_sim(config: AppConfig, collector: StatsCollector) -> None:
    out = Path("screencap.png")
    log.info(f"SIM MODE — writing frames to {out} every {config.display.refresh_interval}s")
    log.info("Press Ctrl+C to stop")
    while _running:
        snap = collector.collect()
        img = render(snap, config.display.theme, config.display.layout)
        img.save(out)
        log.info(f"Frame saved → {out}")
        time.sleep(config.display.refresh_interval)
