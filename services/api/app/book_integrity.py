from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.worker.app.book_integrity import fingerprint_distance

from .export_service import ExportError, create_export
from .models import (
    BookIntegrityDecision,
    ExportStatus,
    ScanExport,
    ScanPage,
    ScanProject,
    User,
)
from .schemas import BookIntegrityIssueView, BookIntegrityReport


class BookIntegrityError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class _Issue:
    key: str
    kind: str
    severity: str
    message_code: str
    page_id: str | None = None
    related_page_id: str | None = None
    printed_page_label: str | None = None
    details: dict[str, object] | None = None


def _current_pages(db: Session, project: ScanProject) -> list[ScanPage]:
    return list(
        db.scalars(
            select(ScanPage)
            .where(
                ScanPage.project_id == project.id,
                ScanPage.book_replaced_by_page_id.is_(None),
            )
            .order_by(ScanPage.page_number, ScanPage.id)
        )
    )


def _issue_key(kind: str, *parts: object) -> str:
    raw = ":".join([kind, *(str(part) for part in parts)])
    return f"{kind}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _number_is_current(page: ScanPage) -> bool:
    return (
        page.book_page_number_status == "ready"
        and page.book_page_number_result_version == page.active_result_version
        and page.book_page_number_label is not None
        and page.book_page_number_value is not None
        and page.book_page_number_kind is not None
    )


def _fingerprint_is_current(page: ScanPage) -> bool:
    return (
        page.book_content_fingerprint is not None
        and page.book_fingerprint_result_version == page.active_result_version
    )


def _detect_issues(pages: list[ScanPage], reading_order: str) -> list[_Issue]:
    issues: list[_Issue] = []
    included = [page for page in pages if page.book_assembly_included]
    for page in pages:
        if page.book_split_status == "fallback":
            issues.append(
                _Issue(
                    key=_issue_key("missing_side", page.id),
                    kind="missing_side",
                    severity="error",
                    message_code="book_issue_missing_side",
                    page_id=page.id,
                    details={"logical_page_number": page.page_number},
                )
            )
        if page.review_status.value == "pending" or page.quality_warning:
            issues.append(
                _Issue(
                    key=_issue_key("quality_review", page.id, page.active_result_version),
                    kind="quality_review",
                    severity="warning",
                    message_code="book_issue_quality_review",
                    page_id=page.id,
                    details={
                        "logical_page_number": page.page_number,
                        "quality_warning": page.quality_warning,
                    },
                )
            )
        if page.book_page_number_status == "ambiguous":
            issues.append(
                _Issue(
                    key=_issue_key("number_ambiguous", page.id, page.active_result_version),
                    kind="number_ambiguous",
                    severity="warning",
                    message_code="book_issue_number_ambiguous",
                    page_id=page.id,
                    details={"reason": page.book_page_number_reason},
                )
            )
        if page.book_expected_page_label:
            actual = page.book_page_number_label if _number_is_current(page) else None
            if actual != page.book_expected_page_label:
                issues.append(
                    _Issue(
                        key=_issue_key(
                            "expected_number_mismatch",
                            page.id,
                            page.book_expected_page_label,
                            actual or "none",
                        ),
                        kind="expected_number_mismatch",
                        severity="error",
                        message_code="book_issue_expected_number_mismatch",
                        page_id=page.id,
                        printed_page_label=page.book_expected_page_label,
                        details={"actual_page_label": actual},
                    )
                )

    numbered = [page for page in included if _number_is_current(page)]
    for left, right in itertools.pairwise(numbered):
        if left.book_page_number_kind != right.book_page_number_kind:
            continue
        assert left.book_page_number_value is not None and right.book_page_number_value is not None
        delta = right.book_page_number_value - left.book_page_number_value
        logical_delta = right.page_number - left.page_number
        if delta < 0:
            issues.append(
                _Issue(
                    key=_issue_key("number_order_conflict", left.id, right.id),
                    kind="number_order_conflict",
                    severity="error",
                    message_code="book_issue_number_order_conflict",
                    page_id=left.id,
                    related_page_id=right.id,
                    details={
                        "left_label": left.book_page_number_label,
                        "right_label": right.book_page_number_label,
                        "reading_order": reading_order,
                    },
                )
            )
        elif logical_delta == 1 and 1 < delta <= 10:
            for missing_value in range(
                left.book_page_number_value + 1, right.book_page_number_value
            ):
                label = (
                    str(missing_value)
                    if left.book_page_number_kind == "arabic"
                    else _roman_label(missing_value)
                )
                issues.append(
                    _Issue(
                        key=_issue_key("missing_page", left.book_page_number_kind, missing_value),
                        kind="missing_page",
                        severity="error",
                        message_code="book_issue_missing_page",
                        page_id=left.id,
                        related_page_id=right.id,
                        printed_page_label=label,
                        details={"number_kind": left.book_page_number_kind},
                    )
                )
        elif logical_delta == 1 and delta > 10:
            issues.append(
                _Issue(
                    key=_issue_key("number_gap_uncertain", left.id, right.id),
                    kind="number_gap_uncertain",
                    severity="warning",
                    message_code="book_issue_number_gap_uncertain",
                    page_id=left.id,
                    related_page_id=right.id,
                    details={
                        "left_label": left.book_page_number_label,
                        "right_label": right.book_page_number_label,
                    },
                )
            )

    for index, left in enumerate(pages):
        if not left.book_assembly_included or not _fingerprint_is_current(left):
            continue
        for right in pages[index + 1 :]:
            if left.book_capture_id and left.book_capture_id == right.book_capture_id:
                continue
            if not _fingerprint_is_current(right):
                continue
            distance = fingerprint_distance(
                left.book_content_fingerprint, right.book_content_fingerprint
            )
            if distance is None:
                continue
            same_number = (
                _number_is_current(left)
                and _number_is_current(right)
                and left.book_page_number_kind == right.book_page_number_kind
                and left.book_page_number_value == right.book_page_number_value
            )
            if same_number and distance <= 8:
                kind = "duplicate_page"
                message = "book_issue_duplicate_page"
            elif same_number:
                kind = "number_conflict"
                message = "book_issue_number_conflict"
            elif distance <= 3:
                kind = "duplicate_page"
                message = "book_issue_duplicate_page"
            else:
                continue
            issues.append(
                _Issue(
                    key=_issue_key(kind, left.id, right.id),
                    kind=kind,
                    severity="error",
                    message_code=message,
                    page_id=left.id,
                    related_page_id=right.id,
                    printed_page_label=(left.book_page_number_label if same_number else None),
                    details={
                        "fingerprint_distance": distance,
                        "left_logical_page_number": left.page_number,
                        "right_logical_page_number": right.page_number,
                    },
                )
            )
    return issues


