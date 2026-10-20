from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .admin_routes import router as admin_router
from .auth_routes import router as auth_router
from .config import get_settings
from .database import SessionLocal
from .domain_services import ensure_superadmin
from .migrations import ensure_database_current, upgrade_database
from .scan_routes import router as scan_router

settings = get_settings()
API_MAJOR_VERSION = "v1"
CONTRACT_REVISION = "2026-10-20.2"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_migrate:
        upgrade_database(settings.database_url)
    else:
        ensure_database_current(settings.database_url)
    with SessionLocal() as db:
        ensure_superadmin(db)
    yield


app = FastAPI(
    title="SmartScan 接口",
    version=CONTRACT_REVISION,
    description="统一账号、权限、扫描项目、上传、处理、导出与文件生命周期接口。",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(scan_router)
app.include_router(admin_router)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["referrer-policy"] = "same-origin"
    response.headers["x-smartscan-api-version"] = API_MAJOR_VERSION
    response.headers["x-smartscan-contract-revision"] = CONTRACT_REVISION
    return response
