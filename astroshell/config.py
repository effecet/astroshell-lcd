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
    refresh_interval: float = 2.0
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


def apply_overrides(
    cfg: AppConfig,
    *,
    layout: str | None = None,
    theme: str | None = None,
    refresh_interval: float | None = None,
) -> AppConfig:
    """Apply CLI flags on top of config.yaml, in place, then validate.

    A flag left unset keeps the file's value.
    """
    if layout is not None:
        cfg.display.layout = layout
    if theme is not None:
        cfg.display.theme = theme
    if refresh_interval is not None:
        cfg.display.refresh_interval = refresh_interval
    validate(cfg)
    return cfg


def validate(cfg: AppConfig) -> None:
    """Reject values that would crash or busy-loop the daemon."""
    try:
        cfg.display.refresh_interval = float(cfg.display.refresh_interval)
    except (TypeError, ValueError):
        raise ValueError(
            f"refresh_interval must be a number, got {cfg.display.refresh_interval!r}"
        ) from None
    if cfg.display.refresh_interval <= 0:
        raise ValueError(
            f"refresh_interval must be greater than 0, got {cfg.display.refresh_interval}"
        )


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
