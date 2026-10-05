# astroshell-lcd

[![ci](https://github.com/effecet/astroshell-lcd/actions/workflows/ci.yml/badge.svg)](https://github.com/effecet/astroshell-lcd/actions/workflows/ci.yml)
[![gitleaks-sweep](https://github.com/effecet/astroshell-lcd/actions/workflows/gitleaks-sweep.yml/badge.svg)](https://github.com/effecet/astroshell-lcd/actions/workflows/gitleaks-sweep.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue)](#license)
[![python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Ubuntu](https://img.shields.io/badge/Ubuntu-Linux-E95420?logo=ubuntu&logoColor=white)](https://ubuntu.com/)
[![systemd](https://img.shields.io/badge/systemd-service-FCC624?logo=linux&logoColor=black)](./astroshell-lcd.service)
[![pyserial](https://img.shields.io/badge/USB-pyserial-5C3EE8)](https://pyserial.readthedocs.io/)
[![Pillow](https://img.shields.io/badge/render-Pillow-11557C)](https://pillow.readthedocs.io/)
[![LCD](https://img.shields.io/badge/LCD-ST7789S%20320%C3%97240-f97316)](#hardware)
[![GitHub](https://img.shields.io/badge/hosted%20on-GitHub-181717?logo=github)](https://github.com/effecet/astroshell-lcd)

> Push real-time hardware stats to the Jungle Leopard Astroshell AIO LCD screen on Ubuntu Linux.

```
# crafted by effece
github.com/effecet/astroshell-lcd
```

## Overview

```mermaid
graph LR
    HW["Hardware Sensors<br/>CPU, GPU, RAM, Voltages"]
    SNAP["StatsSnapshot"]
    RENDER["Pillow Renderer<br/>320x240 frame"]
    SERIAL["pyserial<br/>55 AA protocol"]
    LCD["Astroshell LCD<br/>33c3:7792"]

    HW --> SNAP --> RENDER --> SERIAL --> LCD

    style HW fill:#0d0d0d,stroke:#22d3ee,color:#e5e5e5
    style SNAP fill:#0d0d0d,stroke:#525252,color:#e5e5e5
    style RENDER fill:#0d0d0d,stroke:#f97316,color:#e5e5e5
    style SERIAL fill:#0d0d0d,stroke:#22d3ee,color:#e5e5e5
    style LCD fill:#f97316,stroke:#f97316,color:#0d0d0d
```

See [docs](docs/) for detailed diagrams: [architecture](docs/architecture.md), [protocol discovery](docs/protocol-discovery.md), [data pipeline](docs/data-pipeline.md).

## Hardware

| Component | Detail |
|---|---|
| Device | HONGTAI MONITOR (`33c3:7792`) |
| Transport | CDC ACM serial → `/dev/ttyACM0` |
| Screen | 320×240 px, 2.8" IPS, ST7789S |
| Protocol | Reverse-engineered from the Jungle Leopard app (`55 AA` magic) |
| Baud | 115200 / 8N1 |

## Status

| Layer | Status |
|---|---|
| USB device detection | ✅ confirmed |
| Serial transport | ✅ CDC ACM, pyserial |
| Protocol | ✅ fully mapped — `55 AA` + len + cmd + checksum |
| Device info | ✅ JSON via cmd 6 (320x240, ST7789S, v3.1) |
| Stats collection | ✅ CPU, GPU, RAM, disk, network, power, voltages |
| Frame rendering | ✅ 4 layouts × 3 themes, Pillow-based |
| Frame push to LCD | ✅ raw JPEG streaming after cmd 17 (startLive) |
| Systemd service | ✅ `astroshell-lcd.service` auto-starts on boot |

## Layouts

| Layout | Use case |
|---|---|
| `grid` | **Default** — 3×3 stats grid: temps, usage, power+voltages |
| `mining` | CPU/GPU temps, RAM, uptime — 24/7 display |
| `gaming` | Large CPU/GPU %, temps, VRAM bars |
| `minimal` | 3 big bars — CPU, GPU, RAM |

## Themes

- **effece** — dark bg, orange `#f97316`, cyan `#22d3ee`
- **dark_green** — green on dark
- **matrix** — classic green-on-black

## Quick Start

Needs Python 3.11+ (Ubuntu 24.04 ships 3.12; on 22.04 install a newer Python first).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Grant serial port access (once, then log out and back in) — no root needed after this
sudo usermod -aG dialout $USER

# Preview layouts (no hardware needed)
python tools/sim_display.py --layout grid
python tools/sim_display.py --layout mining
python tools/sim_display.py --layout gaming
python tools/sim_display.py --layout minimal

# Run live on LCD
python -m astroshell.main run --layout grid

# Install as systemd service (auto-start on boot)
# Note: CPU power comes from the RAPL energy counter, which many kernels make
# root-readable only; if so, the power tile shows 0 W when not running as root.
# Edit User=, WorkingDirectory= and ExecStart= in the unit file to match your
# username and install path first — the shipped values are placeholders.
sudo cp astroshell-lcd.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now astroshell-lcd
```

## Project Structure

```
astroshell-lcd/
├── astroshell/
│   ├── main.py              ← typer CLI entrypoint
│   ├── daemon.py            ← collect → render → push loop + threaded keepalive
│   ├── config.py            ← pydantic config from config.yaml
│   ├── logger.py            ← rich logging
│   ├── stats/
│   │   └── collector.py     ← hardware stats → StatsSnapshot (RAPL, pynvml, hwmon)
│   ├── renderer/
│   │   ├── frame.py         ← PIL image composer (grid, mining, gaming, minimal)
│   │   ├── themes.py        ← color palettes
│   │   └── widgets.py       ← bars, text, dividers
│   └── usb/
│       ├── device.py        ← serial port open/close + auto-detect
│       └── protocol.py      ← serial protocol: build_command, init, push, keepalive
├── tools/                   ← dev/debug scripts (not needed for normal use)
│   ├── show_info.py         ← display device info on LCD
│   ├── sim_display.py       ← render to PNG (no hardware)
│   ├── push_frame.py        ← push a single frame to the device
│   └── probe_*.py           ← 8 protocol-reverse-engineering probes
│                              (real, raw, handshake, protocol, image,
│                               v2, h264, h264_serial)
├── astroshell_portable.py   ← single-file portable version
├── astroshell-lcd.service   ← systemd unit file
├── config.yaml
└── pyproject.toml
```

## Protocol

Packet format:
```
55 AA [len_lo len_hi] [cmd] [payload...] [checksum_lo checksum_hi]
```
- **Length** = payload_size + 7
- **Checksum** = sum of all preceding bytes & 0xFFFF (LE)

Commands:
| Cmd | Action |
|-----|--------|
| 6   | getDeviceInfo (returns JSON) |
| 17  | startLive (begin JPEG streaming) |
| 1   | restart device |
| 3   | setBrightness (payload: [0-100]) |
| 33  | close (fw >= 3.1) |

Image streaming:
1. Send `FF D9 FF D9` (stop current display), then wait ~200 ms
2. `getDeviceInfo` (cmd 6) — returns device JSON
3. `startLive` (cmd 17)
4. Stream raw JPEG frames (no framing, just bytes)
5. Re-send cmd 17 every ~0.8s as keepalive (dedicated thread, device times out at ~1.5s)

Reverse-engineered for interoperability from the vendor's `Jungle Leopard Display Setup 1.0.42`
(Electron app, published by Guangzhou Haiji Intelligent Technology Co., Ltd), so the screen
can be driven from Linux.

## Tech Stack

| Layer | Library |
|---|---|
| CLI | typer |
| Terminal UI | rich |
| Serial | pyserial |
| Rendering | Pillow |
| Stats | psutil, pynvml |
| Config | pydantic-settings, pyyaml |

## License

MIT
