"""Fabrica de conexiones: SQLite local en desarrollo, Turso/libSQL en produccion.

El driver `libsql` es compatible con la DB-API de `sqlite3` (verificado:
mismos `execute`, `rowcount` y `commit`, incluido `rowcount == 0` en un
`ON CONFLICT DO NOTHING`). Por eso hay una sola implementacion de repositorio
y solo cambia como se abre la conexion: el SQL que corre en tu maquina es
exactamente el que corre en produccion (seccion 3).

Si en el futuro el driver divergiera, el adapter va aca y nada mas cambia.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)


class Connection(Protocol):
    """Subconjunto de la DB-API que realmente usamos."""

    def execute(self, sql: str, parameters: tuple = ()) -> Any: ...
    def executemany(self, sql: str, parameters: list) -> Any: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


def connect_sqlite(path: str | Path) -> Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def connect_turso(url: str, auth_token: str) -> Connection:
    try:
        import libsql
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Falta el driver de Turso. Instalar con: pip install 'house-watch[turso]'"
        ) from exc
    return libsql.connect(database=url, auth_token=auth_token)


def connect(*, db_path: str | Path | None, secrets) -> tuple[Connection, str]:
    """Elige el backend. Devuelve (conexion, etiqueta para logs).

    Si se pasa --db explicito gana el local; si no, se usa Turso cuando hay
    secretos. Nunca se loguea la URL ni el token (seccion 12).
    """
    if db_path:
        log.info("Persistencia: SQLite local (%s)", db_path)
        return connect_sqlite(db_path), "sqlite"
    if secrets.has_turso:
        log.info("Persistencia: Turso/libSQL (remoto)")
        return connect_turso(secrets.turso_database_url, secrets.turso_auth_token), "turso"
    raise RuntimeError(
        "No hay backend de persistencia: pasa --db para SQLite local o define "
        "TURSO_DATABASE_URL y TURSO_AUTH_TOKEN."
    )
