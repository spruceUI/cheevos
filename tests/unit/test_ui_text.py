import sys
from types import SimpleNamespace

import pytest

from cheevos.ui.pyui import text
from cheevos.ui.pyui.text import (
    ListRoom,
    Text,
    displayable,
    fit_text,
    fit_with_tail,
    text_width,
)

LACKING = {"·", "…", "é"}  # a pixel font like Pico-8's


@pytest.fixture(autouse=True)
def fake_font(monkeypatch):
    """Every character is 10 px wide (a "W" 20 px); the font lacks the characters in LACKING."""
    measured = []

    def advance(_purpose, char):
        measured.append(char)
        return 20 if char == "W" else 10

    monkeypatch.setattr(text, "_advance", advance)
    monkeypatch.setattr(text, "_has_glyph", lambda _purpose, char: char not in LACKING)
    text._advances.clear()
    text._glyphs.clear()
    text._ellipsis.cache_clear()
    yield measured
    text._advances.clear()
    text._glyphs.clear()
    text._ellipsis.cache_clear()


def test_plain_ascii_is_returned_as_is():
    title = "Final Fantasy Tactics Advance"
    assert displayable(title, Text.TITLE) is title


def test_spaces_collapse_and_emoji_go():
    assert displayable("  Mario \U0001f3ae  Kart ", Text.TITLE) == "Mario Kart"


def test_characters_the_font_lacks_get_stand_ins():
    assert displayable("Pokémon · Red…", Text.BODY) == "Pokemon - Red..."
    assert displayable("Ñandú", Text.BODY) == "Ñandú"  # the font has these


def test_text_width_measures_each_character_once_per_font(fake_font):
    assert text_width("WAA", Text.TITLE) == 40
    assert text_width("AWW", Text.TITLE) == 50
    assert sorted(fake_font) == ["A", "W"]
    assert text_width("A", Text.BODY) == 10
    assert sorted(fake_font) == ["A", "A", "W"]


def test_fit_text_keeps_text_that_fits_and_shortens_the_rest():
    assert fit_text("Metroid", Text.TITLE, 100) == "Metroid"  # 70 px of 97
    # 97 px less "..." (30 px) leaves 67 px: six letters, then the stand-in ellipsis
    assert fit_text("Metroid Fusion", Text.TITLE, 100) == "Metroi..."


def test_fit_with_tail_keeps_the_date_whole():
    # Joined: "Mastered - 1 May" (16 characters, 160 px) fits 200 px as it is.
    assert fit_with_tail("Mastered", "1 May", Text.BODY, 200) == "Mastered - 1 May"
    # Too long: the description is shortened, the date and its separator stay.
    fitted = fit_with_tail("Awarded for earning points", "1 May", Text.BODY, 200)
    assert fitted.endswith("... - 1 May")
    assert text_width(fitted, Text.BODY) <= 200
    # No room left for a description: everything is shortened together.
    assert fit_with_tail("Awarded", "27 April 2026", Text.BODY, 120) == "Awarded..."
    assert fit_with_tail("", "1 May", Text.BODY, 200) == "1 May"
    assert fit_with_tail("Mastered", "", Text.BODY, 200) == "Mastered"


def test_list_room_takes_the_icon_column_from_the_row_background(monkeypatch):
    # SPRUCE at 480x800: the row background is 640 px wide, so PyUI's icon column is 80 px.
    device = SimpleNamespace(screen_width=lambda: 480)
    theme = SimpleNamespace(
        get_list_large_selected_bg=lambda: "bg-list-l.png",
        get_descriptive_list_icon_offset_x=lambda: 7,
        get_descriptive_list_text_from_icon_offset=lambda: 7,
    )
    display = SimpleNamespace(get_image_dimensions=lambda _path: (640, 90))
    monkeypatch.setitem(
        sys.modules,
        "devices.device",
        SimpleNamespace(Device=SimpleNamespace(get_device=lambda: device)),
    )
    monkeypatch.setitem(sys.modules, "themes.theme", SimpleNamespace(Theme=theme))
    monkeypatch.setitem(sys.modules, "display.display", SimpleNamespace(Display=display))
    assert text.list_room() == ListRoom(full=480 - 7 - 80 - 7 * 2, gap=7, least=120)


def test_list_room_leaves_the_value_its_width_and_the_title_a_minimum():
    room = ListRoom(full=400, gap=16, least=160)
    assert room.title("") == 400
    assert room.title("12/40") == 400 - 50 - 16
    assert room.title("W" * 20) == 160
