from __future__ import annotations

import json
from pathlib import Path

from services.api.app.main import app

OPENAPI_SNAPSHOT = Path(__file__).parents[1] / "packages" / "contracts" / "openapi.json"

EXPECTED_OPERATIONS = {
    ("GET", "/health", 200),
    ("POST", "/v1/auth/register", 201),
    ("POST", "/v1/auth/sms/challenges", 201),
    ("POST", "/v1/auth/wecom/authorize", 201),
    ("GET", "/v1/auth/wecom/callback", 200),
    ("POST", "/v1/auth/wecom/bind-phone", 200),
    ("POST", "/v1/auth/account-merges", 200),
    ("POST", "/v1/auth/login", 200),
    ("POST", "/v1/auth/refresh", 200),
    ("POST", "/v1/auth/account-deletion/cancel", 200),
    ("POST", "/v1/auth/logout", 204),
    ("GET", "/v1/me", 200),
    ("POST", "/v1/me/account-deletion", 202),
    ("POST", "/v1/me/password", 204),
    ("GET", "/v1/me/sessions", 200),
    ("DELETE", "/v1/me/sessions", 204),
    ("DELETE", "/v1/me/sessions/{session_id}", 204),
    ("GET", "/v1/projects", 200),
    ("POST", "/v1/projects", 201),
    ("GET", "/v1/projects/{project_id}", 200),
    ("DELETE", "/v1/projects/{project_id}", 202),
    ("GET", "/v1/projects/{project_id}/pages", 200),
    ("PATCH", "/v1/projects/{project_id}/pages/order", 200),
    ("POST", "/v1/projects/{project_id}/pages", 202),
    ("GET", "/v1/projects/{project_id}/exports", 200),
    ("POST", "/v1/projects/{project_id}/exports", 201),
    ("GET", "/v1/exports/{export_id}", 200),
    ("GET", "/v1/export-artifacts/{artifact_id}/content", 200),
    ("GET", "/v1/project-deletions/{deletion_id}", 200),
    ("GET", "/v1/pages/{page_id}", 200),
    ("POST", "/v1/uploads", 201),
    ("GET", "/v1/uploads/{upload_id}", 200),
    ("DELETE", "/v1/uploads/{upload_id}", 204),
    ("PUT", "/v1/uploads/{upload_id}/chunks/{chunk_index}", 200),
    ("POST", "/v1/uploads/{upload_id}/complete", 202),
    ("GET", "/v1/pages/{page_id}/content", 200),
    ("GET", "/v1/pages/{page_id}/results", 200),
    ("POST", "/v1/pages/{page_id}/rotations", 200),
    ("POST", "/v1/pages/{page_id}/edits", 200),
    ("PATCH", "/v1/pages/{page_id}/review", 200),
    ("PUT", "/v1/pages/{page_id}/exam-suggestion-dismissal", 200),
    ("GET", "/v1/jobs", 200),
    ("GET", "/v1/jobs/{job_id}", 200),
    ("POST", "/v1/jobs/{job_id}/cancel", 200),
    ("POST", "/v1/jobs/{job_id}/retry", 200),
    ("GET", "/v1/admin/users", 200),
    ("GET", "/v1/admin/users/{target_id}/projects", 200),
    ("PATCH", "/v1/admin/users/{target_id}/role", 200),
    ("PATCH", "/v1/admin/users/{target_id}/status", 200),
    ("DELETE", "/v1/admin/users/{target_id}/sessions", 204),
    ("POST", "/v1/admin/users/{target_id}/account-deletion", 202),
    ("GET", "/v1/admin/account-deletions", 200),
    ("POST", "/v1/admin/account-deletions/{request_id}/cancel", 200),
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
        "PageResultView",
        "UploadView",
        "ChunkReceipt",
        "JobView",
        "ExportView",
        "ExportArtifactView",
        "ProjectDeletionView",
        "AccountMergeView",
        "DeviceSessionView",
        "AccountDeletionView",
        "AdminAccountDeletionView",
        "AuditLogView",
    }.issubset(component_schemas)
    assert "securitySchemes" not in schema["components"]
    assert schema["paths"]["/v1/uploads/{upload_id}/complete"]["post"]["responses"]["202"]
    page_properties = component_schemas["PageView"]["properties"]
    assert {
        "ocr_text",
        "ocr_status",
        "ocr_result_version",
        "ocr_model_version",
        "ocr_confidence",
        "ocr_rotation_degrees",
        "ocr_details",
        "ocr_title_candidate",
        "ocr_error_code",
        "ocr_updated_at",
    }.issubset(page_properties)
    assert {
        "exam_classification_status",
        "exam_result_version",
        "exam_classifier_version",
        "exam_prediction",
        "exam_probability",
        "exam_confidence_band",
        "exam_recommendation",
        "exam_details",
        "exam_suggestion_visible",
        "exam_suggestion_dismissed_result_version",
        "exam_suggestion_dismissed_by_user_id",
        "exam_suggestion_dismissed_at",
        "exam_suggestion_dismissal_reason",
        "exam_updated_at",
    }.issubset(page_properties)
    project_properties = component_schemas["ProjectView"]["properties"]
    assert {"suggested_name", "suggested_name_source", "suggested_name_updated_at"}.issubset(
        project_properties
    )


def test_openapi_matches_committed_snapshot() -> None:
    expected = json.loads(OPENAPI_SNAPSHOT.read_text(encoding="utf-8"))
    assert app.openapi() == expected
