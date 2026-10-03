"""Tests contra la respuesta real del portal, no contra HTML inventado."""

import pytest

from house_watch.sources.infocasas import (
    InfocasasParseError,
    InfocasasSource,
    extract_search_payload,
    is_plausible_search,
    paginated_url,
    parse_listing,
)


def test_extrae_los_21_items_de_la_pagina(infocasas_html):
    items, paginator = extract_search_payload(infocasas_html)
    assert len(items) == 21
    assert paginator["total"] > 0
    assert paginator["hasMorePages"] is True


def test_parse_listing_mapea_todos_los_campos(infocasas_html):
    items, _ = extract_search_payload(infocasas_html)
    listing = parse_listing(items[0])

    assert listing.source == "infocasas"
    assert listing.external_id == "194134957"
    assert listing.price_usd == 269000
    assert listing.bedrooms == 4
    assert listing.bathrooms == 2
    assert listing.built_area_m2 == 132
    assert listing.land_area_m2 == 265
    assert listing.neighborhood == "Brazo Oriental"
    assert listing.department == "Montevideo"
    assert listing.agency == "NH Negocios Inmobiliarios"
    assert listing.latitude == pytest.approx(-34.8627335)
    # La busqueda ya trae la descripcion completa: por eso no se abre detalle.
    assert len(listing.description) > 1000
    assert listing.detail_complete is True


def test_canonical_url_escapa_tildes_del_slug(infocasas_html):
    items, _ = extract_search_payload(infocasas_html)
    listing = parse_listing(items[0])
    assert listing.canonical_url.startswith("https://www.infocasas.com.uy/")
    assert "ñ" not in listing.canonical_url
    assert "%C3%B1" in listing.canonical_url


def test_nunca_necesita_abrir_detalle(infocasas_html):
    items, _ = extract_search_payload(infocasas_html)
    listing = parse_listing(items[0])
    assert InfocasasSource().needs_detail(listing, None) is False


def test_plausibilidad_mira_contenido_no_status():
    assert is_plausible_search([{"id": 1}], {}) is True
    assert is_plausible_search([], {"total": 3906}) is True
    # Sin items y sin total: indistinguible de un scraper roto.
    assert is_plausible_search([], {"total": 0}) is False
    assert is_plausible_search([], {}) is False


def test_paginacion_usa_el_sufijo_del_portal():
    base = "https://www.infocasas.com.uy/venta/casas/montevideo"
    assert paginated_url(base, 1) == base
    assert paginated_url(base, 3) == f"{base}/pagina3"
    assert paginated_url(base + "/", 2) == f"{base}/pagina2"
