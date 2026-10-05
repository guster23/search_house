"""Score de preferencias (seccion 16).

Completamente determinista y sin servicios externos: los mismos datos dan
siempre el mismo puntaje. Todos los pesos salen de config.yaml para poder
ajustar criterios sin tocar codigo (seccion 40).
"""

from __future__ import annotations

from .config import Config
from .models import Listing
from .normalize import normalize_text

# Etiquetas legibles para el mensaje de Telegram.
_FEATURE_LABELS = {
    "garage": "garage",
    "fondo": "fondo",
    "parrillero": "parrillero",
    "padron_unico": "padron unico",
    "acepta_banco": "acepta banco",
    "piscina": "piscina",
}

MAX_SCORE = 100


def score_listing(listing: Listing, cfg: Config) -> tuple[int, list[str]]:
    """Devuelve (score 0-100, razones) para una propiedad.

    Las razones son las lineas '+ ...' del mensaje: explican por que una casa
    puntuo alto, que es lo que hace la alerta accionable en vez de un numero.
    """
    s = cfg.scoring
    score = float(s.get("base", 50))
    reasons: list[str] = []

    ideal = s.get("ideal_price") or {}
    price = listing.price_usd
    if price is not None and ideal:
        low, high = ideal.get("min"), ideal.get("max")
        if low is not None and high is not None and float(low) <= price <= float(high):
            score += float(ideal.get("points", 0))
            reasons.append("precio dentro del ideal")

    hoods = s.get("preferred_neighborhoods") or {}
    names = hoods.get("names") or []
    if names and listing.neighborhood:
        wanted = {normalize_text(n) for n in names}
        # Coincidencia por contencion: "Solymar Sur" debe matchear "Solymar".
        actual = normalize_text(listing.neighborhood)
        if actual in wanted or any(w and w in actual for w in wanted):
            score += float(hoods.get("points", 0))
            reasons.append("buena zona")

    beds = s.get("bedrooms") or {}
    ideal_min = beds.get("ideal_min")
    if ideal_min is not None and listing.bedrooms is not None:
        if listing.bedrooms >= int(ideal_min):
            score += float(beds.get("points", 0))
            reasons.append(f"{listing.bedrooms} dormitorios")

    land = s.get("land_area") or {}
    land_min = land.get("min_m2")
    if land_min is not None and listing.land_area_m2 is not None:
        if listing.land_area_m2 >= float(land_min):
            score += float(land.get("points", 0))
            reasons.append(f"terreno {listing.land_area_m2:.0f} m2")

    for key, points in (s.get("features") or {}).items():
        if key in listing.features and float(points) > 0:
            score += float(points)
            reasons.append(_FEATURE_LABELS.get(key, key))

    return max(0, min(MAX_SCORE, round(score))), reasons


def should_alert(listing: Listing, cfg: Config) -> bool:
    """Regla de seccion 20: nuevo Y pasa filtros duros Y score suficiente.

    Aca solo se evalua el score; 'nuevo' y 'pasa filtros' los decide el
    pipeline, que es quien conoce el estado previo.
    """
    return listing.score is not None and listing.score >= cfg.min_alert_score


def price_drop_percent(old_price: float | None, new_price: float | None) -> float | None:
    """Caida porcentual positiva, o None si no aplica (seccion 21)."""
    if not old_price or not new_price or old_price <= 0:
        return None
    if new_price >= old_price:
        return None
    return (old_price - new_price) / old_price * 100.0
