"""Gallito Luis Uruguay -- fuente con navegador real y JSON-LD.

Estrategia (2026-10-03):
Gallito bloquea clientes HTTP estandar (httpx/curl) con Cloudflare managed challenge
(HTTP 403 cf-mitigated: challenge). Sin embargo, un navegador real (Chrome headed
bajo Xvfb con Playwright) supera el challenge ~80% de las veces en paginas de busqueda,
y con un retry loop de 2-3 intentos alcanza fiabilidad practicamente total.

Hallazgo clave:
La pagina de busqueda (`/inmuebles/casas/venta/...`) expone en el HTML un bloque
`<script type="application/ld+json">` con un `ItemList` de `RealEstateListing`.
Este JSON estructurado contiene todos los datos relevantes:
- ID de aviso (vtaCod)
- Precio y moneda
- Dormitorios y baños
- Metros cuadrados construidos (floorSize)
- Barrio (addressLocality) y departamento (addressRegion)
- Coordenadas geograficas (latitud y longitud)
- Fecha de publicacion (datePosted)
- Inmobiliaria / vendedor (seller)
- Fotos y descripcion

<<<<<<< Updated upstream
Es un managed challenge de Cloudflare. No se intenta resolver ni evadir
(seccion 29). Habilitarla requeriria navegador real, y aun asi el challenge
puede no pasar.
=======
Por lo tanto, NO es necesario abrir las paginas de detalle de cada aviso (las cuales
ademas presentan mayor proteccion antibot). La busqueda ya provee el detalle completo
(`detail_complete = True`), de forma analoga a InfoCasas.
>>>>>>> Stashed changes
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from selectolax.parser import HTMLParser

from ..browser import BrowserFetcher, BrowserUnavailable
from ..budget import ExecutionBudget
from ..config import Config, SearchConfig
from ..http import HttpFetcher
from ..models import Listing, SourceResult
from ..normalize import detect_features, positive, title_case_place, to_float, to_int
from .base import BaseSource

log = logging.getLogger(__name__)

BASE_URL = "https://www.gallito.com.uy"

_JSON_LD_RE = re.compile(
    r"""<script[^>]*type=["']application/ld\+json["'][^>]*>(.*?)</script>""",
    re.DOTALL | re.IGNORECASE,
)
_INMUEBLE_ID_RE = re.compile(r"inmuebles-(\d+)")


class GallitoParseError(Exception):
    """El HTML no tenia la estructura JSON-LD esperada."""


def extract_gallito_listings(html: str) -> list[dict]:
    """Extrae los items de tipo RealEstateListing del ItemList en JSON-LD."""
    items: list[dict] = []
    found_any_ld = False

    for match in _JSON_LD_RE.finditer(html):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        found_any_ld = True
        nodes: list[dict] = []
        if isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                nodes.extend(data["@graph"])
            else:
                nodes.append(data)
        elif isinstance(data, list):
            nodes.extend(data)

        for node in nodes:
            if isinstance(node, dict) and node.get("@type") == "ItemList":
                for elem in node.get("itemListElement") or []:
                    it = elem.get("item")
                    if isinstance(it, dict) and it.get("@type") == "RealEstateListing":
                        items.append(it)

    if not items and not found_any_ld:
        raise GallitoParseError("No se encontro ningun bloque JSON-LD en la pagina")
    return items


