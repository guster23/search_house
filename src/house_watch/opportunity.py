"""Deteccion de oportunidades por comparables historicos (secciones 17 y 18).

Sin IA y sin servicios pagos: se compara el precio por m2 edificado contra la
mediana de propiedades parecidas que ya vimos. Se usa mediana y no promedio
porque una sola mansion cargada por error deforma el promedio.

Nada de esto es confiable con pocos datos, asi que por debajo del minimo de
comparables se devuelve None y la alerta simplemente omite la linea. El
sistema sirve desde el dia uno y mejora solo a medida que junta historia.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from .config import Config
from .models import Listing

# Calibrado para que "14% por debajo de la mediana" de 78/100, como el
# ejemplo de la seccion 20.
_POINTS_PER_PERCENT = 2.0
_NEUTRAL = 50.0


@dataclass
class OpportunityResult:
    score: int
    price_per_m2: float
    median_price_per_m2: float
    difference_percent: float
    sample_size: int

    @property
    def is_below_market(self) -> bool:
        return self.difference_percent < 0

    def summary(self) -> str:
        return f"~{abs(self.difference_percent):.0f}% debajo de comparables"


def evaluate(listing: Listing, repo, cfg: Config) -> OpportunityResult | None:
    """Puntua la oportunidad, o None si no hay evidencia suficiente."""
    settings = cfg.opportunity
    if not settings.get("enabled", True):
        return None
    if not listing.price_usd or not listing.built_area_m2:
        return None

    samples = repo.comparables(
        neighborhood=listing.neighborhood,
        bedrooms=listing.bedrooms,
        built_area_m2=listing.built_area_m2,
        land_area_m2=listing.land_area_m2,
        built_bucket=float(settings.get("built_area_bucket_m2", 50)),
        land_bucket=float(settings.get("land_area_bucket_m2", 400)),
        exclude_id=listing.id,
    )

    minimum = int(settings.get("min_comparables", 15))
    if len(samples) < minimum:
        return None

    price_per_m2 = listing.price_usd / listing.built_area_m2
    market = median(samples)
    if market <= 0:
        return None

    difference = (price_per_m2 - market) / market * 100.0
    score = max(0, min(100, round(_NEUTRAL - difference * _POINTS_PER_PERCENT)))

    return OpportunityResult(
        score=score,
        price_per_m2=price_per_m2,
        median_price_per_m2=market,
        difference_percent=difference,
        sample_size=len(samples),
    )
