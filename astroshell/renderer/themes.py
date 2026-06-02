"""
Display themes. Default is 'effece' — the github.com/effecet/astroshell-lcd brand palette.
"""

from typing import TypedDict


class Theme(TypedDict):
    bg: str
    primary: str
    accent: str
    text: str
    muted: str
    label: str
    info: str
    font: str


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


THEMES: dict[str, Theme] = {
    "effece": {
        "bg": "#0d0d0d",
        "primary": "#f97316",  # orange
        "accent": "#22d3ee",  # cyan
        "text": "#e5e5e5",
        "muted": "#525252",
        "label": "#facc15",  # yellow
        "info": "#4ade80",  # green
        "font": "JetBrains Mono",
    },
    "dark_green": {
        "bg": "#0a0a0a",
        "primary": "#22c55e",
        "accent": "#4ade80",
        "text": "#d1fae5",
        "muted": "#374151",
        "label": "#facc15",
        "info": "#4ade80",
        "font": "monospace",
    },
    "matrix": {
        "bg": "#000000",
        "primary": "#00ff41",
        "accent": "#008f11",
        "text": "#00ff41",
        "muted": "#003b00",
        "label": "#facc15",
        "info": "#4ade80",
        "font": "monospace",
    },
}


def get_theme(name: str) -> Theme:
    return THEMES.get(name, THEMES["effece"])


def rgb(theme: Theme, key: str) -> tuple[int, int, int]:
    """Return a theme color as an (R, G, B) tuple."""
    return _hex(theme[key])
