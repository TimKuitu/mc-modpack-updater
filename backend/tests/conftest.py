from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_appdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MC_UPDATER_DATA_DIR", str(tmp_path / "appdata"))
