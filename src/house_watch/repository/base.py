"""Interfaz de persistencia (secciones 3 y 38).

La logica de negocio depende de este Protocol, nunca de Turso ni de SQLite.
Eso es lo que permite cambiar de proveedor sin tocar scraping, scoring ni
notificaciones si algun free tier deja de convenir (seccion 37).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import Listing, PendingAlert, RunStats


@dataclass
class ExistingListing:
    """Estado previo minimo necesario para decidir novedad y cambios."""

    id: int
    external_id: str
    price_usd: float | None
    data_hash: str | None
    active: bool
    score: int | None


@dataclass
class UpsertOutcome:
    new: list[Listing]
    changed: list[tuple[Listing, ExistingListing]]
    unchanged: int


class ListingRepository(Protocol):
    def migrate(self) -> None: ...

    def get_existing(self, source: str, external_ids: list[str]) -> dict[str, ExistingListing]: ...

    def has_any_listings(self, source: str) -> bool: ...

    def upsert_listings(self, source: str, listings: list[Listing]) -> UpsertOutcome: ...

    def reserve_alert(
        self, *, dedupe_key: str, listing_id: int | None, alert_type: str,
        score: int | None, payload: str,
    ) -> int | None: ...

    def mark_alert_sent(self, alert_id: int) -> None: ...

    def pending_alerts(self) -> list[PendingAlert]: ...

    def record_run(self, stats: RunStats) -> None: ...

    def mark_missing(self, source: str, seen_ids: list[str], threshold: int) -> int: ...

    def comparables(
        self, *, neighborhood: str | None, bedrooms: int | None,
        built_area_m2: float | None, land_area_m2: float | None,
        built_bucket: float, land_bucket: float, exclude_id: int | None,
    ) -> list[float]: ...

    def set_opportunity_score(self, listing_id: int, score: int) -> None: ...

    def purge(self, *, runs_days: int, versions_days: int) -> None: ...

    def get_state(self, key: str) -> str | None: ...

    def set_state(self, key: str, value: str) -> None: ...

    def close(self) -> None: ...
