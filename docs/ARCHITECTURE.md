# Architecture

```text
WeCom H5 ─┐
Android ──┼── HTTPS / Nginx ── FastAPI ── PostgreSQL
iOS ──────┘                         │          │
Admin web ──────────────────────────┘          └─ leased CPU jobs
                                                │
                                      per-user file storage
                                                │
                                      optional AI gateway (off)
```

Authorization is evaluated against the current role of the immutable data owner. Administrative reads never change ownership and generate an audit event. User-facing project lists always constrain by the current user's owner ID, even for administrators.

The worker acquires tasks with row locking and a lease. Client disconnects therefore do not cancel accepted work; expired leases can be reclaimed. Originals are retained and processed outputs are separate artifacts.

External AI is an enhancement boundary, not a dependency. Provider URLs must use HTTPS and resolve only to public addresses. Production must additionally enforce DNS rebinding protection, egress allowlists, redirect rejection, request size limits, timeouts, output schemas, cost quotas and circuit breakers.

