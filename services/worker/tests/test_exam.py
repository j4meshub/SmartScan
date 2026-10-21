from __future__ import annotations

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from services.worker.app.exam import (
    CLASSIFIER_VERSION,
    classify_exam_page,
    conservative_color_cleanup,
    detect_exam_layout,
    exam_keyword_hits,
    exam_text_signals,
)


class FixedExamModel:
    model_version = "fixed-test-v1"

    def __init__(self, probability: float):
        self.probability = probability

    def predict_exam_probability(self, image: Image.Image) -> float:
        del image
        return self.probability


class FailingExamModel:
    model_version = "failing-test-v1"

    def predict_exam_probability(self, image: Image.Image) -> float:
        del image
        raise RuntimeError("不得进入持久证据的内部模型错误")


def exam_page() -> Image.Image:
    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    for row in range(12):
        y = 120 + row * 105
        for column in range(8):
            x = 120 + column * 90
            draw.rectangle((x, y, x + 35, y + 20), fill="black")
        draw.line((170, y + 55, 1020, y + 55), fill="black", width=3)
    for y in (180, 420, 660, 900):
        draw.rectangle((80, y, 105, y + 25), outline="black", width=3)
    return image


def test_exam_layout_uses_confidence_bands_and_optional_keyword_signal() -> None:
    high = detect_exam_layout(exam_page())
    assert high.recommendation == "suggest_cleanup"
    assert high.long_line_count >= 6
    assert high.text_component_count >= 80
    assert high.answer_marker_count >= 4

    plain = Image.new("RGB", (1200, 1600), "white")
    ordinary = detect_exam_layout(plain)
    assert ordinary.score == 0
    assert ordinary.recommendation == "ordinary"

    keyword_only = detect_exam_layout(plain, keyword_hits=3)
    assert keyword_only.recommendation == "ask"


def test_product_classifier_fuses_rules_ocr_and_optional_local_model() -> None:
    classified = classify_exam_page(
        exam_page(),
        ocr_text="姓名 Alice 班级 3 EXAM SCORE",
        model=FixedExamModel(0.9),
    )

    assert classified.prediction == "exam"
    assert classified.confidence_band == "high"
    assert classified.recommendation == "suggest_cleanup"
    assert classified.exam_probability >= 0.65
    assert classified.keyword_hits == 4
    assert classified.model_probability == 0.9
    assert classified.classifier_version == "exam-fusion-v1:fixed-test-v1"
    assert "Alice" not in str(classified.details)


def test_classifier_falls_back_to_rules_when_local_model_fails() -> None:
    classified = classify_exam_page(exam_page(), model=FailingExamModel())

    assert classified.classifier_version == CLASSIFIER_VERSION
    assert classified.model_probability is None
    assert classified.details["model_status"] == "fallback"
    assert "内部模型错误" not in str(classified.details)


def test_explicit_exam_mode_is_high_confidence_without_model() -> None:
    classified = classify_exam_page(
        Image.new("RGB", (800, 1200), "white"),
        explicit_exam_mode=True,
    )

    assert classified.prediction == "exam"
    assert classified.exam_probability == 1.0
    assert classified.recommendation == "suggest_cleanup"
    assert classified.classifier_version == "user-selected-exam-v1"
    assert classified.details["source"] == "user_selected"


def test_exam_keyword_hits_are_unique_and_language_aware() -> None:
    assert exam_keyword_hits("姓名 姓名 班级 TEST EXAM score") == 4
    assert exam_keyword_hits("classification example") == 0
    assert exam_keyword_hits(None) == 0


def test_exam_text_signals_count_layout_semantics_without_copying_ocr_text() -> None:
    text = "1. （10分） A. 选项 B. 选项 ____ 装订线 x = √4 Alice"

    signals = exam_text_signals(text)

    assert signals["question_number_hits"] == 1
    assert signals["score_hits"] == 1
    assert signals["option_hits"] == 2
    assert signals["answer_line_hits"] == 1
    assert signals["binding_line_hits"] == 1
    assert signals["formula_token_hits"] == 2
    assert signals["formula_density"] > 0
    assert "Alice" not in str(signals)


def test_cleanup_weakens_isolated_colored_ink_and_preserves_print() -> None:
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.text((100, 100), "PRINTED CONTENT", fill="black", stroke_width=1)
    draw.line((120, 350, 500, 430), fill=(240, 40, 40), width=12)
    before = np.asarray(image).copy()

    result = conservative_color_cleanup(image)
    after = np.asarray(result.image)

    assert result.applied is True
    assert result.reason == "safe_color_cleanup_applied"
    assert result.removed_ratio > 0
    assert result.review_ratio == 0
    assert result.black_ink_preserved is True
    assert np.array_equal(after[90:130, 90:260], before[90:130, 90:260])
    assert after[390, 310].mean() > before[390, 310].mean()


def test_cleanup_preserves_dark_or_print_overlapping_candidates_for_review() -> None:
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 250, 700, 270), fill="black")
    draw.line((150, 260, 650, 260), fill=(120, 0, 0), width=18)

    result = conservative_color_cleanup(image)

    assert result.applied is False
    assert result.needs_review is True
    assert result.reason in {"printed_content_overlap_too_high", "no_candidate_safe_to_modify"}
    assert result.review_mask.sum() > 0
    assert result.removed_mask.sum() == 0
    assert np.array_equal(np.asarray(result.image), np.asarray(image))


def test_cleanup_falls_back_for_large_colored_region() -> None:
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 100, 700, 500), fill=(220, 60, 60))

    result = conservative_color_cleanup(image)

    assert result.applied is False
    assert result.needs_review is True
    assert result.reason == "candidate_area_too_large"
    assert np.array_equal(np.asarray(result.image), np.asarray(image))


def test_cleanup_leaves_grayscale_page_and_black_handwriting_unchanged() -> None:
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.text((100, 100), "PRINTED", fill="black")
    draw.line((120, 350, 500, 430), fill="black", width=12)

    result = conservative_color_cleanup(image)

    assert result.applied is False
    assert result.needs_review is False
    assert result.reason == "no_safe_color_candidates"
    assert result.black_ink_preserved is True
    assert np.array_equal(np.asarray(result.image), np.asarray(image))


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"saturation_threshold": 0}, "饱和度"),
        ({"maximum_candidate_ratio": 0}, "候选面积"),
        ({"maximum_review_share": 2}, "复核占比"),
        ({"cleanup_strength": 0}, "净化强度"),
    ],
)
def test_cleanup_rejects_unsafe_configuration(arguments: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        conservative_color_cleanup(Image.new("RGB", (400, 400), "white"), **arguments)


def test_cleanup_masks_are_read_only() -> None:
    image = Image.new("RGB", (400, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.line((40, 200, 360, 220), fill=(240, 30, 30), width=10)

    result = conservative_color_cleanup(image)

    with pytest.raises(ValueError):
        result.candidate_mask[0, 0] = 1


def test_detection_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="关键词"):
        detect_exam_layout(exam_page(), keyword_hits=-1)
    with pytest.raises(ValueError, match="分析尺寸"):
        detect_exam_layout(exam_page(), max_analysis_dimension=128)


def test_colored_candidate_mask_remains_binary() -> None:
    image = np.full((500, 500, 3), 255, dtype=np.uint8)
    cv2.line(image, (50, 250), (450, 280), (255, 0, 0), 12)

    result = conservative_color_cleanup(Image.fromarray(image))

    assert set(np.unique(result.candidate_mask)).issubset({0, 1})
    assert set(np.unique(result.removed_mask)).issubset({0, 1})
    assert set(np.unique(result.review_mask)).issubset({0, 1})
