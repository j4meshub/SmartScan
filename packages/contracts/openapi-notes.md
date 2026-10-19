# API contract notes

The FastAPI service publishes the canonical OpenAPI document at `/openapi.json`.

- User-facing clients only call `/v1/projects`, `/v1/pages`, and `/v1/jobs` for the authenticated user.
- Cross-user access is confined to `/v1/admin/*` and always audited.
- Unknown and unauthorized object identifiers both return `404`.
- Processing succeeds without an external AI provider; AI is an optional enhancement.

