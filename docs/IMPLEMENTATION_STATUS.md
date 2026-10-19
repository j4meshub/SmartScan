# Implementation status

Updated: 2026-10-19

The v1.4 plan describes a multi-stage product program, including external credentials, physical devices, model evaluation, a target Ubuntu host, WeCom tenant configuration, Android signing, and Apple review. This repository intentionally distinguishes implemented behavior from placeholders.

## Implemented baseline

| Area | Status | Notes |
|---|---|---|
| Repository structure | Implemented | H5, admin, Android, iOS, API, worker, AI gateway, contracts, deploy and docs |
| Local identity | Implemented | Verified development-code registration, username/password login, Argon2id and opaque sessions |
| Phone handling | Implemented | E.164 normalization, masked display and peppered HMAC matching |
| Role visibility | Implemented | User self-only; admin self + users; super admin all |
| Admin account actions | Partial | Role and active/disabled changes with session revocation; deletion/cooling-off remains |
| Unique super admin | Implemented baseline | API bootstrapping plus PostgreSQL unique index and protective trigger |
| Audit | Implemented baseline | Login, cross-user reads, role/status actions; production retention/export remains |
| Scan projects/uploads | Implemented | Owner IDs, generated paths, MIME/size checks, hashes and original retention |
| Job queue | Implemented baseline | PostgreSQL locking/leases and retry state |
| CPU processing | Implemented baseline | EXIF orientation, autocontrast, sharpening and basic quality warnings |
| H5 | Implemented baseline | Responsive bilingual authentication, mode/project creation and upload |
| Admin web | Implemented baseline | Account metrics/list and audit display |
| Optional AI gateway | Safety skeleton | Public HTTPS validation; no provider is enabled or called |
| Android | UI scaffold | Compose shell and declared CameraX/Room/WorkManager/ML Kit dependencies |
| iOS | UI scaffold | SwiftUI shell; Xcode target and signing still required |
| CI/deployment | Implemented baseline | GitHub/GitLab checks and single-host Compose layout |

## Not represented as complete

- Real SMS provider, WeCom OAuth/address-book permissions and safe identity conflict resolution.
- Resumable chunk upload with idempotency and weak-network recovery.
- OpenCV document-edge/perspective correction, OCR/orientation fusion, template exam cleaning, book dewarping, spread splitting, page-number/repeat/gap detection and PDF/JPG exports.
- CameraX/AVFoundation capture state machines, encrypted local caches, offline queues, share sheets and complete account deletion UI.
- Production database migrations, encrypted phone storage, backup/restore drills, monitoring, quotas and 16-user mixed-load validation.
- Model datasets, acceptance metrics, real device matrix, WeCom verification, Android signed distribution, TestFlight/App Store materials and review.

## Recommended next milestones

1. Freeze domain, SMS, WeCom, package/Bundle IDs, storage limits, deletion window and production host parameters.
2. Complete the stage-0 rejection POC: WeCom phone trust, H5 resumable uploads, document perspective correction, basic exam cleaning, book split/dewarp and a 16-user load test.
3. Add versioned PostgreSQL migrations and expand authorization/IDOR integration tests before any real user data is accepted.
4. Wire Android and iOS camera/upload flows on physical devices, then proceed through the plan's acceptance gates in order.

