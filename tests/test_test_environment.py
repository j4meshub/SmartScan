from __future__ import annotations

from pathlib import Path

from services.api.app.main import settings


def test_application_tests_use_isolated_database_and_storage() -> None:
    workspace = Path.cwd().resolve()
    storage_root = settings.storage_root.resolve()

    assert settings.database_url.endswith("/smartscan-test.db")
    assert storage_root.name == "storage"
    assert workspace != storage_root
    assert workspace not in storage_root.parents
