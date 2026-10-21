from __future__ import annotations

import hashlib
import io
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageOps
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.worker.app.ocr import sanitize_title_candidate

from .config import Settings, get_settings
from .models import (
    ExportArtifact,
    ExportStatus,
    PageResult,
    ScanExport,
    ScanPage,
    ScanProject,
    User,
)

PROCESSOR_VERSION = "export-v1"
QUALITY_PROFILES = {
    "clear": (None, 95),
    "balanced": (2400, 85),
    "small": (1600, 72),
}


class ExportError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class _PageSource:
    page: ScanPage
    result: PageResult
    source: Path
    ocr_lines: tuple[dict[str, object], ...]


def _safe_storage_path(settings: Settings, relative: str) -> Path:
    root = settings.storage_root.resolve()
    absolute = (root / relative).resolve()
    if root not in absolute.parents:
        raise ExportError("export_file_path_invalid", status_code=500)
    return absolute


def _base_file_name(project: ScanProject, now: datetime) -> str:
    candidate = sanitize_title_candidate(project.title) or sanitize_title_candidate(
        project.suggested_name or ""
    )
    base = candidate or "智能扫描"
    base = re.sub(r"\s+", "_", base).strip(" ._")[:80] or "智能扫描"
    return f"{base}_{now:%Y%m%d}"


def _load_ocr_lines(page: ScanPage) -> tuple[dict[str, object], ...]:
    if (
        page.ocr_status != "ready"
        or page.ocr_result_version != page.active_result_version
        or not page.ocr_details
    ):
        return ()
    try:
        details = json.loads(page.ocr_details)
    except json.JSONDecodeError:
        return ()
    lines = details.get("lines") if isinstance(details, dict) else None
    if not isinstance(lines, list):
        return ()
    accepted: list[dict[str, object]] = []
    for line in lines[:2000]:
        if not isinstance(line, dict):
            continue
        text = line.get("text")
        box = line.get("box")
        if (
            not isinstance(text, str)
            or not text.strip()
            or not isinstance(box, list)
            or len(box) != 4
        ):
            continue
        if not all(isinstance(value, (int, float)) for value in box):
            continue
        accepted.append({"text": text[:512], "box": [float(value) for value in box]})
    return tuple(accepted)


def _select_pages(
    db: Session,
    *,
    project: ScanProject,
    page_ids: list[str] | None,
    settings: Settings,
) -> list[_PageSource]:
    pages = list(
        db.scalars(
            select(ScanPage)
            .where(
                ScanPage.project_id == project.id,
                ScanPage.book_replaced_by_page_id.is_(None),
            )
            .order_by(ScanPage.page_number, ScanPage.id)
        )
    )
    if page_ids is not None:
        if len(set(page_ids)) != len(page_ids):
            raise ExportError("export_page_ids_duplicated", status_code=422)
        requested = set(page_ids)
        pages = [page for page in pages if page.id in requested]
        if len(pages) != len(requested):
            raise ExportError("export_page_not_found", status_code=404)
    if not pages:
        raise ExportError("export_pages_empty")
    sources: list[_PageSource] = []
    for page in pages:
        if page.active_result_version <= 0:
            raise ExportError("export_page_not_ready")
        result = db.scalar(
            select(PageResult).where(
                PageResult.page_id == page.id,
                PageResult.version == page.active_result_version,
            )
        )
        if result is None:
            raise ExportError("export_page_result_missing", status_code=500)
        source = _safe_storage_path(settings, result.file_path)
        if not source.is_file():
            raise ExportError("export_page_file_missing", status_code=404)
        sources.append(_PageSource(page, result, source, _load_ocr_lines(page)))
    return sources


def _render_image(source: Path, quality: str) -> tuple[Image.Image, bytes]:
    max_dimension, jpeg_quality = QUALITY_PROFILES[quality]
    with Image.open(source) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
        if max_dimension is not None and max(image.size) > max_dimension:
            image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        rendered = image.copy()
    payload = io.BytesIO()
    rendered.save(payload, "JPEG", quality=jpeg_quality, optimize=True)
    return rendered, payload.getvalue()


