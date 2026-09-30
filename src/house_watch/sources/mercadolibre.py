"""MercadoLibre Uruguay -- integración via API oficial REST.

Estrategia: OAuth client_credentials (sin usuario) + endpoint de búsqueda
público. El scraping HTML devolvía HTTP 200 con página anti-bot; la API con
un App Token funciona sin navegador.

Flujo por run:
  1. POST /oauth/token  →  access_token (válido 6 h; el run dura <2 min)
  2. GET /sites/MLU/search?category=MLU1459&...  (paginado con offset)

Si las credenciales ML_CLIENT_ID / ML_CLIENT_SECRET no están en el entorno,
la fuente se comporta como BlockedSource con un mensaje descriptivo; nunca
interrumpe el pipeline.

Categorías MLU (Uruguay) relevantes:
  MLU1459  Casas
  MLU1466  Apartamentos
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from ..budget import ExecutionBudget
from ..config import Config, SearchConfig
from ..http import HttpFetcher
from ..models import Listing, SourceResult
from ..normalize import detect_features, positive, title_case_place, to_float, to_int
from .base import BaseSource

log = logging.getLogger(__name__)

API_BASE = "https://api.mercadolibre.com"
TOKEN_URL = f"{API_BASE}/oauth/token"
SEARCH_URL = f"{API_BASE}/sites/MLU/search"

# Categoría "Casas" en MLU (Uruguay).
CATEGORY_CASAS = "MLU1459"

# La API devuelve hasta 50 por página; 1 000 resultados totales.
PAGE_SIZE = 50


class MercadoLibreAuthError(Exception):
    """No se pudo obtener el App Token."""


def _get_token(client_id: str, client_secret: str, timeout: float = 10.0) -> str:
    """Obtiene un App Token via client_credentials.

    No usa HttpFetcher porque este request no es scraping de portal: es
    autenticación contra nuestra propia aplicación. Timeout corto y sin
    reintentos complejos: si falla, la fuente reporta error y el pipeline sigue.
    """
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise MercadoLibreAuthError(
            f"token fallido: HTTP {resp.status_code} — {resp.text[:200]}"
        )
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise MercadoLibreAuthError(f"respuesta sin access_token: {data}")
    return str(token)


def _search_url(offset: int, extra_params: dict[str, str]) -> str:
    params: dict[str, Any] = {
        "category": CATEGORY_CASAS,
        "limit": PAGE_SIZE,
        "offset": offset,
    }
    params.update(extra_params)
    return f"{SEARCH_URL}?{urlencode(params)}"


def _attr(attributes: list[dict], attr_id: str) -> Any:
    """Extrae el valor de un atributo por id en la lista de attributes."""
    for attr in attributes:
        if attr.get("id") == attr_id:
            return attr.get("value_name") or attr.get("value_struct")
    return None


def parse_listing(item: dict) -> Listing | None:
    """Mapea un item crudo de la API de MercadoLibre a nuestro modelo."""
    external_id = item.get("id")
    if not external_id:
        return None

    attrs = item.get("attributes") or []

    # Precio: la API lo devuelve en la moneda del anuncio.
    price = to_float(item.get("price"))
    currency = item.get("currency_id")  # "UYU" o "USD"
    price_usd = price if currency == "USD" else None

    # Ubicación.
    location = item.get("location") or {}
    neighborhood = title_case_place(
        (location.get("neighborhood") or {}).get("name")
    )
    city = title_case_place(
        (location.get("city") or {}).get("name")
    )
    department = title_case_place(
        (location.get("state") or {}).get("name")
    )
    address = location.get("address_line")
    lat = to_float(location.get("latitude"))
    lon = to_float(location.get("longitude"))

    # Atributos estructurados.
    bedrooms = to_int(_attr(attrs, "BEDROOMS"))
    bathrooms = to_int(_attr(attrs, "BATHROOMS"))
    built_area_m2 = positive(to_float(_attr(attrs, "COVERED_AREA")))
    land_area_m2 = positive(to_float(_attr(attrs, "TOTAL_AREA")))

    # Seller.
    seller = item.get("seller") or {}
    agency = seller.get("nickname") or None

    # Features desde título y descripción (la API no trae facilities aquí).
    title = item.get("title")
    description = None  # La búsqueda no trae descripción; ver needs_detail.
    features = detect_features(
        title=title,
        description=description,
        extra={
            "garage": _attr(attrs, "PARKING_LOTS") not in (None, "0"),
        },
    )

    return Listing(
        source="mercadolibre",
        external_id=str(external_id),
        canonical_url=item.get("permalink") or f"https://articulo.mercadolibre.com.uy/{external_id}",
        title=title,
        description=description,
        currency=currency,
        price=price,
        price_usd=price_usd,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        built_area_m2=built_area_m2,
        land_area_m2=land_area_m2,
        neighborhood=neighborhood,
        city=city,
        department=department,
        address=address,
        latitude=lat,
        longitude=lon,
        agency=agency,
        image_url=item.get("thumbnail"),
        published_at=item.get("date_created"),
        features=features,
        # La búsqueda no incluye descripción; se completa en fetch_detail.
        detail_complete=False,
    )


def parse_results(data: dict) -> tuple[list[Listing], int]:
    """Devuelve (listings, total) desde una respuesta paginada de la API."""
    total = int((data.get("paging") or {}).get("total") or 0)
    listings = []
    for item in data.get("results") or []:
        listing = parse_listing(item)
        if listing:
            listings.append(listing)
    return listings, total


class MercadoLibreSource(BaseSource):
    """Fuente MercadoLibre Uruguay usando la API oficial REST.

    Si las credenciales no están presentes en el entorno, actúa como
    BlockedSource: registra el error sin interrumpir el pipeline.
    """

    name = "mercadolibre"
    requires_browser = False

    def search(
        self,
        searches: tuple[SearchConfig, ...],
        fetcher: HttpFetcher,
        budget: ExecutionBudget,
        cfg: Config,
    ) -> SourceResult:
        secrets = cfg.secrets
        if not secrets.has_mercadolibre:
            msg = (
                "credenciales ML_CLIENT_ID / ML_CLIENT_SECRET no configuradas; "
                "agregá los secrets en GitHub Actions"
            )
            log.warning("mercadolibre: %s", msg)
            return SourceResult(source=self.name, listings=[], plausible=False, error=msg)

        # Obtener token una sola vez para todo el run.
        try:
            token = _get_token(
                secrets.ml_client_id,  # type: ignore[arg-type]
                secrets.ml_client_secret,  # type: ignore[arg-type]
                timeout=float(cfg.scraping.get("request_timeout_seconds", 10)),
            )
        except MercadoLibreAuthError as exc:
            log.error("mercadolibre: %s", exc)
            return SourceResult(source=self.name, listings=[], plausible=False, error=str(exc))

        max_pages = int(cfg.scraping.get("max_search_pages_per_source", 5))
        result = SourceResult(source=self.name)
        seen: set[str] = set()
        any_plausible = False

        auth_headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        request_timeout = float(cfg.scraping.get("request_timeout_seconds", 10))

        for search in searches:
            # Extraer filtros de precio del config para pasarlos a la API.
            filters = cfg.filters
            extra: dict[str, str] = {}
            min_price = filters.get("min_price")
            max_price = filters.get("max_price")
            if min_price or max_price:
                lo = int(min_price or 0)
                hi = int(max_price or 9_999_999)
                extra["price"] = f"{lo}-{hi}"
                extra["price_currency"] = "USD"

            for page in range(max_pages):
                if budget.exhausted:
                    log.warning("presupuesto agotado; se corta la paginación ML")
                    break

                offset = page * PAGE_SIZE
                url = _search_url(offset, extra)

                try:
                    resp = httpx.get(
                        url,
                        headers=auth_headers,
                        timeout=request_timeout,
                        follow_redirects=True,
                    )
                    if resp.status_code >= 400:
                        err = (
                            f"HTTP {resp.status_code} en {url} — "
                            f"{resp.text[:1000]}"
                        )
                        log.warning("mercadolibre: %s", err)
                        result.error = err
                        break
                    data = resp.json()
                except Exception as exc:
                    log.warning("mercadolibre %s offset %d: %s", search.name, offset, exc)
                    result.error = str(exc)
                    break

                result.pages_fetched += 1
                listings, total = parse_results(data)

                if listings or total > 0:
                    any_plausible = True

                for listing in listings:
                    if listing.external_id not in seen:
                        seen.add(listing.external_id)
                        result.listings.append(listing)

                # ¿Hay más páginas?
                fetched_so_far = offset + len(listings)
                if fetched_so_far >= total or not listings:
                    break

        result.plausible = any_plausible
        if not any_plausible and result.error is None:
            result.error = "ninguna búsqueda devolvió resultados plausibles"
        return result

    def needs_detail(self, listing: Listing, known: Listing | None) -> bool:
        """La búsqueda no trae descripción; se pide el detalle para propiedades nuevas."""
        if listing.detail_complete:
            return False
        # Solo abrimos el detalle si es nueva o cambió el precio.
        if known is None:
            return True
        return known.price_usd != listing.price_usd

    def fetch_detail(
        self, listing: Listing, fetcher: HttpFetcher, budget: ExecutionBudget
    ) -> Listing:
        """Completa la descripción desde el endpoint de ítem individual."""
        if budget.exhausted:
            return listing
        url = f"{API_BASE}/items/{listing.external_id}"
        try:
            resp = httpx.get(url, timeout=10.0, follow_redirects=True)
            if resp.status_code != 200:
                return listing
            data = resp.json()
        except Exception as exc:
            log.debug("mercadolibre fetch_detail %s: %s", listing.external_id, exc)
            return listing

        description = None
        # La descripción está en un endpoint separado: /items/{id}/description
        try:
            desc_resp = httpx.get(
                f"{API_BASE}/items/{listing.external_id}/description",
                timeout=10.0,
                follow_redirects=True,
            )
            if desc_resp.status_code == 200:
                description = desc_resp.json().get("plain_text") or None
        except Exception:
            pass

        # Re-detectar features con la descripción completa.
        features = detect_features(
            title=listing.title,
            description=description,
            extra={"garage": "garage" in listing.features},
        )

        from dataclasses import replace
        return replace(
            listing,
            description=description,
            features=features,
            detail_complete=True,
        )
