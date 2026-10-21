from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageOps

from .ocr import OcrAnalysis

ARABIC_PATTERNS = (
    re.compile(r"^(?:第\s*)?(\d{1,5})(?:\s*页)?$", re.IGNORECASE),
    re.compile(r"^page\s+(\d{1,5})(?:\s*(?:of|/)\s*\d{1,5})?$", re.IGNORECASE),
    re.compile(r"^(\d{1,5})\s*/\s*\d{1,5}$", re.IGNORECASE),
)
ROMAN_PATTERN = re.compile(r"^[ivxlcdm]{1,12}$", re.IGNORECASE)


@dataclass(frozen=True)
class PrintedPageNumber:
    status: str
    label: str | None = None
    value: int | None = None
    kind: str | None = None
    confidence: float | None = None
    reason: str | None = None


def _roman_value(candidate: str) -> int | None:
    normalized = candidate.upper()
    if not ROMAN_PATTERN.fullmatch(normalized):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for character in reversed(normalized):
        value = values[character]
        total += -value if value < previous else value
        previous = max(previous, value)
    if total <= 0 or total > 3999 or _to_roman(total) != normalized:
        return None
    return total


def _to_roman(value: int) -> str:
    parts: list[str] = []
    for number, token in (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ):
        while value >= number:
            parts.append(token)
            value -= number
    return "".join(parts)


def normalize_printed_page_label(label: str) -> tuple[str, int, str] | None:
    compact = re.sub(r"\s+", " ", label.strip())
    for pattern in ARABIC_PATTERNS:
        match = pattern.fullmatch(compact)
        if match:
            value = int(match.group(1))
            if 0 < value <= 99999:
                return str(value), value, "arabic"
    value = _roman_value(compact.replace(" ", ""))
    if value is not None:
        return compact.replace(" ", "").lower(), value, "roman"
    return None


def extract_printed_page_number(
    analysis: OcrAnalysis | None,
    *,
    minimum_confidence: float = 0.60,
) -> PrintedPageNumber:
    if analysis is None:
        return PrintedPageNumber(status="disabled", reason="ocr_disabled")
    details = analysis.details
    size = details.get("selected_image_size")
    lines = details.get("lines")
    if (
        not isinstance(size, list)
        or len(size) != 2
        or not all(isinstance(item, (int, float)) for item in size)
        or not isinstance(lines, list)
    ):
        return PrintedPageNumber(status="ambiguous", reason="ocr_geometry_missing")
    width, height = float(size[0]), float(size[1])
    if width <= 0 or height <= 0:
        return PrintedPageNumber(status="ambiguous", reason="ocr_geometry_invalid")
    candidates: list[tuple[float, float, str, int, str]] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        text = line.get("text")
        confidence = line.get("confidence")
        box = line.get("box")
        if (
            not isinstance(text, str)
            or not isinstance(confidence, (int, float))
            or float(confidence) < minimum_confidence
            or not isinstance(box, list)
            or len(box) != 4
            or not all(isinstance(item, (int, float)) for item in box)
        ):
            continue
        normalized = normalize_printed_page_label(text)
        if normalized is None:
            continue
        x_min, y_min, x_max, y_max = (float(item) for item in box)
        center_x = (x_min + x_max) / 2
        center_y = (y_min + y_max) / 2
        if not (center_y <= height * 0.20 or center_y >= height * 0.78):
            continue
        edge_distance = min(center_x, max(width - center_x, 0.0)) / width
        vertical_score = (
            1.0 - center_y / max(height * 0.20, 1.0)
            if center_y <= height * 0.20
            else (center_y - height * 0.78) / max(height * 0.22, 1.0)
        )
        label, value, kind = normalized
        score = float(confidence) * 0.75 + min(max(vertical_score, 0.0), 1.0) * 0.20
        score += min(edge_distance, 0.5) * 0.10
        candidates.append((score, float(confidence), label, value, kind))
    if not candidates:
        return PrintedPageNumber(status="none", reason="no_common_region_candidate")
    candidates.sort(reverse=True)
    best = candidates[0]
    different = [item for item in candidates[1:] if (item[3], item[4]) != (best[3], best[4])]
    if different and different[0][0] >= best[0] - 0.04:
        return PrintedPageNumber(status="ambiguous", reason="multiple_close_candidates")
    return PrintedPageNumber(
        status="ready",
        label=best[2],
        value=best[3],
        kind=best[4],
        confidence=round(best[1], 6),
        reason="common_page_number_region",
    )


def image_dhash(image: Image.Image) -> str:
    sample = ImageOps.grayscale(image).resize((9, 8), Image.Resampling.LANCZOS)
    flattened = getattr(sample, "get_flattened_data", None)
    pixels = list(flattened() if callable(flattened) else sample.getdata())
    bits = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            bits = (bits << 1) | int(pixels[offset + column] > pixels[offset + column + 1])
    return f"{bits:016x}"


def fingerprint_distance(left: str | None, right: str | None) -> int | None:
    if (
        not left
        or not right
        or not re.fullmatch(r"[a-f0-9]{16}", left)
        or not re.fullmatch(r"[a-f0-9]{16}", right)
    ):
        return None
    return (int(left, 16) ^ int(right, 16)).bit_count()


def page_number_evidence(result: PrintedPageNumber) -> dict[str, Any]:
    return {
        "status": result.status,
        "label": result.label,
        "value": result.value,
        "kind": result.kind,
        "confidence": result.confidence,
        "reason": result.reason,
    }
