"""Implementacion SQL del repositorio, comun a SQLite y Turso.

Optimizada para minimizar round trips: contra Turso cada `execute` es una
llamada de red desde el runner, asi que las lecturas van en una sola query con
IN (...) y las escrituras en `executemany`. Un run de ~100 propiedades cuesta
unas pocas idas y vueltas, no doscientas.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..models import Listing, PendingAlert, RunStats, utcnow
from .base import ExistingListing, UpsertOutcome
from .connection import Connection

log = logging.getLogger(__name__)

def _default_migrations_dir() -> Path:
    """Ubica migrations/ tanto en un checkout como instalado con pip -e."""
    for candidate in (
        Path(__file__).resolve().parents[3] / "migrations",
        Path.cwd() / "migrations",
    ):
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parents[3] / "migrations"


MIGRATIONS_DIR = _default_migrations_dir()

# SQLite tiene un tope de variables por sentencia; troceamos las lecturas.
_CHUNK = 400

_LISTING_COLUMNS = (
    "source", "external_id", "canonical_url", "title", "description", "currency",
    "price", "price_usd", "bedrooms", "bathrooms", "built_area_m2", "land_area_m2",
    "neighborhood", "city", "department", "address", "latitude", "longitude",
    "agency", "image_url", "published_at", "fingerprint", "score",
    "opportunity_score", "description_hash", "data_hash", "features_json",
)


def _listing_values(listing: Listing) -> tuple:
    return (
        listing.source, listing.external_id, listing.canonical_url, listing.title,
        listing.description, listing.currency, listing.price, listing.price_usd,
        listing.bedrooms, listing.bathrooms, listing.built_area_m2,
        listing.land_area_m2, listing.neighborhood, listing.city, listing.department,
        listing.address, listing.latitude, listing.longitude, listing.agency,
        listing.image_url, listing.published_at, listing.fingerprint(), listing.score,
        listing.opportunity_score, listing.description_hash, listing.data_hash(),
        json.dumps(sorted(listing.features)),
    )


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def _split_statements(sql: str) -> list[str]:
    """Separa sentencias por ';' ignorando los que aparecen en comentarios.

    Un ';' dentro de un comentario -- ... partiria la sentencia al medio y
    fallaria con "incomplete input".
    """
    lines = [
        line.split("--", 1)[0] if "--" in line else line
        for line in sql.splitlines()
    ]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


class SqlListingRepository:
    def __init__(self, conn: Connection, migrations_dir: Path | None = None):
        self._conn = conn
        self._migrations = migrations_dir or MIGRATIONS_DIR

    # --- esquema ----------------------------------------------------------

    def migrate(self) -> None:
        """Aplica las migraciones. Idempotente (todo es CREATE ... IF NOT EXISTS)."""
        files = sorted(self._migrations.glob("*.sql"))
        if not files:
            raise RuntimeError(f"No hay migraciones en {self._migrations}")
        for path in files:
            for statement in _split_statements(path.read_text(encoding="utf-8")):
                self._conn.execute(statement)
        self._conn.commit()
        log.info("Migraciones aplicadas: %s", ", ".join(p.name for p in files))

    # --- listings ---------------------------------------------------------

    def get_existing(self, source: str, external_ids: list[str]) -> dict[str, ExistingListing]:
        """Una sola query por lote: contra Turso cada round trip cuesta."""
        found: dict[str, ExistingListing] = {}
        for start in range(0, len(external_ids), _CHUNK):
            chunk = external_ids[start : start + _CHUNK]
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT id, external_id, price_usd, data_hash, active, score "
                f"FROM listings WHERE source = ? AND external_id IN ({placeholders})",
                (source, *chunk),
            ).fetchall()
            for row in rows:
                found[str(row[1])] = ExistingListing(
                    id=int(row[0]), external_id=str(row[1]),
                    price_usd=row[2], data_hash=row[3],
                    active=bool(row[4]), score=row[5],
                )
        return found

    def has_any_listings(self, source: str) -> bool:
        """Si ya conocemos esta fuente. False = primera corrida (linea de base)."""
        row = self._conn.execute(
            "SELECT 1 FROM listings WHERE source = ? LIMIT 1", (source,)
        ).fetchone()
        return row is not None

    def upsert_listings(self, source: str, listings: list[Listing]) -> UpsertOutcome:
        """Inserta, actualiza o solo 'toca' cada propiedad segun si cambio.

        Solo se escribe una fila en listing_versions cuando el data_hash
        cambia, que es lo que mantiene bajo el volumen de escrituras
        (seccion 11).
        """
        if not listings:
            return UpsertOutcome(new=[], changed=[], unchanged=0)

        now = utcnow()
        existing = self.get_existing(source, [l.external_id for l in listings])

        new: list[Listing] = []
        changed: list[tuple[Listing, ExistingListing]] = []
        touch: list[tuple] = []

        for listing in listings:
            prior = existing.get(listing.external_id)
            if prior is None:
                new.append(listing)
            elif prior.data_hash != listing.data_hash() or not prior.active:
                changed.append((listing, prior))
            else:
                touch.append((now, listing.external_id, source))

        if new:
            cols = ", ".join(_LISTING_COLUMNS)
            marks = ", ".join("?" * len(_LISTING_COLUMNS))
            self._conn.executemany(
                f"INSERT INTO listings ({cols}, first_seen_at, last_seen_at, active, "
                f"missed_observations) VALUES ({marks}, ?, ?, 1, 0) "
                f"ON CONFLICT (source, external_id) DO NOTHING",
                [(*_listing_values(l), now, now) for l in new],
            )

        if changed:
            assignments = ", ".join(f"{c} = ?" for c in _LISTING_COLUMNS)
            self._conn.executemany(
                f"UPDATE listings SET {assignments}, last_seen_at = ?, active = 1, "
                f"missed_observations = 0 WHERE source = ? AND external_id = ?",
                [
                    (*_listing_values(l), now, source, l.external_id)
                    for l, _ in changed
                ],
            )

        if touch:
            self._conn.executemany(
                "UPDATE listings SET last_seen_at = ?, missed_observations = 0 "
                "WHERE external_id = ? AND source = ?",
                touch,
            )

        self._conn.commit()

        # Los ids recien creados hacen falta para versiones y alertas.
        refreshed = self.get_existing(source, [l.external_id for l in new + [c[0] for c in changed]])
        version_rows = []
        for listing in new:
            prior = refreshed.get(listing.external_id)
            if prior:
                listing.id = prior.id
                version_rows.append((prior.id, now, listing.price_usd, listing.data_hash()))
        for listing, _ in changed:
            prior = refreshed.get(listing.external_id)
            if prior:
                listing.id = prior.id
                version_rows.append((prior.id, now, listing.price_usd, listing.data_hash()))

        if version_rows:
            self._conn.executemany(
                "INSERT INTO listing_versions (listing_id, observed_at, price, data_hash) "
                "VALUES (?, ?, ?, ?)",
                version_rows,
            )
            self._conn.commit()

        return UpsertOutcome(new=new, changed=changed, unchanged=len(touch))

    def mark_missing(self, source: str, seen_ids: list[str], threshold: int) -> int:
        """Incrementa el contador de ausencias y desactiva al superar el umbral.

        IMPORTANTE: el pipeline solo llama esto cuando la fuente estuvo sana en
        el run. Si un scraper falla y devuelve 0 resultados, contar eso como
        'todas desaparecieron' desactivaria el historial entero (seccion 28).
        """
        placeholders = ",".join("?" * len(seen_ids)) if seen_ids else "NULL"
        params: tuple = (source, *seen_ids) if seen_ids else (source,)
        self._conn.execute(
            f"UPDATE listings SET missed_observations = missed_observations + 1 "
            f"WHERE source = ? AND active = 1 AND external_id NOT IN ({placeholders})",
            params,
        )
        cursor = self._conn.execute(
            "UPDATE listings SET active = 0 WHERE source = ? AND active = 1 "
            "AND missed_observations >= ?",
            (source, threshold),
        )
        self._conn.commit()
        return int(getattr(cursor, "rowcount", 0) or 0)

    # --- alertas (idempotencia, seccion 22) --------------------------------

    def reserve_alert(
        self, *, dedupe_key: str, listing_id: int | None, alert_type: str,
        score: int | None, payload: str,
    ) -> int | None:
        """Reserva la alerta antes de mandarla. None = ya se habia alertado.

        `sent_at` queda NULL a proposito: si Telegram falla justo despues, la
        fila queda pendiente y el proximo run la reintenta en vez de perderla.
        """
        cursor = self._conn.execute(
            "INSERT INTO alerts (listing_id, alert_type, score, created_at, sent_at, "
            "payload, dedupe_key) VALUES (?, ?, ?, ?, NULL, ?, ?) "
            "ON CONFLICT (dedupe_key) DO NOTHING",
            (listing_id, alert_type, score, utcnow(), payload, dedupe_key),
        )
        self._conn.commit()
        if not getattr(cursor, "rowcount", 0):
            return None
        row = self._conn.execute(
            "SELECT id FROM alerts WHERE dedupe_key = ?", (dedupe_key,)
        ).fetchone()
        return int(row[0]) if row else None

    def mark_alert_sent(self, alert_id: int) -> None:
        self._conn.execute(
            "UPDATE alerts SET sent_at = ? WHERE id = ?", (utcnow(), alert_id)
        )
        self._conn.commit()

    def pending_alerts(self) -> list[PendingAlert]:
        rows = self._conn.execute(
            "SELECT id, listing_id, alert_type, score, dedupe_key, payload "
            "FROM alerts WHERE sent_at IS NULL ORDER BY id"
        ).fetchall()
        return [
            PendingAlert(
                id=int(r[0]), listing_id=r[1], alert_type=r[2],
                score=r[3], dedupe_key=r[4], payload=r[5] or "",
            )
            for r in rows
        ]

    def discard_alert(self, alert_id: int) -> None:
        """Libera una reserva que no se pudo enviar por un error permanente."""
        self._conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        self._conn.commit()

    # --- runs y salud -----------------------------------------------------

    def record_run(self, stats: RunStats) -> None:
        self._conn.execute(
            "INSERT INTO scrape_runs (started_at, finished_at, source, pages_fetched, "
            "items_seen, items_new, items_changed, alerts_sent, status, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                stats.started_at, stats.finished_at or utcnow(), stats.source,
                stats.pages_fetched, stats.items_seen, stats.items_new,
                stats.items_changed, stats.alerts_sent, stats.status, stats.error,
            ),
        )
        self._conn.commit()

    def get_health(self, source: str) -> dict:
        row = self._conn.execute(
            "SELECT source, state, last_success_at, consecutive_failures, "
            "consecutive_zero_results, last_error, last_nonzero_result_at, "
            "degraded_notified_at FROM source_health WHERE source = ?",
            (source,),
        ).fetchone()
        if not row:
            return {
                "source": source, "state": "ok", "last_success_at": None,
                "consecutive_failures": 0, "consecutive_zero_results": 0,
                "last_error": None, "last_nonzero_result_at": None,
                "degraded_notified_at": None,
            }
        keys = (
            "source", "state", "last_success_at", "consecutive_failures",
            "consecutive_zero_results", "last_error", "last_nonzero_result_at",
            "degraded_notified_at",
        )
        return dict(zip(keys, row))

    def save_health(self, health: dict) -> None:
        self._conn.execute(
            "INSERT INTO source_health (source, state, last_success_at, "
            "consecutive_failures, consecutive_zero_results, last_error, "
            "last_nonzero_result_at, degraded_notified_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (source) DO UPDATE SET state = excluded.state, "
            "last_success_at = excluded.last_success_at, "
            "consecutive_failures = excluded.consecutive_failures, "
            "consecutive_zero_results = excluded.consecutive_zero_results, "
            "last_error = excluded.last_error, "
            "last_nonzero_result_at = excluded.last_nonzero_result_at, "
            "degraded_notified_at = excluded.degraded_notified_at",
            (
                health["source"], health["state"], health["last_success_at"],
                health["consecutive_failures"], health["consecutive_zero_results"],
                health["last_error"], health["last_nonzero_result_at"],
                health["degraded_notified_at"],
            ),
        )
        self._conn.commit()

    # --- oportunidad ------------------------------------------------------

    def comparables(
        self, *, neighborhood: str | None, bedrooms: int | None,
        built_area_m2: float | None, land_area_m2: float | None,
        built_bucket: float, land_bucket: float, exclude_id: int | None,
    ) -> list[float]:
        """Precios por m2 edificado de propiedades realmente comparables.

        Se exige coincidencia de zona y dormitorios, y cercania en area
        edificada y de terreno, para no comparar una casa de 100 m2 en 800 m2
        de terreno con un apartamento (seccion 18).
        """
        if not neighborhood or not built_area_m2 or not bedrooms:
            return []

        conditions = [
            "active = 1", "neighborhood = ?", "bedrooms = ?",
            "built_area_m2 IS NOT NULL", "built_area_m2 > 0", "price_usd > 0",
            "ABS(built_area_m2 - ?) <= ?",
        ]
        params: list = [neighborhood, bedrooms, built_area_m2, built_bucket]

        if land_area_m2:
            conditions.append("(land_area_m2 IS NULL OR ABS(land_area_m2 - ?) <= ?)")
            params += [land_area_m2, land_bucket]
        if exclude_id:
            conditions.append("id != ?")
            params.append(exclude_id)

        rows = self._conn.execute(
            f"SELECT price_usd / built_area_m2 FROM listings WHERE {' AND '.join(conditions)}",
            tuple(params),
        ).fetchall()
        return [float(r[0]) for r in rows if r[0]]

    def set_opportunity_score(self, listing_id: int, score: int) -> None:
        self._conn.execute(
            "UPDATE listings SET opportunity_score = ? WHERE id = ?", (score, listing_id)
        )
        self._conn.commit()

    # --- mantenimiento ----------------------------------------------------

    def purge(self, *, runs_days: int, versions_days: int) -> None:
        """Retencion de la seccion 27. Los listings nunca se borran."""
        self._conn.execute(
            "DELETE FROM scrape_runs WHERE started_at < ?", (_iso_days_ago(runs_days),)
        )
        self._conn.execute(
            "DELETE FROM listing_versions WHERE observed_at < ?",
            (_iso_days_ago(versions_days),),
        )
        self._conn.commit()

    def counts_since(self, days: int) -> dict:
        """Numeros para el resumen semanal (seccion 26)."""
        since = _iso_days_ago(days)
        row = self._conn.execute(
            "SELECT COALESCE(SUM(items_seen), 0), COALESCE(SUM(items_new), 0), "
            "COALESCE(SUM(alerts_sent), 0) FROM scrape_runs WHERE started_at >= ?",
            (since,),
        ).fetchone()
        interesting = self._conn.execute(
            "SELECT COUNT(*) FROM listings WHERE first_seen_at >= ? AND score >= ?",
            (since, 70),
        ).fetchone()
        return {
            "seen": int(row[0]), "new": int(row[1]), "alerts": int(row[2]),
            "interesting": int(interesting[0]),
        }

    # --- estado -----------------------------------------------------------

    def get_state(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_state(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO app_state (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
