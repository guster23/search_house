"""Tests unitarios para la fuente Gallito Luis."""

import pytest

from house_watch.browser import BrowserResponse, BrowserUnavailable
from house_watch.budget import ExecutionBudget
from house_watch.config import SearchConfig
from house_watch.sources.gallito import (
    GallitoParseError,
    GallitoSource,
    extract_gallito_listings,
    has_next_page,
    is_plausible_search,
    paginated_url,
    parse_listing,
)


def test_extrae_los_24_items_de_la_pagina(gallito_html):
    items = extract_gallito_listings(gallito_html)
    assert len(items) == 24
    assert items[0]["@type"] == "RealEstateListing"


def test_parse_listing_mapea_todos_los_campos(gallito_html):
    items = extract_gallito_listings(gallito_html)
    listing = parse_listing(items[0])

    assert listing is not None
    assert listing.source == "gallito"
    assert listing.external_id == "28814252"
    assert listing.canonical_url == (
        "https://www.gallito.com.uy/venta-apartamento-carrasco-montevideo-3-dormitorios-inmuebles-28814252"
    )
    assert listing.title == "Apartamento en venta de 3 dormitorios en Carrasco"
    assert listing.price == 567000
    assert listing.price_usd == 567000
    assert listing.currency == "USD"
    assert listing.bedrooms == 3
    assert listing.bathrooms == 3
    assert listing.built_area_m2 == 121
    assert listing.neighborhood == "Carrasco"
    assert listing.department == "Montevideo"
    assert listing.address == "Trento"
    assert listing.agency == "Golf"
    assert listing.latitude == pytest.approx(-34.8658358)
    assert listing.longitude == pytest.approx(-56.0733619)
    assert listing.published_at == "2026-10-03"
    assert listing.image_url is not None
    assert listing.image_url.startswith("https://imagenes.gallito.com/")
    assert listing.detail_complete is True


def test_parse_listing_casa_en_malvin(gallito_html):
    items = extract_gallito_listings(gallito_html)
    # Buscamos la casa en Malvin (id 29864746)
    casa = next(
        (parse_listing(it) for it in items if it.get("identifier", {}).get("value") == "29864746"),
        None,
    )
    assert casa is not None
    assert casa.bedrooms == 4
    assert casa.bathrooms == 3
    assert casa.built_area_m2 == 234
    assert casa.price_usd == 540000
    assert casa.neighborhood == "Malvin"


def test_plausibilidad_mira_contenido():
    assert is_plausible_search([{"identifier": "1"}]) is True
    assert is_plausible_search([], "<div>No se encontraron avisos</div>") is True
    assert is_plausible_search([], "<div>0 propiedades encontradas</div>") is True
    assert is_plausible_search([], "<div>Challenge Cloudflare</div>") is False
    assert is_plausible_search([], "") is False


def test_paginacion_usa_parametro_pag():
    base = "https://www.gallito.com.uy/inmuebles/casas/venta"
    assert paginated_url(base, 1) == base
    assert paginated_url(base, 2) == f"{base}?pag=2"
    assert paginated_url(f"{base}?order=1", 3) == f"{base}?order=1&pag=3"


def test_has_next_page(gallito_html):
    assert has_next_page(gallito_html, current_page=1, items_count=24) is True
    assert has_next_page(gallito_html, current_page=1, items_count=10) is False
    assert has_next_page("", current_page=1, items_count=0) is False


def test_nunca_necesita_abrir_detalle(gallito_html):
    items = extract_gallito_listings(gallito_html)
    listing = parse_listing(items[0])
    assert GallitoSource().needs_detail(listing, None) is False


class MockBrowserFetcher:
    """Mock que simula BrowserFetcher devolviendo el fixture HTML."""

    def __init__(self, html: str, status_code: int = 200):
        self.html = html
        self.status_code = status_code
        self.requested_urls: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def get(self, url: str, **kwargs) -> BrowserResponse:
        self.requested_urls.append(url)
        return BrowserResponse(
            status_code=self.status_code,
            text=self.html,
            title="Venta de Casas | Gallito",
            url=url,
        )


def test_gallito_source_search_con_mock_browser(gallito_html, cfg):
    mock_browser = MockBrowserFetcher(gallito_html)
    source = GallitoSource(browser_fetcher=mock_browser)

    searches = (
        SearchConfig(name="montevideo", url="https://www.gallito.com.uy/inmuebles/casas/venta/montevideo"),
    )
    budget = ExecutionBudget(60)
    result = source.search(searches, fetcher=None, budget=budget, cfg=cfg)

    assert result.ok is True
    assert result.plausible is True
    assert len(result.listings) == 24
    assert result.pages_fetched >= 1
    assert "https://www.gallito.com.uy/inmuebles/casas/venta/montevideo" in mock_browser.requested_urls[0]


def test_gallito_source_maneja_browser_unavailable(cfg):
    class FailingBrowserFetcher:
        def __enter__(self):
            raise BrowserUnavailable("Playwright no disponible")

        def __exit__(self, *args):
            pass

    source = GallitoSource(browser_fetcher=FailingBrowserFetcher())
    searches = (
        SearchConfig(name="montevideo", url="https://www.gallito.com.uy/inmuebles/casas/venta/montevideo"),
    )
    budget = ExecutionBudget(60)
    result = source.search(searches, fetcher=None, budget=budget, cfg=cfg)

    assert result.ok is False
    assert result.plausible is False
    assert "Playwright no disponible" in result.error
