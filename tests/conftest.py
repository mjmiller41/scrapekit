import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Every test gets its own data dir and targets dir so nothing touches ~/.local."""
    data = tmp_path / "data"
    targets = tmp_path / "targets"
    targets.mkdir()
    monkeypatch.setenv("SCRAPEKIT_DATA", str(data))
    monkeypatch.setenv("SCRAPEKIT_TARGETS", str(targets))
    monkeypatch.setenv("SCRAPEKIT_CONFIG", str(tmp_path / "nope.yaml"))
    import scrapekit.config as config

    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "TARGETS_DIR", targets)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "nope.yaml")
    yield tmp_path


@pytest.fixture
def fixture_html():
    def _load(name: str) -> str:
        return (FIXTURES / name).read_text()
    return _load
