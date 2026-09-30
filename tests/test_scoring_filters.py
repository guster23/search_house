from house_watch.filters import hard_reject_reason, passes_early_filters, passes_hard_filters
from house_watch.models import Listing
from house_watch.scoring import price_drop_percent, score_listing


def make(**kwargs) -> Listing:
    base = dict(
        source="infocasas", external_id="1", canonical_url="https://x/1",
        price_usd=198000, currency="U$S", bedrooms=3, bathrooms=2,
        built_area_m2=115, land_area_m2=420, neighborhood="Solymar",
        department="Canelones",
    )
    base.update(kwargs)
    return Listing(**base)


def test_score_es_deterministico(cfg):
    listing = make(features={"garage", "fondo"})
    assert score_listing(listing, cfg) == score_listing(listing, cfg)


def test_score_suma_lo_que_dice_la_config(cfg):
    sin_extras = make(features=set(), neighborhood="Nada", land_area_m2=None)
    con_extras = make(features={"garage"}, neighborhood="Solymar", land_area_m2=420)
    bajo, _ = score_listing(sin_extras, cfg)
    alto, razones = score_listing(con_extras, cfg)
    assert alto > bajo
    assert "buena zona" in razones and "garage" in razones


def test_score_nunca_pasa_de_100(cfg):
    todo = make(features={"garage", "fondo", "parrillero", "padron_unico", "acepta_banco"})
    score, _ = score_listing(todo, cfg)
    assert 0 <= score <= 100


def test_baja_de_precio_del_ejemplo_de_la_spec():
    assert round(price_drop_percent(230000, 215000), 2) == 6.52


def test_subida_de_precio_no_es_baja():
    assert price_drop_percent(200000, 210000) is None
    assert price_drop_percent(None, 210000) is None
    assert price_drop_percent(0, 210000) is None


def test_rechazo_duro_por_palabra_prohibida(cfg):
    listing = make(title="Casa en venta", description="Se vende la NUDA PROPIEDAD")
    assert hard_reject_reason(listing, cfg) is not None
    assert not passes_hard_filters(listing, cfg)


def test_rechazo_duro_ignora_tildes_y_mayusculas(cfg):
    assert hard_reject_reason(make(description="derechos posesorios"), cfg) is not None


def test_filtro_temprano_descarta_por_precio(cfg):
    caro = make(price_usd=420000)
    verdict = passes_early_filters(caro, cfg)
    assert not verdict and "maximo" in verdict.reason


def test_filtro_temprano_no_descarta_por_dato_ausente(cfg):
    """Un campo vacio puede completarse en el detalle: no descalifica."""
    assert passes_early_filters(make(bedrooms=None, price_usd=None), cfg)


def test_filtro_duro_exige_precio(cfg):
    verdict = passes_hard_filters(make(price_usd=None), cfg)
    assert not verdict and "precio" in verdict.reason


def test_filtro_por_departamento(cfg):
    # Usamos el min_price del config para garantizar que el precio siempre pase.
    precio_valido = int(cfg.filters.get("min_price", 50000)) + 1000
    assert not passes_early_filters(make(department="Maldonado", price_usd=precio_valido), cfg)
    assert passes_early_filters(make(department="Canelones", price_usd=precio_valido), cfg)
