from house_watch.models import Listing
from house_watch.notify.messages import (
    new_listing_message,
    price_drop_message,
    weekly_summary_message,
)
from house_watch.opportunity import OpportunityResult


def listing() -> Listing:
    return Listing(
        source="infocasas", external_id="1",
        canonical_url="https://www.infocasas.com.uy/x/1",
        neighborhood="Solymar", department="Canelones", price_usd=198000,
        currency="U$S", bedrooms=3, bathrooms=2, built_area_m2=115,
        land_area_m2=420, agency="InfoCasas", score=84,
        score_reasons=["precio dentro del ideal", "buena zona", "garage"],
    )


def test_mensaje_de_nueva_propiedad_tiene_lo_esencial():
    text = new_listing_message(listing())
    assert "Nueva propiedad interesante" in text
    assert "USD 198.000" in text
    assert "Solymar" in text
    assert "84/100" in text
    assert "https://www.infocasas.com.uy/x/1" in text


def test_la_linea_de_oportunidad_aparece_solo_si_hay_datos():
    sin_datos = new_listing_message(listing())
    assert "Oportunidad" not in sin_datos

    con_datos = new_listing_message(
        listing(),
        OpportunityResult(score=78, price_per_m2=1620, median_price_per_m2=1930,
                          difference_percent=-14.0, sample_size=22),
    )
    assert "Oportunidad: 78/100" in con_datos
    assert "14% debajo de comparables" in con_datos


def test_mensaje_de_baja_de_precio():
    text = price_drop_message(listing(), old_price=230000, drop_percent=6.52)
    assert "Bajó de precio" in text
    assert "USD 230.000" in text and "USD 198.000" in text
    assert "6.5% menos" in text


def test_resumen_semanal_marca_el_estado_de_cada_fuente():
    text = weekly_summary_message(
        {"seen": 1842, "new": 73, "interesting": 8, "alerts": 3},
        {"infocasas": "ok", "gallito": "degraded"},
    )
    assert "1.842 listings revisados" in text
    assert "infocasas ✅" in text
    assert "gallito ⚠️" in text


def test_una_propiedad_sin_precio_no_rompe_el_mensaje():
    sin_precio = listing()
    sin_precio.price_usd = None
    assert "precio no publicado" in new_listing_message(sin_precio)
