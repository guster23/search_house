"""Normalizacion de texto, ubicaciones y caracteristicas.

Todo lo que dependa del idioma o del vocabulario de un portal vive aca, para
que el scoring y los filtros trabajen siempre sobre valores canonicos.
"""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize_text(value: str | None) -> str:
    """Minusculas, sin tildes, espacios colapsados.

    Base de toda comparacion textual: "Parrillero / Barbacoa" y
    "parrillero/barbacoa" deben coincidir.
    """
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _WS.sub(" ", stripped.lower()).strip()


def title_case_place(value: str | None) -> str | None:
    """Nombre de lugar presentable, preservando el original si ya viene bien."""
    if not value:
        return None
    value = _WS.sub(" ", str(value)).strip()
    return value or None


# --- Caracteristicas -------------------------------------------------------
#
# Claves canonicas: deben coincidir con las de `scoring.features` en config.yaml.

_FEATURE_TEXT_PATTERNS: dict[str, tuple[str, ...]] = {
    "garage": ("garaje", "garage", "cochera", "estacionamiento"),
    "parrillero": ("parrillero", "barbacoa", "parrilla"),
    "fondo": ("fondo", "jardin", "patio", "terreno al fondo"),
    "padron_unico": ("padron unico", "padron propio", "padron individual"),
    "acepta_banco": (
        "acepta banco",
        "apto banco",
        "apto credito",
        "apto bhu",
        "financiacion bancaria",
        "credito bancario",
        "apto hipoteca",
    ),
    "piscina": ("piscina", "pileta"),
}

# Nombres exactos del catalogo de facilities de InfoCasas.
_FEATURE_FACILITY_NAMES: dict[str, tuple[str, ...]] = {
    "garage": ("garaje", "cochera"),
    "parrillero": ("parrillero / barbacoa", "barbacoa"),
    "fondo": ("jardin / patio", "patio", "jardin"),
    "piscina": ("piscina",),
}


def detect_features(
    *,
    title: str | None = None,
    description: str | None = None,
    facilities: list[str] | None = None,
    extra: dict[str, object] | None = None,
) -> set[str]:
    """Deriva las caracteristicas canonicas de una propiedad.

    Combina el catalogo estructurado del portal (confiable) con el texto libre
    (ruidoso pero es la unica fuente para cosas como "padron unico").
    """
    found: set[str] = set()

    for name in facilities or []:
        norm = normalize_text(name)
        for key, candidates in _FEATURE_FACILITY_NAMES.items():
            if norm in candidates:
                found.add(key)

    blob = normalize_text(f"{title or ''} {description or ''}")
    if blob:
        for key, patterns in _FEATURE_TEXT_PATTERNS.items():
            if any(p in blob for p in patterns):
                found.add(key)

    for key, value in (extra or {}).items():
        if value:
            found.add(key)

    return found


# --- Numeros ---------------------------------------------------------------

_NUM_TOKEN = re.compile(r"-?[\d.,]*\d")
_THOUSANDS_DOT = re.compile(r"^-?\d{1,3}(?:\.\d{3})+$")
_THOUSANDS_COMMA = re.compile(r"^-?\d{1,3}(?:,\d{3})+$")


def to_float(value: object) -> float | None:
    """Convierte a float tolerando '132 m2', 'U$S 269.000', '1,5' y vacios.

    Uruguay usa '.' como separador de miles y ',' como decimal, pero los
    portales mezclan ambas convenciones. En vez de asumir una, se decide por
    la forma del numero: '269.000' son miles, '34.86' es un decimal.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    match = _NUM_TOKEN.search(str(value))
    if not match:
        return None
    token = match.group()

    if "," in token and "." in token:
        # El separador que aparece ultimo es el decimal.
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif _THOUSANDS_DOT.match(token):
        token = token.replace(".", "")
    elif _THOUSANDS_COMMA.match(token):
        token = token.replace(",", "")
    elif "," in token:
        token = token.replace(",", ".")

    try:
        return float(token)
    except ValueError:
        return None


def to_int(value: object) -> int | None:
    number = to_float(value)
    return None if number is None else int(number)


def positive(value: float | None) -> float | None:
    """Trata 0 y negativos como 'dato ausente'.

    Los portales usan 0 para 'no informado' en areas y dormitorios; dejarlo
    pasar arruinaria las estadisticas de comparables.
    """
    if value is None or value <= 0:
        return None
    return value
