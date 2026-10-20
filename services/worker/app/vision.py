from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class PerspectiveResult:
    image: Image.Image
    detected: bool
    confidence: float


def _order_corners(points: np.ndarray) -> np.ndarray:
    points = points.reshape(4, 2).astype(np.float32)
    ordered_by_y = points[np.argsort(points[:, 1])]
    top = ordered_by_y[:2][np.argsort(ordered_by_y[:2, 0])]
    bottom = ordered_by_y[2:][np.argsort(ordered_by_y[2:, 0])]
    return np.array([top[0], top[1], bottom[1], bottom[0]], dtype=np.float32)


def detect_document_corners(
    image: Image.Image,
    *,
    min_area_ratio: float = 0.2,
    max_detection_dimension: int = 1600,
) -> tuple[np.ndarray, float] | None:
    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    scale = min(1.0, max_detection_dimension / max(height, width))
    if scale < 1.0:
        sample = cv2.resize(
            rgb,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        sample = rgb

    gray = cv2.cvtColor(sample, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    median = float(np.median(blurred))
    lower = max(20, int(median * 0.55))
    upper = min(240, max(lower + 40, int(median * 1.45)))
    edges = cv2.Canny(blurred, lower, upper)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    sample_area = float(sample.shape[0] * sample.shape[1])
    candidates: list[tuple[float, np.ndarray]] = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:20]:
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        area_ratio = abs(cv2.contourArea(polygon)) / sample_area
        if area_ratio < min_area_ratio:
            continue
        ordered = _order_corners(polygon)
        side_lengths = [
            np.linalg.norm(ordered[index] - ordered[(index + 1) % 4]) for index in range(4)
        ]
        if min(side_lengths) < 40:
            continue
        candidates.append((area_ratio, ordered))

    if not candidates:
        return None
    area_ratio, corners = max(candidates, key=lambda item: item[0])
    confidence = min(1.0, area_ratio / 0.65)
    return corners / scale, confidence


def _warp_document(image: Image.Image, corners: np.ndarray) -> Image.Image:
    top_left, top_right, bottom_right, bottom_left = corners
    width = round(
        max(
            np.linalg.norm(top_right - top_left),
            np.linalg.norm(bottom_right - bottom_left),
        )
    )
    height = round(
        max(
            np.linalg.norm(bottom_left - top_left),
            np.linalg.norm(bottom_right - top_right),
        )
    )
    width = max(64, width)
    height = max(64, height)
    output_scale = min(1.0, 8000 / max(width, height))
    width = max(64, round(width * output_scale))
    height = max(64, round(height * output_scale))
    target = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(corners.astype(np.float32), target)
    rgb = np.asarray(image.convert("RGB"))
    corrected = cv2.warpPerspective(
        rgb,
        transform,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return Image.fromarray(corrected)


def correct_document_perspective(
    image: Image.Image,
    *,
    min_area_ratio: float = 0.2,
    max_detection_dimension: int = 1600,
) -> PerspectiveResult:
    detection = detect_document_corners(
        image,
        min_area_ratio=min_area_ratio,
        max_detection_dimension=max_detection_dimension,
    )
    if detection is None:
        return PerspectiveResult(image=image.copy(), detected=False, confidence=0.0)
    corners, confidence = detection
    return PerspectiveResult(
        image=_warp_document(image, corners),
        detected=True,
        confidence=confidence,
    )
