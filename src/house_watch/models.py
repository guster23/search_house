"""Modelos de dominio. Dataclasses planas, sin dependencias de I/O."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone


def utcnow() -> str:
    """Timestamp ISO-8601 en UTC. Un solo lugar para el formato de fechas."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(*parts: object) -> str:
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class Listing:
    """Una propiedad normalizada.

    La misma clase representa el resultado parcial de una pagina de busqueda y
    el resultado completo tras abrir el detalle; `detail_complete` distingue
    ambos casos. Para InfoCasas la busqueda ya viene completa, asi que nunca
    se abre un detalle.
    """

    source: str
    external_id: str
    canonical_url: str

    title: str | None = None
    description: str | None = None
    currency: str | None = None
    price: float | None = None
    price_usd: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    built_area_m2: float | None = None
    land_area_m2: float | None = None
    neighborhood: str | None = None
    city: str | None = None
    department: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    agency: str | None = None
    image_url: str | None = None
    published_at: str | None = None

    features: set[str] = field(default_factory=set)
    detail_complete: bool = True

    # Calculados aguas abajo.
    score: int | None = None
    opportunity_score: int | None = None
    score_reasons: list[str] = field(default_factory=list)

    # Identidad en la DB, presente solo cuando viene de la base.
    id: int | None = None

    @property
    def description_hash(self) -> str:
        from .normalize import normalize_text

        return _sha(normalize_text(self.description or ""))

    def data_hash(self) -> str:
        """Hash de los campos cuyo cambio amerita una fila en listing_versions.

        Deliberadamente NO incluye last_seen_at ni el score: ver una propiedad
        de nuevo sin cambios no debe generar escrituras (seccion 11).
        """
        return _sha(
            self.price,
            # price_usd es el valor con el que se comparan bajas de precio:
            # si no entra al hash, una baja no se detecta como cambio.
            self.price_usd,
            self.currency,
            self.description_hash,
            self.built_area_m2,
            self.land_area_m2,
            self.bedrooms,
            self.bathrooms,
        )

    def fingerprint(self) -> str:
        """Huella aproximada para detectar la misma propiedad en otro portal.

        Redondea precio y areas a buckets para que dos publicaciones de la
        misma casa con datos levemente distintos caigan en el mismo valor.
        """
        from .normalize import normalize_text

        price = round((self.price_usd or 0) / 1000)
        built = round((self.built_area_m2 or 0) / 10)
        land = round((self.land_area_m2 or 0) / 50)
        return _sha(
            normalize_text(self.neighborhood or ""),
            self.bedrooms,
            built,
            land,
            price,
        )

    def with_scores(self, score: int, reasons: list[str]) -> "Listing":
        return replace(self, score=score, score_reasons=reasons)


@dataclass
class SourceResult:
    """Lo que devuelve una fuente en un run, incluida la senal de salud."""

    source: str
    listings: list[Listing] = field(default_factory=list)
    pages_fetched: int = 0
    # False cuando la respuesta no parece una pagina de resultados valida.
    # Clave: NO se deriva del status code (seccion 24).
    plausible: bool = True
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.plausible


@dataclass
class RunStats:
    source: str
    started_at: str
    finished_at: str | None = None
    pages_fetched: int = 0
    items_seen: int = 0
    items_new: int = 0
    items_changed: int = 0
    alerts_sent: int = 0
    status: str = "ok"          # ok | partial | error
    error: str | None = None


@dataclass
class PendingAlert:
    """Alerta reservada en la DB pero todavia no confirmada en Telegram."""

    id: int
    listing_id: int | None
    alert_type: str
    score: int | None
    dedupe_key: str
    payload: str