def _roman_label(value: int) -> str:
    result = ""
    for number, token in (
        (1000, "m"),
        (900, "cm"),
        (500, "d"),
        (400, "cd"),
        (100, "c"),
        (90, "xc"),
        (50, "l"),
        (40, "xl"),
        (10, "x"),
        (9, "ix"),
        (5, "v"),
        (4, "iv"),
        (1, "i"),
    ):
        while value >= number:
            result += token
            value -= number
    return result


def build_book_integrity_report(db: Session, project: ScanProject) -> BookIntegrityReport:
    if project.mode != "book":
        raise BookIntegrityError("book_integrity_requires_book_project")
    pages = _current_pages(db, project)
    decisions = {
        item.issue_key: item
        for item in db.scalars(
            select(BookIntegrityDecision).where(BookIntegrityDecision.project_id == project.id)
        )
    }
    detected = _detect_issues(pages, project.reading_order)
    views: list[BookIntegrityIssueView] = []
    for issue in detected:
        decision = decisions.get(issue.key)
        decision_value = decision.decision if decision is not None else None
        blocking = decision_value is None
        views.append(
            BookIntegrityIssueView(
                key=issue.key,
                kind=issue.kind,
                severity=issue.severity,
                message_code=issue.message_code,
                page_id=issue.page_id,
                related_page_id=issue.related_page_id,
                printed_page_label=issue.printed_page_label,
                decision=decision_value,
                blocking=blocking,
                details=issue.details or {},
            )
        )
    included = [page for page in pages if page.book_assembly_included]
    ready_pages = [page for page in included if page.active_result_version > 0]
    blocking_count = sum(item.blocking for item in views)
    processing_count = len(included) - len(ready_pages)
    return BookIntegrityReport(
        project_id=project.id,
        pages_checked=len(pages),
        included_page_count=len(included),
        visible_page_number_count=sum(_number_is_current(page) for page in included),
        processing_page_count=processing_count,
        open_issue_count=sum(item.decision is None for item in views),
        blocking_issue_count=blocking_count + processing_count,
        ready_to_assemble=bool(included) and blocking_count == 0 and processing_count == 0,
        issues=views,
        generated_at=datetime.now(UTC),
    )


