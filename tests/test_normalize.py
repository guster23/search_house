import pytest

from house_watch.normalize import detect_features, normalize_text, positive, to_float


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("132 m2", 132.0),
        ("269.000", 269000.0),          # punto como separador de miles
        ("U$S 269.000", 269000.0),
        ("1.234.567", 1234567.0),
        ("34.86", 34.86),               # punto decimal, NO miles
        ("-56.1715603", -56.1715603),
        ("1,5", 1.5),                   # coma decimal
        ("1.234,56", 1234.56),
        ("1,234.56", 1234.56),
        (265, 265.0),
        ("", None),
        (None, None),
        ("consultar", None),
    ],
)
def test_to_float_maneja_ambas_convenciones(raw, expected):
    assert to_float(raw) == expected


def test_normalize_text_saca_tildes_y_colapsa_espacios():
    assert normalize_text("  Antigüedad   ÑOÑO ") == "antiguedad nono"


def test_positive_trata_cero_como_dato_ausente():
    # Los portales usan 0 para "no informado"; dejarlo pasar arruina las medianas.
    assert positive(0) is None
    assert positive(-5) is None
    assert positive(120) == 120


def test_detect_features_combina_catalogo_y_texto():
    found = detect_features(
        title="Casa con parrillero",
        description="Padrón único, apto banco",
        facilities=["Garaje", "Jardin / Patio"],
    )
    assert {"parrillero", "padron_unico", "acepta_banco", "garage", "fondo"} <= found


def test_detect_features_vacio_no_explota():
    assert detect_features() == set()
