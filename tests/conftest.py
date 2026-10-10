from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from house_watch.config import Secrets, load_config          # noqa: E402
from house_watch.repository.connection import connect_sqlite  # noqa: E402
from house_watch.repository.sql import SqlListingRepository   # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def infocasas_html() -> str:
    """Respuesta real de InfoCasas capturada el 2026-09-25."""
    return (FIXTURES / "infocasas_search.html").read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="session")
def gallito_html() -> str:
    """Respuesta real de Gallito capturada el 2026-10-03."""
    return (FIXTURES / "gallito_search.html").read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def cfg():
    return load_config(FIXTURES / "config.yaml", secrets=Secrets())


@pytest.fixture
def repo(tmp_path):
    repository = SqlListingRepository(
        connect_sqlite(tmp_path / "test.db"), migrations_dir=ROOT / "migrations"
    )
    repository.migrate()
    yield repository
    repository.close()
