"""不依赖外部 AI 的试卷检测与保守彩色笔迹净化 POC。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np
from PIL import Image

ExamRecommendation = Literal["ordinary", "ask", "suggest_cleanup"]


@dataclass(frozen=True)
class ExamDetectionResult:
    score: float
    recommendation: ExamRecommendation
    long_line_count: int
    text_component_count: int
    answer_marker_count: int
    keyword_hits: int


@dataclass(frozen=True)
class ExamCleanupResult:
    image: Image.Image
    candidate_mask: np.ndarray
    removed_mask: np.ndarray
    review_mask: np.ndarray
    applied: bool
    needs_review: bool
    reason: str
    candidate_ratio: float
    removed_ratio: float
    review_ratio: float
    black_ink_preserved: bool = True


def _analysis_image(image: Image.Image, max_dimension: int) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    scale = min(1.0, max_dimension / max(height, width))
    if scale == 1.0:
        return rgb
    return cv2.resize(
        rgb,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def detect_exam_layout(
    image: Image.Image,
    *,
    keyword_hits: int = 0,
    max_analysis_dimension: int = 1600,
) -> ExamDetectionResult:
    """用版式信号给出建议等级；keyword_hits 预留给后续自有 OCR。"""

    if keyword_hits < 0:
        raise ValueError("关键词命中数不能为负数")
    if max_analysis_dimension < 256:
        raise ValueError("分析尺寸不能小于 256")

    rgb = _analysis_image(image, max_analysis_dimension)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        15,
    )
    height, width = binary.shape
    image_area = height * width

    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(24, width // 18), 1))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
    line_components, _, line_stats, _ = cv2.connectedComponentsWithStats(horizontal, 8)
    long_line_count = sum(
        1
        for index in range(1, line_components)
        if line_stats[index, cv2.CC_STAT_WIDTH] >= width * 0.18
        and line_stats[index, cv2.CC_STAT_HEIGHT] <= max(8, height * 0.015)
    )

    component_count, _, component_stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    text_component_count = 0
    for index in range(1, component_count):
        component_width = component_stats[index, cv2.CC_STAT_WIDTH]
        component_height = component_stats[index, cv2.CC_STAT_HEIGHT]
        area = component_stats[index, cv2.CC_STAT_AREA]
        if (
            3 <= component_width <= width * 0.12
            and 4 <= component_height <= height * 0.06
            and 8 <= area <= image_area * 0.004
        ):
            text_component_count += 1

    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    answer_marker_count = 0
    hierarchy_rows = hierarchy[0] if hierarchy is not None else []
    for index, contour in enumerate(contours):
        x, y, marker_width, marker_height = cv2.boundingRect(contour)
        del x, y
        marker_area = marker_width * marker_height
        if not (
            8 <= marker_width <= width * 0.04
            and 8 <= marker_height <= height * 0.04
            and 0.65 <= marker_width / marker_height <= 1.35
            and marker_area <= image_area * 0.0015
        ):
            continue
        contour_area = abs(cv2.contourArea(contour))
        has_hole = bool(len(hierarchy_rows) > index and hierarchy_rows[index][2] >= 0)
        if has_hole and contour_area / marker_area >= 0.25:
            answer_marker_count += 1

    line_score = min(1.0, long_line_count / 6)
    component_score = min(1.0, text_component_count / 80)
    marker_score = min(1.0, answer_marker_count / 4)
    keyword_score = min(1.0, keyword_hits / 3)
    score = round(
        0.30 * line_score + 0.25 * component_score + 0.20 * marker_score + 0.25 * keyword_score,
        6,
    )
    if score >= 0.65:
        recommendation: ExamRecommendation = "suggest_cleanup"
    elif score >= 0.25:
        recommendation = "ask"
    else:
        recommendation = "ordinary"
    return ExamDetectionResult(
        score=score,
        recommendation=recommendation,
        long_line_count=long_line_count,
        text_component_count=text_component_count,
        answer_marker_count=answer_marker_count,
        keyword_hits=keyword_hits,
    )


def _readonly(mask: np.ndarray) -> np.ndarray:
    mask.setflags(write=False)
    return mask


def _empty_cleanup(image: Image.Image, *, reason: str) -> ExamCleanupResult:
    height, width = image.height, image.width
    empty = np.zeros((height, width), dtype=np.uint8)
    return ExamCleanupResult(
        image=image.copy(),
        candidate_mask=_readonly(empty.copy()),
        removed_mask=_readonly(empty.copy()),
        review_mask=_readonly(empty.copy()),
        applied=False,
        needs_review=False,
        reason=reason,
        candidate_ratio=0.0,
        removed_ratio=0.0,
        review_ratio=0.0,
    )


def conservative_color_cleanup(
    image: Image.Image,
    *,
    saturation_threshold: int = 70,
    maximum_candidate_ratio: float = 0.08,
    maximum_review_share: float = 0.35,
    cleanup_strength: float = 0.92,
) -> ExamCleanupResult:
    """只弱化安全彩色候选；黑色笔迹和疑似印刷重叠区域始终保留。"""

    if not 1 <= saturation_threshold <= 254:
        raise ValueError("饱和度阈值必须位于 1 到 254")
    if not 0 < maximum_candidate_ratio <= 1:
        raise ValueError("候选面积阈值必须位于 0 到 1")
    if not 0 <= maximum_review_share <= 1:
        raise ValueError("复核占比阈值必须位于 0 到 1")
    if not 0 < cleanup_strength <= 1:
        raise ValueError("净化强度必须位于 0 到 1")

    rgb = np.asarray(image.convert("RGB")).copy()
    height, width = rgb.shape[:2]
    pixel_count = height * width
    if pixel_count == 0:
        return _empty_cleanup(image, reason="empty_image")

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    color_range = rgb.max(axis=2).astype(np.int16) - rgb.min(axis=2).astype(np.int16)
    raw_candidate = (
        (saturation >= saturation_threshold) & (value <= 248) & (color_range >= 45)
    ).astype(np.uint8)
    raw_candidate = cv2.morphologyEx(
        raw_candidate,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2)),
    )
    raw_candidate = cv2.morphologyEx(
        raw_candidate,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(raw_candidate, 8)
    candidate = np.zeros_like(raw_candidate)
    for index in range(1, component_count):
        component_area = stats[index, cv2.CC_STAT_AREA]
        if component_area >= 4:
            candidate[labels == index] = 1

    candidate_count = int(candidate.sum())
    if candidate_count == 0:
        return _empty_cleanup(image, reason="no_safe_color_candidates")

    printed = ((saturation < 45) & (gray < 155)).astype(np.uint8)
    protected = cv2.dilate(
        printed,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
        iterations=1,
    )
    dark_candidate = (candidate == 1) & (gray < 75)
    near_printed_content = (candidate == 1) & (protected == 1)
    review = (dark_candidate | near_printed_content).astype(np.uint8)
    review_buffer = cv2.dilate(
        review,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        iterations=1,
    )
    safe = ((candidate == 1) & (review_buffer == 0)).astype(np.uint8)

    candidate_ratio = candidate_count / pixel_count
    review_count = int(review.sum())
    review_share = review_count / candidate_count
    if candidate_ratio > maximum_candidate_ratio:
        reason = "candidate_area_too_large"
    elif review_share > maximum_review_share:
        reason = "printed_content_overlap_too_high"
    elif not safe.any():
        reason = "no_candidate_safe_to_modify"
    else:
        reason = ""

    if reason:
        empty = np.zeros_like(candidate)
        return ExamCleanupResult(
            image=image.copy(),
            candidate_mask=_readonly(candidate),
            removed_mask=_readonly(empty),
            review_mask=_readonly(review),
            applied=False,
            needs_review=True,
            reason=reason,
            candidate_ratio=round(candidate_ratio, 6),
            removed_ratio=0.0,
            review_ratio=round(review_share, 6),
        )

    background_pixels = rgb[(saturation < 35) & (value > 165)]
    if len(background_pixels) == 0:
        background = np.array([255, 255, 255], dtype=np.float32)
    else:
        background = np.percentile(background_pixels, 75, axis=0).astype(np.float32)
    safe_pixels = safe.astype(bool)
    original_pixels = rgb[safe_pixels].astype(np.float32)
    rgb[safe_pixels] = np.clip(
        original_pixels * (1 - cleanup_strength) + background * cleanup_strength,
        0,
        255,
    ).astype(np.uint8)
    removed_count = int(safe.sum())
    return ExamCleanupResult(
        image=Image.fromarray(rgb),
        candidate_mask=_readonly(candidate),
        removed_mask=_readonly(safe),
        review_mask=_readonly(review),
        applied=True,
        needs_review=review_count > 0,
        reason="partial_cleanup_requires_review" if review_count else "safe_color_cleanup_applied",
        candidate_ratio=round(candidate_ratio, 6),
        removed_ratio=round(removed_count / pixel_count, 6),
        review_ratio=round(review_share, 6),
    )
