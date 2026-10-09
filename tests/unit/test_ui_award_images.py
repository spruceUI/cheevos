from pathlib import Path

import pytest

from cheevos.core.models import AwardKind
from cheevos.ui.pyui import award_images, generated
from cheevos.ui.pyui.bar_colors import luma, palette

PALETTES = [
    ("dark", palette((43, 43, 43), (240, 230, 200))),
    ("light", palette((255, 255, 255), (0, 0, 0))),
    ("black", palette((230, 190, 40), (20, 20, 20))),
    ("white", palette((180, 160, 80), (240, 230, 200))),
]


def pixel(pixels, canvas, x, y):
    offset = (y * canvas + x) * 4
    return tuple(pixels[offset : offset + 4])


@pytest.mark.parametrize(("style", "colors"), PALETTES)
def test_awards_are_existing_bundled_pngs_without_runtime_generation(style, colors, monkeypatch):
    def generate(*_args, **_kwargs):
        pytest.fail("The handheld tried to generate an award PNG")

    monkeypatch.setattr(generated, "write", generate)
    images = award_images.images(colors)
    assert set(images) == set(AwardKind)
    for kind, path in images.items():
        assert Path(path).name == f"{kind.value}-{style}.png"
        assert Path(path).is_file()
        assert "/res/awards/" in path


@pytest.mark.parametrize(("style", "colors"), PALETTES)
@pytest.mark.parametrize("kind", list(AwardKind))
def test_static_assets_keep_award_modes_rims_and_halos(style, colors, kind):
    pytest.importorskip("sdl2.sdlimage")
    loaded = generated.load_rgba(award_images.images(colors)[kind])
    assert loaded is not None
    canvas, height, pixels = loaded
    assert canvas == height == award_images.canvas_size(kind, award_images.DIAMETER)
    centre = pixel(pixels, canvas, canvas // 2, canvas // 2)
    marker = colors.markers[kind]
    assert centre[3] == (255 if marker.filled else 0)
    assert pixel(pixels, canvas, 0, 0)[3] == 0
    assert any(0 < pixels[index] < 255 for index in range(3, len(pixels), 4))
    pad = (canvas - award_images.DIAMETER) // 2
    rim = pixel(pixels, canvas, pad + 1, canvas // 2)
    assert rim[3] == 255
    if marker.filled:
        assert luma(rim[:3]) > luma(centre[:3])
    else:
        assert rim[:3] == marker.color
    if kind == AwardKind.MASTERED:
        alpha = [pixel(pixels, canvas, x, canvas // 2)[3] for x in (pad - 1, pad - 8, 1)]
        assert 255 > alpha[0] > alpha[1] > alpha[2] >= 0
    else:
        assert pixel(pixels, canvas, 0, canvas // 2)[3] == 0