def apply_book_integrity_decision(
    db: Session,
    *,
    actor: User,
    project: ScanProject,
    issue_key: str,
    decision: str,
) -> BookIntegrityReport:
    report = build_book_integrity_report(db, project)
    issue = next((item for item in report.issues if item.key == issue_key), None)
    existing = db.scalar(
        select(BookIntegrityDecision).where(
            BookIntegrityDecision.project_id == project.id,
            BookIntegrityDecision.issue_key == issue_key,
        )
    )
    if decision == "reopen":
        if existing is None:
            raise BookIntegrityError("book_integrity_decision_not_found", status_code=404)
        if existing.decision == "exclude_duplicate":
            details = json.loads(existing.details or "{}")
            related_page_id = details.get("related_page_id")
            page = db.get(ScanPage, related_page_id) if isinstance(related_page_id, str) else None
            if page is not None and page.project_id == project.id:
                page.book_assembly_included = True
                page.book_assembly_exclusion_reason = None
        db.delete(existing)
        project.updated_at = datetime.now(UTC)
        db.flush()
        return build_book_integrity_report(db, project)
    if issue is None:
        raise BookIntegrityError("book_integrity_issue_not_current")
    allowed = {"ignored"}
    if issue.kind == "missing_page":
        allowed.add("confirmed_absent")
    if issue.kind in {"duplicate_page", "number_conflict"}:
        allowed.update({"keep_both", "exclude_duplicate"})
    if decision not in allowed:
        raise BookIntegrityError("book_integrity_decision_invalid", status_code=422)
    details = {
        "page_id": issue.page_id,
        "related_page_id": issue.related_page_id,
        "printed_page_label": issue.printed_page_label,
    }
    if decision == "exclude_duplicate":
        page = db.get(ScanPage, issue.related_page_id) if issue.related_page_id else None
        if page is None or page.project_id != project.id:
            raise BookIntegrityError("book_integrity_related_page_missing", status_code=404)
        page.book_assembly_included = False
        page.book_assembly_exclusion_reason = issue.kind
    elif decision == "keep_both" and issue.related_page_id:
        page = db.get(ScanPage, issue.related_page_id)
        if page is not None and page.project_id == project.id:
            page.book_assembly_included = True
            page.book_assembly_exclusion_reason = None
    now = datetime.now(UTC)
    if existing is None:
        existing = BookIntegrityDecision(
            owner_user_id=actor.id,
            project_id=project.id,
            issue_key=issue.key,
            issue_kind=issue.kind,
            decision=decision,
            details=json.dumps(details, sort_keys=True, separators=(",", ":")),
            decided_by_user_id=actor.id,
            decided_at=now,
        )
        db.add(existing)
    else:
        existing.issue_kind = issue.kind
        existing.decision = decision
        existing.details = json.dumps(details, sort_keys=True, separators=(",", ":"))
        existing.decided_by_user_id = actor.id
        existing.decided_at = now
    project.updated_at = now
    db.flush()
    return build_book_integrity_report(db, project)


def _assembly_signature(pages: list[ScanPage], *, quality: str, include_ocr_text: bool) -> str:
    snapshot = {
        "quality": quality,
        "include_ocr_text": include_ocr_text,
        "pages": [
            {
                "id": page.id,
                "order": page.page_number,
                "result": page.active_result_version,
                "ocr": page.ocr_result_version if include_ocr_text else None,
            }
            for page in pages
        ],
    }
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_book_assembly(
    db: Session,
    *,
    actor: User,
    project: ScanProject,
    quality: str,
    include_ocr_text: bool,
) -> ScanExport:
    report = build_book_integrity_report(db, project)
    if not report.ready_to_assemble:
        raise BookIntegrityError("book_integrity_unresolved")
    pages = [page for page in _current_pages(db, project) if page.book_assembly_included]
    signature = _assembly_signature(pages, quality=quality, include_ocr_text=include_ocr_text)
    existing = db.scalar(
        select(ScanExport).where(
            ScanExport.project_id == project.id,
            ScanExport.book_assembly_signature == signature,
            ScanExport.status == ExportStatus.ready,
        )
    )
    if existing is not None:
        return existing
    previous = db.scalar(
        select(ScanExport)
        .where(
            ScanExport.project_id == project.id,
            ScanExport.book_assembly_revision.is_not(None),
        )
        .order_by(ScanExport.book_assembly_revision.desc(), ScanExport.created_at.desc())
    )
    revision = (previous.book_assembly_revision or 0) + 1 if previous is not None else 1
    try:
        return create_export(
            db,
            actor=actor,
            project=project,
            format="pdf",
            quality=quality,
            include_ocr_text=include_ocr_text,
            page_ids=[page.id for page in pages],
            book_assembly_signature=signature,
            book_assembly_revision=revision,
            book_previous_export_id=previous.id if previous is not None else None,
        )
    except ExportError as exc:
        raise BookIntegrityError(exc.code, status_code=exc.status_code) from exc
