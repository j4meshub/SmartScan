from __future__ import annotations

from typing import Any

from .tasks import StructuredTask


def deterministic_mock_result(task: StructuredTask) -> dict[str, Any]:
    """生成保守、可重复且不读取媒体内容的本机试用结果。"""

    task_type = task.task_type.value
    common: dict[str, Any] = {
        "schema_version": "1.0",
        "task_id": str(task.task_id),
        "task_type": task_type,
        "confidence": 0.99,
    }
    if task_type == "classify_page":
        return {
            **common,
            "label": "ordinary_document",
            "evidence_codes": ["ordinary_layout"],
        }
    if task_type == "detect_orientation":
        return {
            **common,
            "rotation_degrees": 0,
            "evidence_codes": ["insufficient_evidence"],
        }
    if task_type == "extract_title":
        return {
            **common,
            "candidates": [
                {
                    "text": "模拟 AI 建议标题",
                    "confidence": 0.99,
                    "source": "header",
                }
            ],
        }
    if task_type == "extract_page_number":
        return {**common, "status": "not_detected"}
    if task_type == "ocr_formula":
        return {**common, "blocks": []}
    if task_type == "review_cleanup_mask":
        return {
            **common,
            "decisions": [
                {
                    "region_id": candidate.region_id,
                    "region_type": "unknown",
                    "action": "review",
                    "confidence": 0.99,
                }
                for candidate in task.parameters.candidates
            ],
        }
    if task_type == "review_book_split":
        return {
            **common,
            "decision": "uncertain",
            "reading_order": task.parameters.reading_order,
        }
    raise ValueError("mock_task_type_unsupported")
