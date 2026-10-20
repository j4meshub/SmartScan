from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from services.worker.app.book import conservative_dewarp_page, split_book_spread


def curved_page(width: int = 600, height: int = 800, curve: float = 28) -> Image.Image:
    pixels = np.full((height, width, 3), 30, dtype=np.uint8)
    midpoint = (width - 1) / 2
    for x in range(20, width - 20):
        normalized = (x - midpoint) / midpoint
        offset = round(curve * normalized * normalized)
        top = 35 + offset
        bottom = height - 35 - offset
        pixels[top:bottom, x] = (242, 242, 236)
        for y in range(top + 90, bottom - 20, 70):
            pixels[y : y + 4, x] = (45, 45, 45)
    return Image.fromarray(pixels)


def book_spread() -> tuple[Image.Image, int]:
    width, height = 1400, 900
    spine = 610
    pixels = np.full((height, width, 3), 28, dtype=np.uint8)
    for x in range(90, spine - 12):
        normalized = (x - 90) / max(1, spine - 102 - 90)
        top = round(95 + 34 * (normalized - 0.45) ** 2)
        bottom = round(805 - 24 * (normalized - 0.45) ** 2)
        pixels[top:bottom, x] = (242, 241, 232)
    for x in range(spine + 12, 1320):
        normalized = (x - (spine + 12)) / max(1, 1320 - (spine + 12))
        top = round(105 + 40 * (normalized - 0.55) ** 2)
        bottom = round(795 - 30 * (normalized - 0.55) ** 2)
        pixels[top:bottom, x] = (239, 240, 232)
    image = Image.fromarray(pixels)
    draw = ImageDraw.Draw(image)
    for y in range(180, 740, 70):
        draw.line((150, y, spine - 75, y + 4), fill="black", width=4)
        draw.line((spine + 80, y + 3, 1240, y), fill="black", width=4)
    return image, spine


def test_split_detects_off_center_spine_and_keeps_unequal_page_widths() -> None:
    image, expected_spine = book_spread()

    result = split_book_spread(image)

    assert result.split_detected is True
    assert result.reason == "spread_split"
    assert result.spine_x is not None
    assert abs(result.spine_x - expected_spine) <= 25
    assert result.confidence >= 0.5
    assert [page.side for page in result.pages] == ["left", "right"]
    assert result.pages[0].image.width != result.pages[1].image.width


def test_split_respects_explicit_right_to_left_order() -> None:
    image, _ = book_spread()

    result = split_book_spread(image, reading_order="right_to_left")

    assert result.split_detected is True
    assert [page.side for page in result.pages] == ["right", "left"]


def test_single_page_without_spine_returns_original_as_one_logical_page() -> None:
    image = Image.new("RGB", (1000, 800), (25, 25, 25))
    draw = ImageDraw.Draw(image)
    draw.rectangle((120, 80, 880, 720), fill=(242, 242, 238))
    for y in range(180, 650, 70):
        draw.line((220, y, 780, y), fill="black", width=4)

    result = split_book_spread(image)

    assert result.split_detected is False
    assert result.spine_x is None
    assert result.reason == "spine_not_confident"
    assert len(result.pages) == 1
    assert result.pages[0].side == "single"
    assert np.array_equal(np.asarray(result.pages[0].image), np.asarray(image))


def test_missing_second_side_falls_back_instead_of_splitting_background() -> None:
    image = Image.new("RGB", (1200, 800), (25, 25, 25))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 560, 720), fill=(245, 245, 240))
    draw.rectangle((560, 80, 575, 720), fill=(5, 5, 5))

    result = split_book_spread(image)

    assert result.split_detected is False
    assert len(result.pages) == 1
    assert result.reason in {"spine_not_confident", "one_side_missing"}


def test_conservative_dewarp_applies_only_when_boundary_score_improves() -> None:
    image = curved_page(curve=35)

    result = conservative_dewarp_page(image)

    assert result.applied is True
    assert result.reason == "boundary_geometry_improved"
    assert result.output_score >= result.source_score + 0.02
    assert result.image.size == image.size


def test_straight_page_does_not_receive_unnecessary_dewarp() -> None:
    image = Image.new("RGB", (600, 800), (30, 30, 30))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 35, 580, 765), fill=(242, 242, 238))

    result = conservative_dewarp_page(image)

    assert result.applied is False
    assert result.reason == "curvature_not_needed"
    assert np.array_equal(np.asarray(result.image), np.asarray(image))


def test_excessive_curvature_falls_back_to_original() -> None:
    image = curved_page(curve=150)

    result = conservative_dewarp_page(image)

    assert result.applied is False
    assert result.reason == "curvature_too_large"
    assert np.array_equal(np.asarray(result.image), np.asarray(image))


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"reading_order": "auto"}, "阅读顺序"),
        ({"minimum_spine_contrast": 0}, "书脊对比度"),
        ({"minimum_side_coverage": 0}, "单侧覆盖率"),
    ],
)
def test_split_rejects_ambiguous_configuration(arguments: dict[str, object], message: str) -> None:
    image, _ = book_spread()
    with pytest.raises(ValueError, match=message):
        split_book_spread(image, **arguments)


def test_dewarp_rejects_invalid_thresholds() -> None:
    image = curved_page()
    with pytest.raises(ValueError, match="曲率"):
        conservative_dewarp_page(
            image,
            minimum_curvature_ratio=0.2,
            maximum_curvature_ratio=0.1,
        )
    with pytest.raises(ValueError, match="改善"):
        conservative_dewarp_page(image, minimum_score_improvement=2)
