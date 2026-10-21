from __future__ import annotations

from PIL import Image, ImageDraw

from services.worker.app.book_integrity import (
    extract_printed_page_number,
    fingerprint_distance,
    image_dhash,
    normalize_printed_page_label,
)
from services.worker.app.ocr import OcrAnalysis


def analysis(*lines: dict[str, object]) -> OcrAnalysis:
    return OcrAnalysis(
        rotation_degrees=0,
        text="\n".join(str(line["text"]) for line in lines),
        confidence=0.95,
        title_candidate=None,
        details={"schema_version": 1, "selected_image_size": [1000, 1400], "lines": list(lines)},
        model_version="test-ocr",
    )


def test_extracts_arabic_and_roman_numbers_only_from_common_page_regions() -> None:
    arabic = extract_printed_page_number(
        analysis(
            {"text": "正文 99", "confidence": 0.99, "box": [100, 600, 900, 680]},
            {"text": "第 12 页", "confidence": 0.93, "box": [460, 1300, 540, 1340]},
        )
    )
    roman = extract_printed_page_number(
        analysis({"text": "xiv", "confidence": 0.91, "box": [470, 40, 530, 80]})
    )

    assert (arabic.status, arabic.label, arabic.value, arabic.kind) == (
        "ready",
        "12",
        12,
        "arabic",
    )
    assert (roman.status, roman.label, roman.value, roman.kind) == (
        "ready",
        "xiv",
        14,
        "roman",
    )


def test_ambiguous_close_candidates_and_no_number_never_invent_a_label() -> None:
    ambiguous = extract_printed_page_number(
        analysis(
            {"text": "12", "confidence": 0.91, "box": [100, 1300, 150, 1340]},
            {"text": "13", "confidence": 0.90, "box": [850, 1300, 900, 1340]},
        )
    )
    absent = extract_printed_page_number(
        analysis({"text": "正文 12", "confidence": 0.99, "box": [100, 600, 900, 680]})
    )

    assert ambiguous.status == "ambiguous"
    assert ambiguous.label is None
    assert absent.status == "none"
    assert absent.label is None


def test_page_label_normalization_rejects_non_page_text() -> None:
    assert normalize_printed_page_label("Page 8 of 200") == ("8", 8, "arabic")
    assert normalize_printed_page_label("IX") == ("ix", 9, "roman")
    assert normalize_printed_page_label("项目 8") is None
    assert normalize_printed_page_label("IIII") is None


def test_dhash_is_deterministic_and_measures_visual_similarity() -> None:
    first = Image.new("RGB", (320, 480), "white")
    draw = ImageDraw.Draw(first)
    draw.rectangle((40, 60, 280, 420), outline="black", width=8)
    similar = first.resize((640, 960))
    different = Image.new("RGB", (320, 480), "black")
    draw = ImageDraw.Draw(different)
    draw.ellipse((40, 60, 280, 420), fill="white")

    first_hash = image_dhash(first)
    similar_hash = image_dhash(similar)
    different_hash = image_dhash(different)

    assert len(first_hash) == 16
    assert first_hash == image_dhash(first)
    assert fingerprint_distance(first_hash, similar_hash) is not None
    assert fingerprint_distance(first_hash, similar_hash) <= 3
    assert fingerprint_distance(first_hash, different_hash) > 3
