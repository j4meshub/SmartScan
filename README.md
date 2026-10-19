# SmartScan / 智能扫描

SmartScan is a privacy-conscious document scanning platform with a shared account and data layer for a WeCom H5 entry, Android, iOS, and a browser administration console. The core processing path is designed to work with external AI disabled.

This repository is the first executable baseline derived from the v1.4 implementation plan. It is not yet an App Store-ready or production-certified release; see [Implementation status](docs/IMPLEMENTATION_STATUS.md) for the exact boundary.

## Included now

- FastAPI API with local registration/login, Argon2id passwords, deterministic phone HMAC, opaque sessions and session revocation.
- Server-side RBAC matching the `user` / `admin` / unique `super_admin` visibility matrix.
- Append-only audit events for login and cross-user administrative access.
- Per-owner scan projects, safe image upload paths, SHA-256 metadata and a PostgreSQL-backed leased job queue.
- CPU worker that preserves originals and performs EXIF orientation, contrast and sharpening without external AI.
- Responsive bilingual H5 and administration console with no frontend build dependency.
- Kotlin/Compose Android and SwiftUI iOS starting points.
- Docker Compose, Nginx, PostgreSQL hardening SQL, GitHub Actions and GitLab CI.

## Run locally

Prerequisites: Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env   # use cp on macOS/Linux
uvicorn services.api.app.main:app --reload
```

In two more terminals:

```bash
python -m services.worker.app.main
python -m http.server 8080 --directory apps/h5
python -m http.server 8081 --directory apps/admin-web
```

Open `http://localhost:8080` for H5 and `http://localhost:8081` for the admin console. API docs are at `http://localhost:8000/docs`.

Development registration uses `SMARTSCAN_DEV_SMS_CODE`; it is intentionally rejected outside the development environment. To bootstrap the protected administrator, set `SMARTSCAN_SUPERADMIN_PASSWORD` before the first API start. Production refuses weak/missing core secrets and never embeds the plan's example password in source control.

## Containers

Copy `.env.example` to `.env`, replace every secret, then:

```bash
docker compose -f deploy/compose/docker-compose.yml up --build
```

For PostgreSQL, apply `deploy/postgres/001_guards.sql` after the application schema has been created. A production rollout must replace this bootstrap with versioned migrations, TLS, encrypted backups and secret management.

## Test

```bash
ruff check services
pytest
node --check apps/h5/app.js
node --check apps/admin-web/app.js
```

## Security baseline

- Never commit `.env`, SMS/WeCom/AI keys, signing material or user scans.
- Data paths use server-generated IDs and are never directly exposed by Nginx.
- Unauthorized and unknown object IDs both return `404`.
- The only super administrator is protected in the API and by PostgreSQL guards.
- Optional AI endpoints must pass HTTPS/public-IP SSRF checks. The base scanning path remains independent of them.

## Repository map

```text
apps/h5/             mobile-first WeCom/browser client
apps/admin-web/      audited administrator console
apps/android/        Kotlin + Compose + CameraX scaffold
apps/ios/            SwiftUI application scaffold
services/api/        account, RBAC, projects, upload and audit API
services/worker/     CPU image-processing queue worker
services/ai-gateway/ optional provider validation boundary
packages/            contracts and shared translations
deploy/              Compose, Nginx and PostgreSQL controls
docs/                architecture and delivery status
```

## License

Copyright © 2026. No open-source license has been selected yet; all rights reserved.

