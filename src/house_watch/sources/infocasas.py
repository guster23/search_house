"""InfoCasas Uruguay -- fuente principal.

Estrategia segun la seccion 7: no hay API publica, pero la pagina de busqueda
es server-rendered con Next.js y expone todo su estado en
`<script id="__NEXT_DATA__">`. Se usa ese JSON interno (nivel 2 de la
escalera), no scraping de HTML ni navegador.

El detalle importante: ese JSON ya trae descripcion completa, coordenadas,
areas, dormitorios, banos, amenities y la inmobiliaria. Por eso
`needs_detail()` siempre es False y un run son ~5 requests en total, no 150
(secciones 6 y 14).
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote, urlsplit, urlunsplit

from ..budget import ExecutionBudget
from ..config import Config, SearchConfig
from ..http import FetchError, HttpFetcher
from ..models import Listing, SourceResult
from ..normalize import detect_features, positive, title_case_place, to_float, to_int
from .base import BaseSource

log = logging.getLogger(__name__)

BASE_URL = "https://www.infocasas.com.uy"

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


class InfocasasParseError(Exception):
    """El HTML no tenia la estructura esperada."""


def extract_next_data(html: str) -> dict:
    match = _NEXT_DATA.search(html)
    if not match:
        raise InfocasasParseError("no se encontro el bloque __NEXT_DATA__")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise InfocasasParseError(f"__NEXT_DATA__ no es JSON valido: {exc}") from exc


def extract_search_payload(html: str) -> tuple[list[dict], dict]:
    """Devuelve (items, paginatorInfo) desde el HTML de una busqueda."""
    data = extract_next_data(html)
    search = (
        data.get("props", {})
        .get("pageProps", {})
        .get("fetchResult", {})
        .get("searchFast")
    )
    if not isinstance(search, dict):
        raise InfocasasParseError("__NEXT_DATA__ no contiene fetchResult.searchFast")
    items = search.get("data")
    if not isinstance(items, list):
        raise InfocasasParseError("searchFast.data no es una lista")
    return items, search.get("paginatorInfo") or {}


def is_plausible_search(items: list[dict], paginator: dict) -> bool:
    """Si la respuesta parece una pagina de resultados real (seccion 24).

    Mira el contenido, nunca el status code: un portal puede devolver 200 con
    una pagina anti-bot o un rediseno que rompe el parser. Un total de 0 con
    items vacios es indistinguible de un scraper roto, asi que se trata como
    no-plausible y deja que source_health decida tras varias corridas.
    """
    if items:
        return True
    return bool(paginator) and int(paginator.get("total") or 0) > 0


def _absolute_url(link: str | None) -> str:
    if not link:
        return BASE_URL
    if link.startswith("http"):
        url = link
    else:
        url = f"{BASE_URL}/{link.lstrip('/')}"
    # Los slugs traen tildes ("...2-banos..." viene como "2-baños").
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=quote(parts.path, safe="/%")))


def paginated_url(base: str, page: int) -> str:
    """InfoCasas pagina con el sufijo /pagina2, /pagina3, ..."""
    if page <= 1:
        return base
    return f"{base.rstrip('/')}/pagina{page}"


def _first_name(container: dict, key: str) -> str | None:
    value = container.get(key)
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return title_case_place(value[0].get("name"))
    if isinstance(value, dict) and value.get("name"):
        return title_case_place(value.get("name"))
    return None


def _technical(item: dict) -> dict[str, str]:
    sheet = item.get("technicalSheet") or []
    return {
        entry.get("field"): (entry.get("value") or "")
        for entry in sheet
        if isinstance(entry, dict) and entry.get("field")
    }


def parse_listing(item: dict) -> Listing | None:
    """Mapea un item crudo de searchFast a nuestro modelo normalizado."""
    external_id = item.get("id")
    if external_id is None:
        return None

    price_block = item.get("price") or {}
    currency = ((price_block.get("currency") or {}).get("name")) or item.get("currency")
    # hidePrice significa "consultar precio": sin precio no se puede evaluar.
    price = None if price_block.get("hidePrice") else to_float(price_block.get("amount"))
    price_usd = to_float(item.get("price_amount_usd"))

    locations = item.get("locations") or {}
    technical = _technical(item)

    facilities = [
        f.get("name")
        for f in (item.get("facilities") or [])
        if isinstance(f, dict) and f.get("name")
    ]
    features = detect_features(
        title=item.get("title"),
        description=item.get("description"),
        facilities=facilities,
        extra={
            "garage": bool(item.get("hasGarage")) or bool(to_int(item.get("garage"))),
            # 'financing' no vacio en la ficha tecnica = admite credito.
            "acepta_banco": bool((technical.get("financing") or "").strip()),
        },
    )

    images = item.get("images") or []
    image_url = item.get("img") or (
        images[0].get("image") if images and isinstance(images[0], dict) else None
    )

    return Listing(
        source="infocasas",
        external_id=str(external_id),
        canonical_url=_absolute_url(item.get("link")),
        title=item.get("title"),
        description=item.get("description"),
        currency=currency,
        price=price,
        price_usd=price_usd if price_usd else price if currency == "U$S" else None,
        bedrooms=to_int(positive(to_float(item.get("bedrooms")))),
        bathrooms=to_int(positive(to_float(item.get("bathrooms")))),
        built_area_m2=positive(to_float(item.get("m2Built"))),
        land_area_m2=positive(to_float(item.get("m2Terrain"))),
        neighborhood=_first_name(locations, "neighbourhood")
        or title_case_place(technical.get("neighborhood_name")),
        city=_first_name(locations, "city") or _first_name(locations, "locality"),
        department=_first_name(locations, "state"),
        address=item.get("address"),
        latitude=to_float(item.get("latitude")),
        longitude=to_float(item.get("longitude")),
        agency=((item.get("owner") or {}).get("name")),
        image_url=image_url,
        published_at=item.get("created_at"),
        features=features,
        detail_complete=True,  # la busqueda ya trae todo
    )


class InfocasasSource(BaseSource):
    name = "infocasas"
    requires_browser = False

    def search(
        self,
        searches: tuple[SearchConfig, ...],
        fetcher: HttpFetcher,
        budget: ExecutionBudget,
        cfg: Config,
    ) -> SourceResult:
        max_pages = int(cfg.scraping.get("max_search_pages_per_source", 5))
        result = SourceResult(source=self.name)
        seen: set[str] = set()
        any_plausible = False

        for search in searches:
            for page in range(1, max_pages + 1):
                if budget.exhausted:
                    log.warning("presupuesto agotado; se corta la paginacion")
                    break

                url = paginated_url(search.url, page)
                try:
                    response = fetcher.get(url)
                    items, paginator = extract_search_payload(response.text)
                except (FetchError, InfocasasParseError) as exc:
                    log.warning("infocasas %s pagina %d fallo: %s", search.name, page, exc)
                    result.error = str(exc)
                    break

                result.pages_fetched += 1
                if is_plausible_search(items, paginator):
                    any_plausible = True

                for raw in items:
                    listing = parse_listing(raw)
                    # El mismo aviso puede repetirse entre busquedas solapadas.
                    if listing and listing.external_id not in seen:
                        seen.add(listing.external_id)
                        result.listings.append(listing)

                if not paginator.get("hasMorePages"):
                    break

        # Si ninguna pagina parecio un resultado valido, la fuente esta rota o
        # bloqueada aunque todos los requests hayan devuelto 200.
        result.plausible = any_plausible
        if not any_plausible and result.error is None:
            result.error = "ninguna pagina devolvio resultados plausibles"
        return result

    def needs_detail(self, listing: Listing, known: Listing | None) -> bool:
        """Nunca: la busqueda de InfoCasas ya trae el detalle completo."""
        return False
