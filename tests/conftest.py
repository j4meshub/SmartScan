from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="smartscan-tests-"))
_DATABASE_PATH = _TEST_ROOT / "smartscan-test.db"
_STORAGE_PATH = _TEST_ROOT / "storage"

# conftest 在测试模块收集前加载，确保应用级单例从一开始就使用隔离资源。
os.environ["SMARTSCAN_ENV"] = "development"
os.environ["SMARTSCAN_DATABASE_URL"] = f"sqlite:///{_DATABASE_PATH.as_posix()}"
os.environ["SMARTSCAN_STORAGE_ROOT"] = str(_STORAGE_PATH)
os.environ["SMARTSCAN_AUTO_MIGRATE"] = "true"
os.environ["SMARTSCAN_SUPERADMIN_PASSWORD"] = ""


def pytest_sessionfinish() -> None:
    from services.api.app.database import engine

    engine.dispose()
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)