def _write_atomic(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    incoming = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.incoming")
    try:
        incoming.write_bytes(payload)
        os.replace(incoming, destination)
    finally:
        incoming.unlink(missing_ok=True)


def _pdf_payload(rendered_pages: list[tuple[Image.Image, bytes, _PageSource]]) -> bytes:
    output = io.BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    document = canvas.Canvas(output, pageCompression=1)
    for image, jpeg, source in rendered_pages:
        width, height = image.size
        document.setPageSize((width, height))
        document.drawImage(ImageReader(io.BytesIO(jpeg)), 0, 0, width=width, height=height)
        with Image.open(source.source) as source_image:
            source_width, source_height = source_image.size
        x_scale = width / source_width
        y_scale = height / source_height
        for line in source.ocr_lines:
            x_min, y_min, _x_max, y_max = line["box"]
            font_size = max(4.0, min((y_max - y_min) * y_scale * 0.85, 72.0))
            text = document.beginText()
            text.setTextRenderMode(3)
            text.setFont("STSong-Light", font_size)
            text.setTextOrigin(x_min * x_scale, height - y_max * y_scale)
            text.textOut(str(line["text"]))
            document.drawText(text)
        document.showPage()
    document.save()
    return output.getvalue()


def create_export(
    db: Session,
    *,
    actor: User,
    project: ScanProject,
    format: str,
    quality: str,
    include_ocr_text: bool,
    page_ids: list[str] | None,
    book_assembly_signature: str | None = None,
    book_assembly_revision: int | None = None,
    book_previous_export_id: str | None = None,
    settings: Settings | None = None,
) -> ScanExport:
    settings = settings or get_settings()
    if project.owner_user_id != actor.id:
        raise ExportError("project_not_found", status_code=404)
    sources = _select_pages(db, project=project, page_ids=page_ids, settings=settings)
    now = datetime.now(UTC)
    snapshot = [
        {
            "page_id": source.page.id,
            "page_number": source.page.page_number,
            "result_version": source.result.version,
            "ocr_result_version": (
                source.page.ocr_result_version if include_ocr_text and source.ocr_lines else None
            ),
        }
        for source in sources
    ]
    export = ScanExport(
        owner_user_id=actor.id,
        project_id=project.id,
        format=format,
        quality=quality,
        include_ocr_text=include_ocr_text,
        status=ExportStatus.generating,
        page_count=len(sources),
        ocr_pages_used=sum(bool(source.ocr_lines) for source in sources) if include_ocr_text else 0,
        base_file_name=_base_file_name(project, now),
        page_snapshot=json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
        processor_version=(
            "export-v2-book-assembly" if book_assembly_signature is not None else PROCESSOR_VERSION
        ),
        book_assembly_signature=book_assembly_signature,
        book_assembly_revision=book_assembly_revision,
        book_previous_export_id=book_previous_export_id,
        created_at=now,
    )
    db.add(export)
    db.flush()
    rendered_pages: list[tuple[Image.Image, bytes, _PageSource]] = []
    destinations: list[Path] = []
    try:
        for source in sources:
            image, payload = _render_image(source.source, quality)
            rendered_pages.append((image, payload, source))
        outputs: list[tuple[str, str, bytes, str | None]] = []
        if format == "jpg":
            for sequence, (_, payload, source) in enumerate(rendered_pages, start=1):
                suffix = f"_{sequence:03d}" if len(rendered_pages) > 1 else ""
                outputs.append(
                    (f"{export.base_file_name}{suffix}.jpg", "image/jpeg", payload, source.page.id)
                )
        else:
            pdf_pages = [
                (image, payload, source)
                if include_ocr_text
                else (image, payload, _PageSource(source.page, source.result, source.source, ()))
                for image, payload, source in rendered_pages
            ]
            outputs.append(
                (f"{export.base_file_name}.pdf", "application/pdf", _pdf_payload(pdf_pages), None)
            )
        for sequence, (file_name, mime_type, payload, page_id) in enumerate(outputs, start=1):
            relative = Path("users") / actor.id / "exports" / export.id / file_name
            destination = _safe_storage_path(settings, relative.as_posix())
            _write_atomic(destination, payload)
            destinations.append(destination)
            db.add(
                ExportArtifact(
                    export_id=export.id,
                    owner_user_id=actor.id,
                    page_id=page_id,
                    sequence=sequence,
                    file_name=file_name,
                    file_path=relative.as_posix(),
                    mime_type=mime_type,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    size_bytes=len(payload),
                    created_at=now,
                )
            )
        export.status = ExportStatus.ready
        export.completed_at = now
        db.commit()
        db.refresh(export)
        return export
    except ExportError:
        db.rollback()
        for destination in destinations:
            destination.unlink(missing_ok=True)
        raise
    except Exception as exc:
        db.rollback()
        for destination in destinations:
            destination.unlink(missing_ok=True)
        raise ExportError("export_generation_failed", status_code=500) from exc
