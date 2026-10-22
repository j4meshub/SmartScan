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
        english = task.context.locale == "en"
        return {
            **common,
            "blocks": [
                {
                    "block_type": "formula",
                    "block_id": "mock-formula-1",
                    "box": {"x0": 0.1, "y0": 0.12, "x1": 0.9, "y1": 0.28},
                    "confidence": 0.99,
                    "latex_candidate": r"\mathrm{Mock}: x^2+y^2=z^2",
                },
                {
                    "block_type": "table",
                    "block_id": "mock-table-1",
                    "box": {"x0": 0.1, "y0": 0.35, "x1": 0.9, "y1": 0.58},
                    "confidence": 0.99,
                    "cells": [
                        {
                            "row": 0,
                            "column": 0,
                            "text_candidate": "Mock field" if english else "模拟字段",
                        },
                        {
                            "row": 0,
                            "column": 1,
                            "text_candidate": "Mock value" if english else "模拟值",
                        },
                    ],
                },
                {
                    "block_type": "layout",
                    "block_id": "mock-layout-1",
                    "box": {"x0": 0.1, "y0": 0.68, "x1": 0.9, "y1": 0.84},
                    "confidence": 0.99,
                    "role": "paragraph",
                    "text_candidate": (
                        "Simulated AI layout candidate" if english else "模拟 AI 版面候选"
                    ),
                },
            ],
        }
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
