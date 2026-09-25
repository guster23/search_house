"""Filtros duros y filtrado temprano (secciones 15 y 16).

Separado del scoring a proposito: el scoring ordena candidatos, los filtros
deciden quien es candidato. Una propiedad rechazada aca no se alerta nunca,
sin importar cuanto puntue.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .models import Listing
from .normalize import normalize_text


@dataclass(frozen=True)
class FilterVerdict:
    passed: bool
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.passed


PASS = FilterVerdict(True)


def _reject(reason: str) -> FilterVerdict:
    return FilterVerdict(False, reason)


def hard_reject_reason(listing: Listing, cfg: Config) -> str | None:
    """Palabras que descalifican la propiedad sin importar nada mas.

    Nuda propiedad, derechos posesorios, ocupada y remate no son casas que se
    puedan comprar y habitar normalmente (seccion 16).
    """
    keywords = cfg.filters.get("reject_keywords") or []
    if not keywords:
        return None
    blob = normalize_text(f"{listing.title or ''} {listing.description or ''}")
    if not blob:
        return None
    for keyword in keywords:
        needle = normalize_text(keyword)
        if needle and needle in blob:
            return f"contiene '{keyword}'"
    return None


def passes_early_filters(listing: Listing, cfg: Config) -> FilterVerdict:
    """Descarte barato, antes de gastar un request de detalle (seccion 15).

    Solo rechaza con datos que *ya tenemos*. Un campo ausente nunca descalifica:
    puede completarse al abrir el detalle.
    """
    f = cfg.filters

    price = listing.price_usd
    if price is not None:
        max_price = f.get("max_price")
        if max_price is not None and price > float(max_price):
            return _reject(f"precio {price:,.0f} > maximo {float(max_price):,.0f}")
        min_price = f.get("min_price")
        if min_price is not None and price < float(min_price):
            return _reject(f"precio {price:,.0f} < minimo {float(min_price):,.0f}")

    min_bedrooms = f.get("min_bedrooms")
    if min_bedrooms is not None and listing.bedrooms is not None:
        if listing.bedrooms < int(min_bedrooms):
            return _reject(f"{listing.bedrooms} dormitorios < {int(min_bedrooms)}")

    allowed = f.get("allowed_departments") or []
    if allowed and listing.department:
        wanted = {normalize_text(d) for d in allowed}
        if normalize_text(listing.department) not in wanted:
            return _reject(f"departamento '{listing.department}' fuera de la lista")

    reason = hard_reject_reason(listing, cfg)
    if reason:
        return _reject(reason)

    return PASS


def passes_hard_filters(listing: Listing, cfg: Config) -> FilterVerdict:
    """Filtro completo, ya con todos los datos disponibles.

    Añade los chequeos que necesitan campos que la busqueda puede no traer.
    """
    verdict = passes_early_filters(listing, cfg)
    if not verdict:
        return verdict

    f = cfg.filters

    min_built = f.get("min_built_area_m2")
    if min_built is not None and listing.built_area_m2 is not None:
        if listing.built_area_m2 < float(min_built):
            return _reject(
                f"{listing.built_area_m2:.0f} m2 edificados < {float(min_built):.0f}"
            )

    # Sin precio no se puede evaluar ni comparar: no alertamos a ciegas.
    if listing.price_usd is None:
        return _reject("sin precio publicado")

    return PASS
