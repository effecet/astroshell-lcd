"""
astroshell — CLI entrypoint
"""

import typer
from rich.console import Console
from rich.table import Table

cli = typer.Typer(name="astroshell", help="Astroshell LCD stats daemon — crafted by effece 🧉")
console = Console()


@cli.command()
def run(
    layout: str | None = typer.Option(
        None, help="Layout: grid | mining | gaming | minimal  [default: from config.yaml]"
    ),
    theme: str | None = typer.Option(
        None, help="Theme: effece | dark_green | matrix  [default: from config.yaml]"
    ),
    interval: float | None = typer.Option(
        None, help="Refresh interval in seconds  [default: from config.yaml]"
    ),
    config: str = typer.Option("config.yaml", help="Path to config file"),
    sim: bool = typer.Option(False, "--sim", help="Simulate (write screencap.png)"),
):
    """Start the live stats daemon and push frames to the Astroshell LCD."""
    from astroshell.config import apply_overrides, load_config
    from astroshell import daemon

    cfg = apply_overrides(
        load_config(config), layout=layout, theme=theme, refresh_interval=interval
    )
    if sim:
        cfg.display.simulate = True

    daemon.run(cfg)


@cli.command()
def identify():
    """Detect the Astroshell serial port by VID:PID (33c3:7792)."""
    from astroshell.usb.device import VENDOR_ID, PRODUCT_ID
    import serial.tools.list_ports

    console.print(
        f"\n[bold]Scanning for Astroshell LCD (VID=[cyan]{VENDOR_ID:#06x}[/] PID=[cyan]{PRODUCT_ID:#06x}[/])...[/]\n"
    )

    ports = list(serial.tools.list_ports.comports())
    found = False
    for p in ports:
        marker = ""
        if p.vid == VENDOR_ID and p.pid == PRODUCT_ID:
            marker = " [bold green]← ASTROSHELL[/]"
            found = True
        console.print(
            f"  {p.device:15s}  VID={p.vid:#06x}  PID={p.pid:#06x}  {p.description}{marker}"
        )

    if not found:
        console.print("\n[yellow]Astroshell not found. Is it plugged in?[/]")
    else:
        console.print("\n[green]✓ Astroshell detected.[/]")


@cli.command()
def probe():
    """Open /dev/ttyACM0 and log raw bytes — helps discover the serial protocol."""
    from astroshell.usb.device import open_device, close_device
    import time

    console.print("[bold]Probing Astroshell serial port...[/]")
    console.print("Listening for 3 seconds — watching for init bytes from device\n")

    ser = open_device()
    time.sleep(0.5)
    data = ser.read(256)
    if data:
        console.print(f"[green]Received {len(data)} bytes:[/]")
        console.print(f"  hex: {data.hex()}")
        console.print(f"  raw: {data!r}")
    else:
        console.print("[yellow]No bytes received — device is passive (we initiate).[/]")
        console.print(
            "This is expected. Next step: run Wireshark on Windows to capture command bytes."
        )
    close_device(ser)


@cli.command()
def stats():
    """Print a single hardware stats snapshot to the terminal."""
    from astroshell.stats.collector import StatsCollector

    collector = StatsCollector()
    snap = collector.collect()

    t = Table(title="StatsSnapshot", show_header=True, header_style="bold cyan")
    t.add_column("Metric", style="dim")
    t.add_column("Value", style="bold")

    t.add_row("CPU %", f"{snap.cpu_percent:.1f}%")
    t.add_row("CPU temp", f"{snap.cpu_temp_c:.1f}°C")
    t.add_row("CPU freq", f"{snap.cpu_freq_mhz:.0f} MHz")
    t.add_row(
        "RAM", f"{snap.ram_used_gb:.1f} / {snap.ram_total_gb:.0f} GB  ({snap.ram_percent:.0f}%)"
    )
    t.add_row("GPU %", f"{snap.gpu_percent:.1f}%")
    t.add_row("GPU temp", f"{snap.gpu_temp_c:.1f}°C")
    t.add_row(
        "VRAM", f"{snap.gpu_vram_used_mb / 1024:.1f} / {snap.gpu_vram_total_mb / 1024:.1f} GB"
    )
    t.add_row(
        "Disk", f"{snap.disk_used_gb:.1f} / {snap.disk_total_gb:.0f} GB  ({snap.disk_percent:.0f}%)"
    )
    t.add_row("Net ↑", f"{snap.net_sent_mbps:.2f} MB/s")
    t.add_row("Net ↓", f"{snap.net_recv_mbps:.2f} MB/s")
    t.add_row("Uptime", f"{snap.uptime_s / 3600:.1f}h")

    console.print(t)


@cli.command()
def sim(
    layout: str | None = typer.Option(None, help="Layout to preview  [default: from config.yaml]"),
    theme: str | None = typer.Option(None, help="Theme to preview  [default: from config.yaml]"),
    interval: float | None = typer.Option(
        None, help="Refresh interval  [default: from config.yaml]"
    ),
    out: str = typer.Option("screencap.png", help="Output file"),
):
    """Simulate display — renders frames to screencap.png without hardware."""
    from astroshell.config import apply_overrides, load_config
    from astroshell import daemon

    cfg = apply_overrides(load_config(), layout=layout, theme=theme, refresh_interval=interval)
    cfg.display.simulate = True

    console.print(
        f"[bold]SIM MODE[/] — writing [cyan]{out}[/] every {cfg.display.refresh_interval}s"
    )
    console.print("Open screencap.png in an image viewer with auto-refresh to preview live.\n")
    daemon.run(cfg)


@cli.command("list-themes")
def list_themes():
    """Show available themes."""
    from astroshell.renderer.themes import THEMES

    for name, theme in THEMES.items():
        console.print(
            f"  [bold]{name:15s}[/]  bg={theme['bg']}  primary={theme['primary']}  accent={theme['accent']}"
        )


@cli.command("list-layouts")
def list_layouts():
    """Show available layouts."""
    layouts = {
        "grid": "3×3 stats grid — temps, usage, power (320×240)",
        "mining": "CPU temp+%, GPU temp, RAM, uptime — for 24/7 display",
        "gaming": "CPU%, GPU%+VRAM, temps, net I/O",
        "minimal": "3 big bars — CPU, GPU, RAM",
    }
    for name, desc in layouts.items():
        console.print(f"  [bold cyan]{name:10s}[/]  {desc}")


if __name__ == "__main__":
    cli()
