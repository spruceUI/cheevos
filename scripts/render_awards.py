"""Bake the bundled award PNGs on a development machine, never on the handheld.

Usage: ``uv run python scripts/render_awards.py``. Circles have a 48 px diameter, large enough
to scale down on handhelds. Dark/light colours follow the row palette; black/white variants
cover themes whose backgrounds fight RA colours. Hollow centres stay transparent: the bridge
covers the short strip of bar inside them before drawing the PNG (.agents/pyui.md).
"""

from __future__ import annotations

import math
from pathlib import Path

from cheevos.core.models import AwardKind
from cheevos.ui.pyui import generated
from cheevos.ui.pyui.bar_colors import GOLD, RGB, ZINC_400, Marker, palette

OUTPUT = Path(__file__).resolve().parents[1] / "src" / "cheevos" / "res" / "awards"
DIAMETER = 48
STYLES = {
    "dark": palette((43, 43, 43), (240, 230, 200)),
    "light": palette((255, 255, 255), (0, 0, 0)),
    "black": palette((230, 190, 40), (0, 0, 0)),
    "white": palette((180, 160, 80), (255, 255, 255)),
}

_GLOW_PAD = 0.7  # margin per diameter, enough for the mastery halo to fade out
_RIM_SHARE = 0.1  # rim thickness per diameter


def _blend(start: RGB, end: RGB, amount: float) -> RGB:
    """Interpolate between two RGB colours."""
    red, green, blue = (round(a + (b - a) * amount) for a, b in zip(start, end, strict=True))
    return red, green, blue


def _coverage(radius: float, distance: float) -> float:
    """Return the coverage of a pixel on an anti-aliased circular edge."""
    return min(max(radius + 0.5 - distance, 0.0), 1.0)


def _glow(outside: float, size: int) -> float:
    """Return the opacity of the mastery halo at a distance beyond the rim."""
    return (
        105 * math.exp(-((outside / (size * 0.18)) ** 2))
        + 28 * math.exp(-((outside / (size * 0.44)) ** 2))
    ) / 255


def _pixel(
    marker: Marker, size: int, dx: float, dy: float, *, mastered: bool, light: bool
) -> bytes:
    """Paint one pixel of the circle, its rim or its translucent halo."""
    radius = size / 2
    distance = math.hypot(dx, dy)
    cover = _coverage(radius, distance)
    inner = _coverage(radius - max(size * _RIM_SHARE, 1), distance)
    if not marker.filled:
        return bytes((*marker.color, round(255 * cover * (1 - inner))))
    halo = _glow(max(distance - radius, 0), size) if mastered else 0.0
    alpha = cover + halo * (1 - cover)
    if not alpha:
        return bytes(4)
    # Light rows keep a gold/grey core, with a darker outer edge for contrast, as in RA's
    # Completion Progress widget. The percentage still uses the palette's darker colour.
    base = (GOLD if mastered else ZINC_400) if light else marker.color
    rim = _blend(base, (255, 255, 255), 0.3)
    # Keep the palette's hue while giving the core a quiet vertical gradient.
    shade = min(max((dy + radius) / size, 0.0), 1.0)
    centre = _blend(base, (0, 0, 0), 0.3 * shade)
    circle = _blend(rim, centre, inner)
    if light:
        circle = _blend(marker.color, circle, _coverage(radius - 1, distance))
    color = _blend(base, circle, cover / alpha)
    return bytes((*color, round(alpha * 255)))


def pixels(marker: Marker, size: int, *, mastered: bool, light: bool = False) -> tuple[int, bytes]:
    """Draw an award at its native diameter, with a transparent margin for mastery.

    Args:
        marker: The row palette's colour and fill.
        size: Circle diameter, excluding the halo.
        mastered: Add a soft glow outside the rim.
        light: Keep a colourful core with a darker outer edge for light rows.

    Returns:
        Square canvas size and its RGBA bytes.
    """
    pad = math.ceil(size * _GLOW_PAD) if mastered else 1
    canvas = size + 2 * pad
    centre = canvas / 2
    rgba = bytearray()
    for y in range(canvas):
        for x in range(canvas):
            rgba.extend(
                _pixel(
                    marker,
                    size,
                    x + 0.5 - centre,
                    y + 0.5 - centre,
                    mastered=mastered,
                    light=light,
                )
            )
    return canvas, bytes(rgba)


def main() -> None:
    """Regenerate all bundled award PNGs, replacing existing files."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for style, colors in STYLES.items():
        for kind, marker in colors.markers.items():
            canvas, rgba = pixels(
                marker, DIAMETER, mastered=kind == AwardKind.MASTERED, light=style == "light"
            )
            path = OUTPUT / f"{kind.value}-{style}.png"
            path.write_bytes(generated.encode_png(canvas, canvas, rgba))
            print(f"{path.relative_to(OUTPUT.parent)} ({canvas}x{canvas})")


if __name__ == "__main__":
    main()
