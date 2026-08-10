import numpy as np
import numpy.typing as npt

from aurora.core.colorx import (
    dominant_hue,
    palette_from_cover,
    palette_from_hue,
    palette_from_seed,
)


def _solid(rgb: tuple[int, int, int], size: int = 96) -> npt.NDArray[np.uint8]:
    image = np.zeros((size, size, 3), dtype=np.uint8)
    image[:, :] = rgb
    return image


def _hue_of(rgb: tuple[int, int, int]) -> float:
    found = dominant_hue(_solid(rgb))
    assert found is not None
    return found[0]


def test_primary_colours_map_to_expected_hues() -> None:
    assert _hue_of((255, 0, 0)) == 0.0
    assert abs(_hue_of((0, 255, 0)) - 120.0) < 1.0
    assert abs(_hue_of((0, 0, 255)) - 240.0) < 1.0
    assert abs(_hue_of((255, 255, 0)) - 60.0) < 1.0
    assert abs(_hue_of((0, 255, 255)) - 180.0) < 1.0
    assert abs(_hue_of((255, 0, 255)) - 300.0) < 1.0


def test_greyscale_cover_has_no_dominant_hue() -> None:
    """整張灰的封面不該決定主題色，應退回中性色相。"""
    assert dominant_hue(_solid((128, 128, 128))) is None
    assert dominant_hue(_solid((0, 0, 0))) is None
    assert dominant_hue(_solid((255, 255, 255))) is None


def test_saturated_minority_beats_desaturated_majority() -> None:
    """大片灰底 + 一小塊鮮紅 → 主色應該是紅，不是灰。"""
    image = _solid((110, 110, 112), size=64)
    image[:12, :12] = (230, 20, 30)
    found = dominant_hue(image)
    assert found is not None
    hue, saturation = found
    assert hue < 15.0 or hue > 350.0
    assert saturation > 0.5


def test_palette_is_valid_hex_and_readable() -> None:
    palette = palette_from_hue(280.0, 0.7)
    for value in (palette.accent, palette.accent2, palette.bg_top, palette.bg_bottom):
        assert len(value) == 7 and value.startswith("#")
        int(value[1:], 16)  # 解析得動就是合法的十六進位

    def brightness(hex_colour: str) -> int:
        return max(int(hex_colour[index : index + 2], 16) for index in (1, 3, 5))

    # accent 必須明顯亮於背景，否則深色底上讀不到
    assert brightness(palette.accent) > brightness(palette.bg_top) + 80


def test_accent2_is_hue_shifted_from_accent() -> None:
    palette = palette_from_hue(120.0, 0.8)
    assert palette.accent != palette.accent2


def test_cover_without_colour_falls_back_instead_of_failing() -> None:
    palette = palette_from_cover(_solid((90, 90, 90)))
    assert palette.accent.startswith("#")


def test_empty_array_is_handled() -> None:
    assert dominant_hue(np.zeros((0, 0, 3), dtype=np.uint8)) is None


def test_seed_palette_is_deterministic_and_varied() -> None:
    assert palette_from_seed("a.mp3") == palette_from_seed("a.mp3")
    assert palette_from_seed("a.mp3") != palette_from_seed("b.mp3")
