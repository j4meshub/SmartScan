from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import Response
from fastapi.responses import FileResponse

from .config import Settings


def attachment_response(
    *,
    absolute: Path,
    relative: str,
    media_type: str,
    file_name: str,
    settings: Settings,
    sha256: str | None = None,
) -> Response:
    headers = {"Cache-Control": "private, max-age=0, must-revalidate"}
    if sha256:
        headers["ETag"] = f'"{sha256}"'
    if not settings.internal_file_send_prefix:
        return FileResponse(
            absolute,
            media_type=media_type,
            filename=file_name,
            content_disposition_type="attachment",
            headers=headers,
        )
    encoded_path = quote(relative.replace("\\", "/"), safe="/")
    encoded_name = quote(file_name, safe="")
    headers.update(
        {
            "X-Accel-Redirect": f"{settings.internal_file_send_prefix}/{encoded_path}",
            "Content-Disposition": f"attachment; filename*=utf-8''{encoded_name}",
            "Accept-Ranges": "bytes",
        }
    )
    return Response(status_code=200, media_type=media_type, headers=headers)
