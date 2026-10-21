from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .ops_metrics import render_operational_metrics

router = APIRouter()
settings = get_settings()


@router.get("/internal/metrics", include_in_schema=False)
def operational_metrics(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Response:
    expected = settings.ops_metrics_token.get_secret_value()
    supplied = ""
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization.removeprefix("Bearer ")
    if (
        not settings.ops_metrics_enabled
        or not expected
        or not supplied
        or not secrets.compare_digest(supplied, expected)
    ):
        raise HTTPException(status_code=404, detail="not found")
    return Response(
        content=render_operational_metrics(db, settings),
        headers={"content-type": CONTENT_TYPE_LATEST},
    )