def parse_listing(item: dict) -> Listing | None:
    """Mapea un item crudo de RealEstateListing a nuestro modelo Listing normalizado."""
    url = item.get("url") or ""
    ident = item.get("identifier")
    ext_id = None
    if isinstance(ident, dict):
        ext_id = ident.get("value")
    elif ident:
        ext_id = str(ident)

    if not ext_id and url:
        m = _INMUEBLE_ID_RE.search(url)
        if m:
            ext_id = m.group(1)

    if not ext_id:
        return None

    offers = item.get("offers") or {}
    about = item.get("about") or {}
    addr = about.get("address") or {}
    geo = about.get("geo") or {}

    currency = offers.get("priceCurrency")
    price = to_float(offers.get("price"))
    price_usd = price if currency in ("USD", "U$S") else None

    title = item.get("name")
    description = item.get("description")

    # Superficie construida y terreno
    floor_size = about.get("floorSize") or {}
    built_area = positive(
        to_float(floor_size.get("value") if isinstance(floor_size, dict) else floor_size)
    )
    if built_area is None:
        m_area = re.search(r"(\d+)\s*(?:m2|m²)", f"{title or ''} {description or ''}", re.IGNORECASE)
        if m_area:
            built_area = positive(to_float(m_area.group(1)))

    lot_size = about.get("lotSize") or about.get("landSize") or {}
    land_area = positive(
        to_float(lot_size.get("value") if isinstance(lot_size, dict) else lot_size)
    )

    bedrooms = to_int(positive(to_float(about.get("numberOfBedrooms"))))
    if bedrooms is None and title:
        m_mas = re.search(r"m[aá]s de\s+(\d+)\s+dormitorio", title, re.IGNORECASE)
        if m_mas:
            bedrooms = int(m_mas.group(1))
        else:
            m_dorm = re.search(r"(\d+)\s+dormitorio", title, re.IGNORECASE)
            if m_dorm:
                bedrooms = int(m_dorm.group(1))

    # Imagen
    images = item.get("image") or []
    image_url = None
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            image_url = first.get("contentUrl") or first.get("url")
        elif isinstance(first, str):
            image_url = first
    elif isinstance(images, str):
        image_url = images

    # Inmobiliaria / vendedor
    seller = offers.get("seller") or {}
    agency = seller.get("name") if isinstance(seller, dict) else str(seller) if seller else None

    features = detect_features(
        title=title,
        description=description,
    )

    return Listing(
        source="gallito",
        external_id=str(ext_id),
        canonical_url=url,
        title=title,
        description=description,
        currency=currency,
        price=price,
        price_usd=price_usd,
        bedrooms=bedrooms,
        bathrooms=to_int(positive(to_float(about.get("numberOfBathroomsTotal")))),
        built_area_m2=built_area,
        land_area_m2=land_area,
        neighborhood=title_case_place(addr.get("addressLocality")),
        city=title_case_place(addr.get("addressLocality")),
        department=title_case_place(addr.get("addressRegion")),
        address=addr.get("streetAddress"),
        latitude=to_float(geo.get("latitude")),
        longitude=to_float(geo.get("longitude")),
        agency=agency,
        image_url=image_url,
        published_at=item.get("datePosted"),
        features=features,
        detail_complete=True,
    )


def is_plausible_search(items: list[dict], html: str = "") -> bool:
    """Verifica si la respuesta parece un resultado de busqueda real."""
    if items:
        return True
    if html and ("0 propiedades" in html or "no se encontraron avisos" in html.lower()):
        return True
    return False


def paginated_url(base: str, page: int) -> str:
    """Gallito pagina agregando ?pag=N al URL."""
    if page <= 1:
        return base
    parts = urlsplit(base)
    query_params = dict(parse_qsl(parts.query))
    query_params["pag"] = str(page)
    return urlunsplit(parts._replace(query=urlencode(query_params)))


def has_next_page(html: str, current_page: int, items_count: int) -> bool:
    """Determina si hay paginas adicionales basandose en el paginador HTML."""
    if items_count == 0 or items_count < 20:
        return False
    tree = HTMLParser(html)
    paginador = tree.css_first("#paginador, .pagination")
    if not paginador:
        return False
    for a in paginador.css("a"):
        href = a.attributes.get("href", "")
        text = a.text().strip()
        if f"pag={current_page + 1}" in href or text in (">", "&gt;", "»"):
            return True
    return False


class GallitoSource(BaseSource):
    name = "gallito"
    requires_browser = True

    def __init__(self, browser_fetcher: BrowserFetcher | None = None):
        self._browser_fetcher = browser_fetcher

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

        try:
            fetcher_ctx = self._browser_fetcher or BrowserFetcher(cfg.scraping, budget)
            with fetcher_ctx as browser:
                for search in searches:
                    for page in range(1, max_pages + 1):
                        if budget.exhausted:
                            log.warning("presupuesto agotado; se corta la paginacion")
                            break

                        url = paginated_url(search.url, page)
                        try:
                            response = browser.get(url)
                            if response.status_code != 200:
                                log.warning("gallito %s pagina %d status %d", search.name, page, response.status_code)
                                result.error = f"HTTP {response.status_code}: {response.title}"
                                break
                            items = extract_gallito_listings(response.text)
                        except Exception as exc:
                            log.warning("gallito %s pagina %d fallo: %s", search.name, page, exc)
                            result.error = str(exc)
                            break

                        result.pages_fetched += 1
                        if is_plausible_search(items, response.text):
                            any_plausible = True

                        for raw in items:
                            listing = parse_listing(raw)
                            if listing and listing.external_id not in seen:
                                seen.add(listing.external_id)
                                result.listings.append(listing)

                        if not has_next_page(response.text, page, len(items)):
                            break

        except BrowserUnavailable as exc:
            log.warning("Gallito no puede ejecutarse (navegador no disponible): %s", exc)
            result.error = str(exc)
            result.plausible = False
            return result
        except Exception as exc:
            log.exception("Error al ejecutar Gallito: %s", exc)
            result.error = str(exc)
            result.plausible = False
            return result

        result.plausible = any_plausible
        if not any_plausible and result.error is None:
            result.error = "ninguna pagina devolvio resultados plausibles"
        return result

    def needs_detail(self, listing: Listing, known: Listing | None) -> bool:
        """Nunca: la busqueda de Gallito ya trae el detalle completo en JSON-LD."""
        return False
