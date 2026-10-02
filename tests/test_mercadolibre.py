"""Tests para el source de MercadoLibre via API oficial (token de usuario).

Se testea contra un JSON fixture que imita la respuesta real de la API
(no se hacen requests reales en CI).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from house_watch.models import Listing
from house_watch.sources.mercadolibre import (
    MercadoLibreSource,
    _search_url,
    parse_listing,
    parse_results,
    MercadoLibreAuthError,
    PAGE_SIZE,
    CATEGORY_CASAS,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixture JSON: respuesta real simplificada de /sites/MLU/search
# ---------------------------------------------------------------------------

ML_API_RESPONSE = {
    "paging": {"total": 2, "offset": 0, "limit": 50},
    "results": [
        {
            "id": "MLU123456",
            "title": "Casa en venta Montevideo 4 dormitorios",
            "price": 185000,
            "currency_id": "USD",
            "permalink": "https://www.mercadolibre.com.uy/MLU123456",
            "thumbnail": "https://http2.mlstatic.com/D_NQ_NP_thumb.jpg",
            "date_created": "2026-09-01T10:00:00.000Z",
            "location": {
                "neighborhood": {"name": "Pocitos"},
                "city": {"name": "Montevideo"},
                "state": {"name": "Montevideo"},
                "address_line": "Calle Falsa 123",
                "latitude": -34.9000,
                "longitude": -56.1500,
            },
            "attributes": [
                {"id": "BEDROOMS", "value_name": "4"},
                {"id": "BATHROOMS", "value_name": "2"},
                {"id": "COVERED_AREA", "value_name": "150"},
                {"id": "TOTAL_AREA", "value_name": "400"},
                {"id": "PARKING_LOTS", "value_name": "1"},
            ],
            "seller": {"nickname": "INMOBILIARIA XYZ"},
        },
        {
            "id": "MLU789012",
            "title": "Casa con parrillero y jardin en Solymar",
            "price": 120000,
            "currency_id": "USD",
            "permalink": "https://www.mercadolibre.com.uy/MLU789012",
            "thumbnail": "https://http2.mlstatic.com/D_NQ_NP_thumb2.jpg",
            "date_created": "2026-09-10T12:00:00.000Z",
            "location": {
                "neighborhood": {"name": "Solymar"},
                "city": {"name": "Canelones"},
                "state": {"name": "Canelones"},
                "address_line": None,
                "latitude": -34.7500,
                "longitude": -55.9000,
            },
            "attributes": [
                {"id": "BEDROOMS", "value_name": "3"},
                {"id": "BATHROOMS", "value_name": "1"},
                {"id": "COVERED_AREA", "value_name": "90"},
                {"id": "TOTAL_AREA", "value_name": "350"},
            ],
            "seller": {"nickname": "PROPIETARIO DIRECTO"},
        },
    ],
}


# ---------------------------------------------------------------------------
# Tests de parse_listing
# ---------------------------------------------------------------------------

def test_parse_listing_mapea_campos_basicos():
    item = ML_API_RESPONSE["results"][0]
    listing = parse_listing(item)

    assert listing is not None
    assert listing.source == "mercadolibre"
    assert listing.external_id == "MLU123456"
    assert listing.price_usd == 185000.0
    assert listing.currency == "USD"
    assert listing.bedrooms == 4
    assert listing.bathrooms == 2
    assert listing.built_area_m2 == 150.0
    assert listing.land_area_m2 == 400.0
    assert listing.neighborhood == "Pocitos"
    assert listing.city == "Montevideo"
    assert listing.department == "Montevideo"
    assert listing.address == "Calle Falsa 123"
    assert listing.latitude == pytest.approx(-34.9000)
    assert listing.longitude == pytest.approx(-56.1500)
    assert listing.agency == "INMOBILIARIA XYZ"
    assert listing.canonical_url == "https://www.mercadolibre.com.uy/MLU123456"
    assert listing.published_at == "2026-09-01T10:00:00.000Z"


def test_parse_listing_detecta_garage():
    item = ML_API_RESPONSE["results"][0]  # tiene PARKING_LOTS = 1
    listing = parse_listing(item)
    assert "garage" in listing.features


def test_parse_listing_detecta_parrillero_en_titulo():
    item = ML_API_RESPONSE["results"][1]  # "parrillero" en el título
    listing = parse_listing(item)
    assert "parrillero" in listing.features


def test_parse_listing_detail_complete_es_false():
    """La búsqueda no trae descripción; se completa en fetch_detail."""
    item = ML_API_RESPONSE["results"][0]
    listing = parse_listing(item)
    assert listing.detail_complete is False


def test_parse_listing_sin_id_devuelve_none():
    assert parse_listing({}) is None
    assert parse_listing({"id": None}) is None


def test_parse_listing_moneda_uyu_no_asigna_price_usd():
    item = {**ML_API_RESPONSE["results"][0], "currency_id": "UYU", "price": 5_000_000}
    listing = parse_listing(item)
    assert listing is not None
    assert listing.currency == "UYU"
    assert listing.price_usd is None
    assert listing.price == 5_000_000.0


# ---------------------------------------------------------------------------
# Tests de parse_results
# ---------------------------------------------------------------------------

def test_parse_results_devuelve_todos_los_items():
    listings, total = parse_results(ML_API_RESPONSE)
    assert total == 2
    assert len(listings) == 2


def test_parse_results_respuesta_vacia():
    listings, total = parse_results({"paging": {"total": 0}, "results": []})
    assert total == 0
    assert listings == []


# ---------------------------------------------------------------------------
# Tests de _search_url
# ---------------------------------------------------------------------------

def test_search_url_incluye_categoria_y_offset():
    url = _search_url(offset=0, extra_params={})
    assert f"category={CATEGORY_CASAS}" in url
    assert f"limit={PAGE_SIZE}" in url
    assert "offset=0" in url


def test_search_url_incluye_filtro_precio():
    url = _search_url(offset=50, extra_params={"price": "40000-250000", "price_currency": "USD"})
    assert "price=40000-250000" in url
    assert "offset=50" in url


# ---------------------------------------------------------------------------
# Tests de MercadoLibreSource (con mocks)
# ---------------------------------------------------------------------------

def _make_cfg(client_id="test_id", client_secret="test_secret"):
    """Config mínima con o sin credenciales."""
    from house_watch.config import Config, Secrets, SourceConfig, SearchConfig

    secrets = Secrets(
        ml_client_id=client_id,
        ml_client_secret=client_secret,
    )
    source_cfg = SourceConfig(
        name="mercadolibre",
        enabled=True,
        searches=(SearchConfig(name="montevideo", url="https://example.com"),),
    )
    return Config(
        sources={"mercadolibre": source_cfg},
        filters={"min_price": 40000, "max_price": 250000},
        scoring={},
        alerts={},
        opportunity={},
        scraping={"max_search_pages_per_source": 2, "request_timeout_seconds": 10},
        runtime={},
        health={},
        retention={},
        secrets=secrets,
    )


class FakeTokenStore:
    """TokenStore en memoria (misma interfaz que SqlListingRepository)."""

    def __init__(self):
        self.data: dict[str, str] = {}

    def get_state(self, key: str) -> str | None:
        return self.data.get(key)

    def set_state(self, key: str, value: str) -> None:
        self.data[key] = value


def test_search_sin_credenciales_devuelve_error():
    from house_watch.config import Config, Secrets, SourceConfig, SearchConfig
    from house_watch.budget import ExecutionBudget

    cfg = _make_cfg(client_id=None, client_secret=None)
    source = MercadoLibreSource()
    result = source.search(
        searches=(SearchConfig(name="test", url="https://example.com"),),
        fetcher=MagicMock(),
        budget=ExecutionBudget(100),
        cfg=cfg,
    )
    assert result.plausible is False
    assert "ML_CLIENT_ID" in result.error


def test_search_con_credenciales_llama_api(monkeypatch):
    from house_watch.budget import ExecutionBudget
    from house_watch.config import SearchConfig

    import httpx

    # Token de usuario ya resuelto: la fuente no llama a /oauth/token.
    monkeypatch.setattr(
        MercadoLibreSource,
        "_resolve_token",
        lambda self, cfg: "fake_user_token",
    )

    # Mock de httpx.get para la búsqueda.
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = ML_API_RESPONSE

    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: mock_response)

    cfg = _make_cfg()
    source = MercadoLibreSource()
    source.set_store(FakeTokenStore())
    result = source.search(
        searches=(SearchConfig(name="montevideo", url="https://example.com"),),
        fetcher=MagicMock(),
        budget=ExecutionBudget(100),
        cfg=cfg,
    )

    assert result.plausible is True
    assert len(result.listings) == 2
    assert result.listings[0].external_id == "MLU123456"
    assert result.listings[1].external_id == "MLU789012"
    assert result.pages_fetched == 1


def test_search_auth_fallida_devuelve_error(monkeypatch):
    from house_watch.budget import ExecutionBudget
    from house_watch.config import SearchConfig

    monkeypatch.setattr(
        MercadoLibreSource,
        "_resolve_token",
        lambda self, cfg: (_ for _ in ()).throw(
            MercadoLibreAuthError("no hay tokens de MercadoLibre guardados")
        ),
    )

    cfg = _make_cfg()
    source = MercadoLibreSource()
    result = source.search(
        searches=(SearchConfig(name="montevideo", url="https://example.com"),),
        fetcher=MagicMock(),
        budget=ExecutionBudget(100),
        cfg=cfg,
    )
    assert result.plausible is False
    assert "no hay tokens" in result.error


def test_search_sin_store_pide_ml_auth():
    """Sin store inyectado no hay forma de resolver token: error accionable."""
    from house_watch.budget import ExecutionBudget
    from house_watch.config import SearchConfig

    cfg = _make_cfg()
    source = MercadoLibreSource()
    result = source.search(
        searches=(SearchConfig(name="montevideo", url="https://example.com"),),
        fetcher=MagicMock(),
        budget=ExecutionBudget(100),
        cfg=cfg,
    )
    assert result.plausible is False
    assert "ml-auth" in result.error


def test_search_http_403_incluye_body_del_error(monkeypatch):
    """El mensaje de error incluye el body: un 403 pelado no diagnosticable."""
    from house_watch.budget import ExecutionBudget
    from house_watch.config import SearchConfig

    monkeypatch.setattr(
        MercadoLibreSource, "_resolve_token", lambda self, cfg: "fake_user_token"
    )
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = '{"message":"forbidden","error":"forbidden","status":403}'
    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: mock_response)

    cfg = _make_cfg()
    source = MercadoLibreSource()
    source.set_store(FakeTokenStore())
    result = source.search(
        searches=(SearchConfig(name="montevideo", url="https://example.com"),),
        fetcher=MagicMock(),
        budget=ExecutionBudget(100),
        cfg=cfg,
    )
    assert result.plausible is False
    assert "forbidden" in result.error


def test_needs_detail_propiedad_nueva():
    source = MercadoLibreSource()
    listing = Listing(source="mercadolibre", external_id="1", canonical_url="u", detail_complete=False)
    assert source.needs_detail(listing, known=None) is True


def test_needs_detail_sin_cambio_de_precio():
    source = MercadoLibreSource()
    listing = Listing(source="mercadolibre", external_id="1", canonical_url="u",
                      price_usd=100000, detail_complete=False)
    known = Listing(source="mercadolibre", external_id="1", canonical_url="u",
                    price_usd=100000, detail_complete=True)
    assert source.needs_detail(listing, known=known) is False


def test_needs_detail_con_cambio_de_precio():
    source = MercadoLibreSource()
    listing = Listing(source="mercadolibre", external_id="1", canonical_url="u",
                      price_usd=90000, detail_complete=False)
    known = Listing(source="mercadolibre", external_id="1", canonical_url="u",
                    price_usd=100000, detail_complete=True)
    assert source.needs_detail(listing, known=known) is True
