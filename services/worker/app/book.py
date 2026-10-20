"""不依赖外部 AI 的双页检测、拆分与保守边界去弯曲 POC。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np
from PIL import Image

ReadingOrder = Literal["left_to_right", "right_to_left"]
PageSide = Literal["left", "right", "single"]


@dataclass(frozen=True)
class DewarpResult:
    image: Image.Image
    applied: bool
    source_score: float
    output_score: float
    reason: str


@dataclass(frozen=True)
class LogicalBookPage:
    side: PageSide
    image: Image.Image
    dewarp: DewarpResult


@dataclass(frozen=True)
class BookSplitResult:
    pages: tuple[LogicalBookPage, ...]
    split_detected: bool
    spine_x: int | None
    confidence: float
    reason: str
    book_bounds: tuple[int, int, int, int] | None


@dataclass(frozen=True)
class _BoundaryGeometry:
    valid: bool
    coverage: float
    curvature_ratio: float
    score: float
    top_curve: np.ndarray | None = None
    bottom_curve: np.ndarray | None = None
    top_line: np.ndarray | None = None
    bottom_line: np.ndarray | None = None


def _page_mask(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )
    return cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)),
    )


def _book_bounds(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    height, width = mask.shape
    valid_columns = np.flatnonzero(np.count_nonzero(mask, axis=0) >= height * 0.12)
    valid_rows = np.flatnonzero(np.count_nonzero(mask, axis=1) >= width * 0.12)
    if len(valid_columns) == 0 or len(valid_rows) == 0:
        return None
    x0, x1 = int(valid_columns[0]), int(valid_columns[-1] + 1)
    y0, y1 = int(valid_rows[0]), int(valid_rows[-1] + 1)
    if (x1 - x0) * (y1 - y0) < width * height * 0.2:
        return None
    return x0, y0, x1, y1


def _boundary_geometry(rgb: np.ndarray) -> _BoundaryGeometry:
    height, width = rgb.shape[:2]
    if min(height, width) < 64:
        return _BoundaryGeometry(False, 0.0, 0.0, 0.0)
    mask = _page_mask(rgb)
    top = np.full(width, np.nan, dtype=np.float32)
    bottom = np.full(width, np.nan, dtype=np.float32)
    for x in range(width):
        rows = np.flatnonzero(mask[:, x])
        if len(rows) >= height * 0.35:
            top[x] = rows[0]
            bottom[x] = rows[-1]
    valid = np.isfinite(top) & np.isfinite(bottom)
    coverage = float(valid.mean())
    if coverage < 0.70 or int(valid.sum()) < 32:
        return _BoundaryGeometry(False, coverage, 0.0, 0.0)

    coordinates = np.arange(width, dtype=np.float32)
    normalized_x = coordinates / max(1, width - 1)
    top_curve_coefficients = np.polyfit(normalized_x[valid], top[valid], 2)
    bottom_curve_coefficients = np.polyfit(normalized_x[valid], bottom[valid], 2)
    top_line_coefficients = np.polyfit(normalized_x[valid], top[valid], 1)
    bottom_line_coefficients = np.polyfit(normalized_x[valid], bottom[valid], 1)
    top_curve = np.polyval(top_curve_coefficients, normalized_x).astype(np.float32)
    bottom_curve = np.polyval(bottom_curve_coefficients, normalized_x).astype(np.float32)
    top_line = np.polyval(top_line_coefficients, normalized_x).astype(np.float32)
    bottom_line = np.polyval(bottom_line_coefficients, normalized_x).astype(np.float32)
    top_deviation = float(np.ptp(top_curve - top_line))
    bottom_deviation = float(np.ptp(bottom_curve - bottom_line))
    curvature_ratio = (top_deviation + bottom_deviation) / (2 * height)
    score = max(0.0, 1.0 - curvature_ratio / 0.12)
    return _BoundaryGeometry(
        True,
        coverage,
        curvature_ratio,
        round(score, 6),
        top_curve,
        bottom_curve,
        top_line,
        bottom_line,
    )


def conservative_dewarp_page(
    image: Image.Image,
    *,
    minimum_curvature_ratio: float = 0.005,
    maximum_curvature_ratio: float = 0.12,
    minimum_score_improvement: float = 0.02,
) -> DewarpResult:
    """仅校正可信的二次边界曲率；几何分数未改善时返回原页。"""

    if not 0 <= minimum_curvature_ratio < maximum_curvature_ratio <= 0.5:
        raise ValueError("去弯曲曲率阈值无效")
    if not 0 <= minimum_score_improvement <= 1:
        raise ValueError("几何改善阈值必须位于 0 到 1")

    rgb = np.asarray(image.convert("RGB"))
    source = _boundary_geometry(rgb)
    if not source.valid:
        return DewarpResult(
            image.copy(), False, source.score, source.score, "boundary_not_confident"
        )
    if source.curvature_ratio < minimum_curvature_ratio:
        return DewarpResult(image.copy(), False, source.score, source.score, "curvature_not_needed")
    if source.curvature_ratio > maximum_curvature_ratio:
        return DewarpResult(image.copy(), False, source.score, source.score, "curvature_too_large")

    assert source.top_curve is not None
    assert source.bottom_curve is not None
    assert source.top_line is not None
    assert source.bottom_line is not None
    height, width = rgb.shape[:2]
    x_coordinates = np.broadcast_to(np.arange(width, dtype=np.float32), (height, width))
    y_coordinates = np.broadcast_to(
        np.arange(height, dtype=np.float32)[:, np.newaxis], (height, width)
    )
    target_height = np.maximum(source.bottom_line - source.top_line, 1.0)
    normalized_y = (y_coordinates - source.top_line[np.newaxis, :]) / target_height[np.newaxis, :]
    source_y = (
        source.top_curve[np.newaxis, :]
        + normalized_y * (source.bottom_curve - source.top_curve)[np.newaxis, :]
    )
    outside = (normalized_y < 0) | (normalized_y > 1)
    source_y[outside] = y_coordinates[outside]
    corrected = cv2.remap(
        rgb,
        x_coordinates,
        source_y.astype(np.float32),
        cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    output = _boundary_geometry(corrected)
    if not output.valid or output.score < source.score + minimum_score_improvement:
        output_score = output.score if output.valid else source.score
        return DewarpResult(
            image.copy(),
            False,
            source.score,
            output_score,
            "geometry_not_improved",
        )
    return DewarpResult(
        Image.fromarray(corrected),
        True,
        source.score,
        output.score,
        "boundary_geometry_improved",
    )


def _crop_page(rgb: np.ndarray, mask: np.ndarray, bounds: tuple[int, int, int, int]) -> Image.Image:
    x0, y0, x1, y1 = bounds
    local_mask = mask[y0:y1, x0:x1]
    rows, columns = np.nonzero(local_mask)
    if len(rows) == 0:
        return Image.fromarray(rgb[y0:y1, x0:x1].copy())
    page_x0, page_x1 = int(columns.min()), int(columns.max() + 1)
    page_y0, page_y1 = int(rows.min()), int(rows.max() + 1)
    return Image.fromarray(rgb[y0 + page_y0 : y0 + page_y1, x0 + page_x0 : x0 + page_x1].copy())


def _single_page_fallback(
    image: Image.Image,
    *,
    reason: str,
    bounds: tuple[int, int, int, int] | None,
) -> BookSplitResult:
    geometry = _boundary_geometry(np.asarray(image.convert("RGB")))
    dewarp = DewarpResult(image.copy(), False, geometry.score, geometry.score, reason)
    return BookSplitResult(
        pages=(LogicalBookPage("single", image.copy(), dewarp),),
        split_detected=False,
        spine_x=None,
        confidence=0.0,
        reason=reason,
        book_bounds=bounds,
    )


def split_book_spread(
    image: Image.Image,
    *,
    reading_order: ReadingOrder = "left_to_right",
    minimum_spine_contrast: float = 18.0,
    minimum_side_coverage: float = 0.35,
) -> BookSplitResult:
    """估计非中心书脊并拆成两个逻辑页；低置信时保留单页原图。"""

    if reading_order not in {"left_to_right", "right_to_left"}:
        raise ValueError("阅读顺序必须是 left_to_right 或 right_to_left")
    if not 0 < minimum_spine_contrast <= 255:
        raise ValueError("书脊对比度阈值必须位于 0 到 255")
    if not 0 < minimum_side_coverage <= 1:
        raise ValueError("单侧覆盖率阈值必须位于 0 到 1")

    rgb = np.asarray(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    mask = _page_mask(rgb)
    bounds = _book_bounds(mask)
    if bounds is None:
        return _single_page_fallback(image, reason="book_outline_not_found", bounds=None)
    x0, y0, x1, y1 = bounds
    book_width = x1 - x0
    if book_width < 160:
        return _single_page_fallback(image, reason="book_too_narrow", bounds=bounds)

    profile_region = gray[y0:y1, x0:x1]
    vertical_profile = np.median(profile_region, axis=0).astype(np.float32)
    smoothing_width = max(9, (book_width // 40) | 1)
    vertical_profile = cv2.GaussianBlur(
        vertical_profile[np.newaxis, :], (smoothing_width, 1), 0
    ).ravel()
    candidate_start = round(book_width * 0.20)
    candidate_end = round(book_width * 0.80)
    candidate_profile = vertical_profile[candidate_start:candidate_end]
    local_minimum = float(candidate_profile.min())
    valley = np.flatnonzero(candidate_profile <= local_minimum + 3)
    local_spine = candidate_start + round(float(valley.mean()))
    spine_x = x0 + local_spine

    left_reference = vertical_profile[round(book_width * 0.05) : round(book_width * 0.35)]
    right_reference = vertical_profile[round(book_width * 0.65) : round(book_width * 0.95)]
    page_brightness = (
        float(np.percentile(left_reference, 75)) + float(np.percentile(right_reference, 75))
    ) / 2
    spine_contrast = page_brightness - float(vertical_profile[local_spine])

    local_mask = mask[y0:y1, x0:x1]
    left_coverage = float(
        np.count_nonzero(local_mask[:, :local_spine]) / max(1, local_mask[:, :local_spine].size)
    )
    right_coverage = float(
        np.count_nonzero(local_mask[:, local_spine:]) / max(1, local_mask[:, local_spine:].size)
    )
    if spine_contrast < minimum_spine_contrast:
        return _single_page_fallback(image, reason="spine_not_confident", bounds=bounds)
    if min(left_coverage, right_coverage) < minimum_side_coverage:
        return _single_page_fallback(image, reason="one_side_missing", bounds=bounds)

    contrast_score = min(1.0, spine_contrast / 80)
    coverage_score = min(1.0, min(left_coverage, right_coverage) / 0.70)
    confidence = round(contrast_score * coverage_score, 6)
    left_image = _crop_page(rgb, mask, (x0, y0, spine_x, y1))
    right_image = _crop_page(rgb, mask, (spine_x, y0, x1, y1))
    left_page = LogicalBookPage("left", left_image, conservative_dewarp_page(left_image))
    right_page = LogicalBookPage("right", right_image, conservative_dewarp_page(right_image))
    pages = (left_page, right_page)
    if reading_order == "right_to_left":
        pages = (right_page, left_page)
    return BookSplitResult(
        pages=pages,
        split_detected=True,
        spine_x=spine_x,
        confidence=confidence,
        reason="spread_split",
        book_bounds=bounds,
    )
