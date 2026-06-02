"""
Configuration model — loads config.yaml into typed dataclasses.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class DisplayConfig:
    port: str = "/dev/ttyACM0"
    baud: int = 115200
    width: int = 320
    height: int = 240
    refresh_interval: float = 1.0
    theme: str = "effece"
    layout: str = "grid"
    simulate: bool = False


@dataclass
class StatsConfig:
    cpu: bool = True
    gpu: bool = True
    memory: bool = True
    disk: bool = True
    network: bool = True
    temps: bool = True


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "astroshell.log"


@dataclass
class AppConfig:
    display: DisplayConfig = field(default_factory=DisplayConfig)
    stats: StatsConfig = field(default_factory=StatsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def load_config(path: str = "config.yaml") -> AppConfig:
    """Load config from YAML file, falling back to defaults."""
    p = Path(path)
    if not p.exists():
        return AppConfig()

    data = yaml.safe_load(p.read_text()) or {}
    cfg = AppConfig()

    if "display" in data:
        for k, v in data["display"].items():
            if hasattr(cfg.display, k):
                setattr(cfg.display, k, v)

    if "stats" in data:
        for k, v in data["stats"].items():
            if hasattr(cfg.stats, k):
                setattr(cfg.stats, k, v)

    if "logging" in data:
        for k, v in data["logging"].items():
            if hasattr(cfg.logging, k):
                setattr(cfg.logging, k, v)

    return cfg
