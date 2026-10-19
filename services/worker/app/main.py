from __future__ import annotations

import signal
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from sqlalchemy import or_, select

from services.api.app.config import get_settings
from services.api.app.database import Base, SessionLocal, engine
from services.api.app.models import JobStatus, ProcessingJob, ScanPage

settings = get_settings()
running = True


def stop(*_: object) -> None:
    global running
    running = False


def claim_job() -> str | None:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        job = db.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.status.in_([JobStatus.pending, JobStatus.running]),
                or_(ProcessingJob.lease_until.is_(None), ProcessingJob.lease_until < now),
            )
            .order_by(ProcessingJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return None
        job.status = JobStatus.running
        job.attempts += 1
        job.lease_until = now + timedelta(minutes=5)
        db.commit()
        return job.id


def quality_warning(image: Image.Image) -> str | None:
    width, height = image.size
    if width * height < 1_000_000:
        return "low_resolution"
    gray = ImageOps.grayscale(image).resize((256, 256))
    extrema = gray.getextrema()
    if extrema[1] - extrema[0] < 45:
        return "low_contrast"
    return None


def process(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id)
        page = db.get(ScanPage, job.page_id) if job and job.page_id else None
        if not job or not page:
            return
        source = settings.storage_root / page.original_path
        output_relative = (
            Path("users") / page.owner_user_id / "processed" / page.project_id / f"{page.id}.jpg"
        )
        output = settings.storage_root / output_relative
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with Image.open(source) as raw:
                image = ImageOps.exif_transpose(raw).convert("RGB")
                page.quality_warning = quality_warning(image)
                image = ImageOps.autocontrast(image, cutoff=1)
                image = ImageEnhance.Sharpness(image).enhance(1.15)
                image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3))
                image.save(output, "JPEG", quality=92, optimize=True)
            page.processed_path = str(output_relative).replace("\\", "/")
            page.mime_type = "image/jpeg"
            job.status = JobStatus.needs_review if page.quality_warning else JobStatus.completed
            job.error = None
        except Exception as exc:  # keep originals and expose a recoverable failure
            job.status = JobStatus.failed if job.attempts >= 3 else JobStatus.pending
            job.error = str(exc)[:1000]
            if output.exists():
                output.unlink()
        finally:
            job.lease_until = None
            db.commit()


def main() -> None:
    Base.metadata.create_all(engine)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while running:
        job_id = claim_job()
        if job_id:
            process(job_id)
        else:
            time.sleep(1.0)


if __name__ == "__main__":
    main()
