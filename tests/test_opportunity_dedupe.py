from house_watch.dedupe import duplicate_confidence, find_duplicate
from house_watch.models import Listing
from house_watch.opportunity import evaluate


def casa(external_id="1", source="infocasas", **kwargs) -> Listing:
    base = dict(
        source=source, external_id=external_id, canonical_url="u",
        neighborhood="Solymar", bedrooms=3, built_area_m2=115,
        land_area_m2=420, price_usd=198000,
    )
    base.update(kwargs)
    return Listing(**base)


# --- oportunidad -----------------------------------------------------------

def test_sin_suficientes_comparables_no_opina(repo, cfg):
    """Con la base fria no hay estadistica: mejor no decir nada que mentir."""
    repo.upsert_listings("infocasas", [casa(str(i)) for i in range(5)])
    assert evaluate(casa("nueva"), repo, cfg) is None


def test_detecta_precio_por_debajo_de_la_mediana(repo, cfg):
    mercado = [
        casa(str(i), price_usd=1930 * 115, built_area_m2=115) for i in range(20)
    ]
    repo.upsert_listings("infocasas", mercado)

    barata = casa("barata", price_usd=1620 * 115, built_area_m2=115)
    result = evaluate(barata, repo, cfg)

    assert result is not None
    assert result.sample_size == 20
    assert result.difference_percent < -15
    assert result.is_below_market
    assert result.score > 50


def test_precio_por_encima_baja_el_score(repo, cfg):
    repo.upsert_listings("infocasas", [casa(str(i), price_usd=200000) for i in range(20)])
    cara = casa("cara", price_usd=300000)
    result = evaluate(cara, repo, cfg)
    assert result is not None and result.score < 50


def test_usa_mediana_y_no_promedio(repo, cfg):
    """Un outlier cargado por error no debe mover la referencia."""
    normales = [casa(str(i), price_usd=200000) for i in range(20)]
    normales.append(casa("outlier", price_usd=200000 * 50))
    repo.upsert_listings("infocasas", normales)

    result = evaluate(casa("nueva", price_usd=200000), repo, cfg)
    assert result is not None
    assert abs(result.difference_percent) < 1, "la mediana ignora el outlier"


def test_sin_area_no_se_puede_evaluar(repo, cfg):
    repo.upsert_listings("infocasas", [casa(str(i)) for i in range(20)])
    assert evaluate(casa("x", built_area_m2=None), repo, cfg) is None


# --- cross-posting ---------------------------------------------------------

def test_la_misma_casa_en_dos_portales_se_detecta():
    a = casa(source="infocasas", address="Av. Giannattasio 1234")
    b = casa(source="gallito", external_id="9", price_usd=199000,
             built_area_m2=118, land_area_m2=430,
             address="Avenida Giannattasio 1234")
    verdict = duplicate_confidence(a, b)
    assert verdict.is_duplicate
    assert "precio +-2%" in verdict.signals


def test_dos_casas_distintas_no_se_confunden():
    a = casa(source="infocasas")
    b = casa(source="gallito", external_id="9", neighborhood="Pocitos",
             price_usd=450000, bedrooms=5, built_area_m2=200, land_area_m2=90)
    assert not duplicate_confidence(a, b).is_duplicate


def test_poca_evidencia_no_da_confianza_alta():
    """Coincidir en lo poco que hay no alcanza para fusionar."""
    a = Listing(source="infocasas", external_id="1", canonical_url="u", bedrooms=3)
    b = Listing(source="gallito", external_id="2", canonical_url="u", bedrooms=3)
    assert not duplicate_confidence(a, b).is_duplicate


def test_no_se_compara_contra_el_mismo_portal():
    a = casa(source="infocasas", external_id="1")
    b = casa(source="infocasas", external_id="2")
    assert find_duplicate(a, [b]) is None
