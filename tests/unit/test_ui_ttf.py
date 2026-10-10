import ctypes
import sys
from types import SimpleNamespace

import pytest

from cheevos.ui.pyui import text
from cheevos.ui.pyui.text import Text, displayable, fit_text, text_width


@pytest.fixture
def ttf(monkeypatch):
    calls = []
    font = object()

    def metrics(_font, codepoint, *_metrics):
        assert _font is font
        calls.append(("metrics", codepoint))
        ctypes.cast(_metrics[-1], ctypes.POINTER(ctypes.c_int)).contents.value = 10
        return 0

    def provided(_font, codepoint):
        assert _font is font
        calls.append(("provided", codepoint))
        return 0 if chr(codepoint) in {"é", "…"} else 1

    def dimensions(_purpose, value):
        calls.append(("dimensions", value))
        return (18, 24)

    api = SimpleNamespace(
        TTF_GlyphMetrics=metrics,
        TTF_GlyphMetrics32=metrics,
        TTF_GlyphIsProvided=provided,
        TTF_GlyphIsProvided32=provided,
    )
    display = SimpleNamespace(
        fonts={role.value: SimpleNamespace(font=font) for role in Text},
        get_text_dimensions=dimensions,
    )
    for name, module in {
        "sdl2": SimpleNamespace(sdlttf=api),
        "display.display": SimpleNamespace(Display=display),
        "display.font_purpose": SimpleNamespace(
            FontPurpose={role.value: role.value for role in Text}
        ),
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    text._advances.clear()
    text._glyphs.clear()
    text._has_glyph.cache_clear()
    text._ellipsis.cache_clear()
    yield SimpleNamespace(api=api, calls=calls, display=display)
    text._advances.clear()
    text._glyphs.clear()
    text._has_glyph.cache_clear()
    text._ellipsis.cache_clear()


def unavailable(*_args):
    raise RuntimeError("requires SDL2_ttf 2.0.18, but the loaded version is 2.0.15")


@pytest.mark.parametrize("binding", ["runtime_error", "missing_attribute"])
def test_older_ttf_fits_setup_title_and_keeps_glyph_advances_cached(ttf, binding):
    if binding == "runtime_error":
        ttf.api.TTF_GlyphMetrics32 = unavailable
    else:
        del ttf.api.TTF_GlyphMetrics32

    assert fit_text("Setup", Text.HEADING, 200) == "Setup"
    assert text_width("Setup", Text.HEADING) == 50
    assert ttf.calls == [("metrics", ord(char)) for char in "Setup"]


@pytest.mark.parametrize("binding", ["runtime_error", "missing_attribute"])
def test_older_ttf_checks_glyph_coverage_and_uses_ascii_fallbacks(ttf, binding):
    if binding == "runtime_error":
        ttf.api.TTF_GlyphIsProvided32 = unavailable
    else:
        del ttf.api.TTF_GlyphIsProvided32

    assert displayable("Pokémon… ·", Text.BODY) == "Pokemon... ·"
    assert sorted(ttf.calls) == [("provided", ord(char)) for char in "·é…"]


def test_older_ttf_never_truncates_supplementary_codepoints_to_16_bits(ttf):
    ttf.api.TTF_GlyphMetrics32 = unavailable
    ttf.api.TTF_GlyphIsProvided32 = unavailable
    char = "\U00020000"  # Supplementary CJK character, outside the emoji filter.
    assert displayable(char, Text.BODY) == char
    assert text_width(char, Text.BODY) == 18
    assert ttf.calls == [("dimensions", char)]


def test_modern_ttf_measures_and_checks_supplementary_glyphs(ttf):
    char = "\U00020000"
    assert displayable(char, Text.BODY) == char
    assert text_width(char, Text.BODY) == 10
    assert ttf.calls == [("provided", ord(char)), ("metrics", ord(char))]


def test_failed_glyph_metrics_use_text_dimensions(ttf):
    ttf.api.TTF_GlyphMetrics32 = lambda *_args: -1
    assert text_width("A", Text.HEADING) == 18
    assert ttf.calls == [("dimensions", "A")]


def test_failed_legacy_glyph_metrics_use_text_dimensions(ttf):
    ttf.api.TTF_GlyphMetrics32 = unavailable
    ttf.api.TTF_GlyphMetrics = lambda *_args: -1
    assert text_width("A", Text.HEADING) == 18
    assert ttf.calls == [("dimensions", "A")]
