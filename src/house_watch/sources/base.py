"""Interfaz de fuente (seccion 38).

Toda la logica de negocio (scoring, filtros, alertas) trabaja contra esta
interfaz, nunca contra un portal concreto. Eso es lo que permite agregar o
quitar fuentes sin tocar nada mas.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..budget import ExecutionBudget
from ..config import Config, SearchConfig
from ..http import HttpFetcher
from ..models import Listing, SourceResult


@runtime_checkable
class ListingSource(Protocol):
    name: str
    requires_browser: bool

    def search(
        self,
        searches: tuple[SearchConfig, ...],
        fetcher: HttpFetcher,
        budget: ExecutionBudget,
        cfg: Config,
    ) -> SourceResult:
        """Recorre las paginas de busqueda y devuelve listings normalizados."""

    def needs_detail(self, listing: Listing, known: Listing | None) -> bool:
        """Si hace falta abrir la pagina de detalle de esta propiedad (seccion 6)."""

    def fetch_detail(
        self, listing: Listing, fetcher: HttpFetcher, budget: ExecutionBudget
    ) -> Listing:
        """Completa la propiedad con los datos de su pagina de detalle."""


class BaseSource:
    """Comportamiento por defecto compartido."""

    name: str = "base"
    requires_browser: bool = False

    def needs_detail(self, listing: Listing, known: Listing | None) -> bool:
        """Politica por defecto de la seccion 6.

        Se abre el detalle solo si la propiedad es nueva, si cambio el precio
        o si le faltan datos importantes. Nunca para las 150 que ya conocemos.
        """
        if listing.detail_complete:
            return False
        if known is None:
            return True
        if known.price_usd != listing.price_usd:
            return True
        return listing.built_area_m2 is None or listing.bedrooms is None

    def fetch_detail(
        self, listing: Listing, fetcher: HttpFetcher, budget: ExecutionBudget
    ) -> Listing:
        return listing


class BlockedSource(BaseSource):
    """Fuente declarada pero inaccesible por HTTP plano.

    Existe para que el estado quede registrado y visible en source_health en
    vez de desaparecer silenciosamente de la configuracion.
    """

    reason: str = "bloqueada"

    def search(self, searches, fetcher, budget, cfg) -> SourceResult:
        return SourceResult(
            source=self.name, listings=[], plausible=False, error=self.reason
        )
