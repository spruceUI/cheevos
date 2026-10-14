"""A small panel of text over the current screen, such as an award's details (.agents/pyui.md).

It sits where the theme puts its popup menus, on the same panel image, and freezes the frame
underneath the way PyUI's popups do: until it closes, every frame starts from that backdrop.
"""

from __future__ import annotations

from collections.abc import Sequence

from cheevos.ui.pyui.primitives import (
    Button,
    Text,
    displayable,
    line_height,
    screen_size,
    text,
    text_width,
    wait_for,
    wrap,
)

Row = tuple[str, Text]


def show_text(heading: str, lines: Sequence[str]) -> None:
    """Show a heading and lines of text in the theme's popup panel until A or B.

    Text is wrapped to the panel; what doesn't fit ends with an ellipsis. Start does nothing
    here, as in the other popups.

    Args:
        heading: First line, in the title font.
        lines: Further lines, in the body font (empty ones are skipped).
    """
    from display.display import Display
    from display.render_mode import RenderMode
    from themes.theme import Theme

    panel = Theme.menu_popup_bg_large()
    panel_width, panel_height = (int(value) for value in Display.get_image_dimensions(panel))
    width, height = screen_size()
    x = int(Theme.pop_menu_x_offset() * width)
    y = int(Theme.pop_menu_y_offset() * height)
    if Theme.pop_menu_add_top_bar_height_to_y_offset():
        y += int(Display.get_top_bar_height())
    pad = int(Theme.pop_menu_text_padding())
    rows = layout(heading, lines, panel_width - 2 * pad, panel_height - 2 * pad)
    title = Display.get_current_top_bar_title()
    Display.render_image(panel, x, y, RenderMode.TOP_LEFT_ALIGNED)
    Display.present()
    Display.lock_current_image()  # the screen and the panel become the backdrop
    try:
        while True:
            Display.clear(title)
            top = y + pad
            for value, role in rows:
                text(value, x + pad, top, role)
                top += line_height(role)
            Display.present()
            if wait_for({Button.A, Button.B, Button.START}) in (Button.A, Button.B):
                return
    finally:
        Display.unlock_current_image()


def layout(heading: str, lines: Sequence[str], width: int, height: int) -> list[Row]:
    """Wrap the text into rows that fit a box, ending with an ellipsis when it overflows.

    Args:
        heading: Title-font text.
        lines: Body-font paragraphs.
        width: Box width.
        height: Box height.

    Returns:
        The rows to draw, top to bottom.
    """
    rows: list[Row] = [(row, Text.TITLE) for row in wrap(heading, Text.TITLE, width)]
    for line in lines:
        if line:
            rows += [(row, Text.BODY) for row in wrap(line, Text.BODY, width)]
    used, kept = 0, []
    for row in rows:
        used += line_height(row[1])
        if used > height and kept:
            value, role = kept[-1]
            ellipsis = displayable("…", role)
            while value and text_width(value + ellipsis, role) > width:
                value = value[:-1]
            kept[-1] = (value.rstrip() + ellipsis, role)
            break
        kept.append(row)
    return kept
