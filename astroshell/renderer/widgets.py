"""
Reusable Pillow drawing widgets for the 320×320 LCD canvas.
"""

from PIL import ImageDraw, ImageFont
from astroshell.renderer.themes import Theme, rgb


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf", size
        )
    except Exception:
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)
        except Exception:
            return ImageFont.load_default()


def draw_bar(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    percent: float,
    theme: Theme,
    color_key: str = "primary",
    bg_key: str = "muted",
    label: str = "",
    value_str: str = "",
) -> None:
    """Horizontal progress bar with optional label and value."""
    bg = rgb(theme, bg_key)
    fg = rgb(theme, color_key)
    txt = rgb(theme, "text")

    # Background track
    draw.rectangle([x, y, x + width, y + height], fill=bg)

    # Filled portion
    fill_w = int(width * max(0.0, min(1.0, percent / 100.0)))
    if fill_w > 0:
        draw.rectangle([x, y, x + fill_w, y + height], fill=fg)

    # Label left
    if label:
        fnt = _font(max(8, height - 4))
        draw.text((x + 4, y + 1), label, font=fnt, fill=txt)

    # Value right
    if value_str:
        fnt = _font(max(8, height - 4))
        draw.text((x + width - 60, y + 1), value_str, font=fnt, fill=txt)


def draw_text(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    theme: Theme,
    size: int = 14,
    color_key: str = "text",
    align: str = "left",
) -> None:
    fnt = _font(size)
    draw.text((x, y), text, font=fnt, fill=rgb(theme, color_key))


def draw_divider(
    draw: ImageDraw.ImageDraw,
    y: int,
    theme: Theme,
    color_key: str = "muted",
) -> None:
    draw.line([(8, y), (312, y)], fill=rgb(theme, color_key), width=1)


def draw_label_value(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    value: str,
    theme: Theme,
    label_size: int = 11,
    value_size: int = 18,
) -> None:
    draw_text(draw, x, y, label, theme, size=label_size, color_key="muted")
    draw_text(draw, x, y + label_size + 2, value, theme, size=value_size, color_key="primary")
