import cv2
import numpy as np
from PIL import Image

from services.worker.app.main import quality_warning
from services.worker.app.vision import correct_document_perspective, detect_document_corners


def synthetic_document() -> Image.Image:
    canvas = np.full((900, 1200, 3), 35, dtype=np.uint8)
    corners = np.array([[220, 110], [990, 190], [1060, 760], [150, 810]], dtype=np.int32)
    cv2.fillConvexPoly(canvas, corners, (245, 245, 240))
    for offset in range(0, 360, 60):
        cv2.line(canvas, (300, 260 + offset), (900, 300 + offset), (40, 40, 40), 8)
    return Image.fromarray(canvas)


def test_detects_and_corrects_skewed_document():
    image = synthetic_document()

    detection = detect_document_corners(image)
    result = correct_document_perspective(image)

    assert detection is not None
    corners, confidence = detection
    assert corners.shape == (4, 2)
    assert confidence >= 0.5
    assert result.detected is True
    assert result.image.width < image.width
    assert result.image.height < image.height
    assert result.image.width > 700
    assert result.image.height > 550


def test_preserves_image_when_document_edges_are_not_found():
    image = Image.new("RGB", (800, 600), (128, 128, 128))

    result = correct_document_perspective(image)

    assert result.detected is False
    assert result.confidence == 0.0
    assert result.image.size == image.size


def test_missing_edges_are_marked_for_review_after_quality_checks():
    pixels = np.full((1100, 1100, 3), 245, dtype=np.uint8)
    pixels[300:800, 300:800] = 20
    image = Image.fromarray(pixels)

    warning = quality_warning(
        image,
        document_edges_required=True,
        document_edges_detected=False,
    )

    assert warning == "document_edges_not_found"
