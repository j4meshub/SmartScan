from __future__ import annotations

import json
from pathlib import Path

from services.api.app.main import app

OPENAPI_SNAPSHOT = Path(__file__).parents[1] / "packages" / "contracts" / "openapi.json"

EXPECTED_OPERATIONS = {
    ("GET", "/health", 200),
    ("POST", "/v1/auth/register", 201),
    ("POST", "/v1/auth/sms/challenges", 201),
    ("POST", "/v1/auth/login", 200),
    ("POST", "/v1/auth/logout", 204),
    ("GET", "/v1/me", 200),
    ("POST", "/v1/me/password", 204),
    ("GET", "/v1/projects", 200),
    ("POST", "/v1/projects", 201),
    ("GET", "/v1/projects/{project_id}", 200),
    ("GET", "/v1/projects/{project_id}/pages", 200),
    ("POST", "/v1/projects/{project_id}/pages", 202),
    ("POST", "/v1/uploads", 201),
    ("GET", "/v1/uploads/{upload_id}", 200),
    ("PUT", "/v1/uploads/{upload_id}/chunks/{chunk_index}", 200),
    ("POST", "/v1/uploads/{upload_id}/complete", 202),
    ("GET", "/v1/pages/{page_id}/content", 200),
    ("GET", "/v1/jobs", 200),
    ("GET", "/v1/admin/users", 200),
    ("GET", "/v1/admin/users/{target_id}/projects", 200),
    ("PATCH", "/v1/admin/users/{target_id}/role", 200),
    ("PATCH", "/v1/admin/users/{target_id}/status", 200),
    ("GET", "/v1/admin/audit", 200),
}


def test_public_route_methods_and_status_codes_are_stable() -> None:
    schema = app.openapi()
    actual = {
        (
            method.upper(),
            path,
            min(int(status) for status in operation["responses"] if status.startswith("2")),
        )
        for path, path_item in schema["paths"].items()
        for method, operation in path_item.items()
    }
    assert actual == EXPECTED_OPERATIONS


def test_openapi_exposes_existing_models_and_security_scheme() -> None:
    schema = app.openapi()
    component_schemas = schema["components"]["schemas"]
    assert {
        "TokenResponse",
        "UserView",
        "ProjectView",
        "PageView",
        "UploadView",
        "ChunkReceipt",
        "JobView",
    }.issubset(component_schemas)
    assert "securitySchemes" not in schema["components"]
    assert schema["paths"]["/v1/uploads/{upload_id}/complete"]["post"]["responses"]["202"]


def test_openapi_matches_committed_snapshot() -> None:
    expected = json.loads(OPENAPI_SNAPSHOT.read_text(encoding="utf-8"))
    assert app.openapi() == expected
