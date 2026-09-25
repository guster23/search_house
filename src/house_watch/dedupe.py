"""Deteccion de cross-posting entre portales (seccion 19).

Dos inmobiliarias pueden publicar la misma casa. El match exacto por
(source, external_id) lo garantiza la constraint UNIQUE de la DB; aca se
resuelve el caso dificil: la misma propiedad en dos portales distintos.

Nunca se fusiona automaticamente con confianza baja. Se calcula un
`duplicate_confidence` y la decision queda registrada, no impuesta.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from .models import Listing
from .normalize import normalize_text

# Tolerancias de la seccion 19.
_PRICE_TOLERANCE = 0.02   # +-2%
_AREA_TOLERANCE = 0.10    # +-10%

MERGE_THRESHOLD = 0.85    # por debajo de esto no se fusiona


@dataclass(frozen=True)
class DuplicateVerdict:
    confidence: float
    signals: tuple[str, ...]

    @property
    def is_duplicate(self) -> bool:
        return self.confidence >= MERGE_THRESHOLD


def _within(a: float | None, b: float | None, tolerance: float) -> bool | None:
    """True/False si ambos valores existen, None si falta alguno."""
    if not a or not b:
        return None
    return abs(a - b) <= max(a, b) * tolerance


def duplicate_confidence(a: Listing, b: Listing) -> DuplicateVerdict:
    """Confianza 0..1 de que dos publicaciones sean la misma propiedad."""
    if a.source == b.source and a.external_id == b.external_id:
        return DuplicateVerdict(1.0, ("mismo aviso",))

    weights: list[tuple[float, bool]] = []
    signals: list[str] = []

    hood_a, hood_b = normalize_text(a.neighborhood), normalize_text(b.neighborhood)
    if hood_a and hood_b:
        match = hood_a == hood_b
        weights.append((0.20, match))
        if match:
            signals.append("misma zona")

    price = _within(a.price_usd, b.price_usd, _PRICE_TOLERANCE)
    if price is not None:
        weights.append((0.30, price))
        if price:
            signals.append("precio +-2%")

    if a.bedrooms and b.bedrooms:
        match = a.bedrooms == b.bedrooms
        weights.append((0.15, match))
        if match:
            signals.append("mismos dormitorios")

    built = _within(a.built_area_m2, b.built_area_m2, _AREA_TOLERANCE)
    if built is not None:
        weights.append((0.15, built))
        if built:
            signals.append("area edificada +-10%")

    land = _within(a.land_area_m2, b.land_area_m2, _AREA_TOLERANCE)
    if land is not None:
        weights.append((0.10, land))
        if land:
            signals.append("terreno +-10%")

    addr_a, addr_b = normalize_text(a.address), normalize_text(b.address)
    if addr_a and addr_b:
        similarity = SequenceMatcher(None, addr_a, addr_b).ratio()
        weights.append((0.10, similarity >= 0.85))
        if similarity >= 0.85:
            signals.append("misma direccion")

    if not weights:
        return DuplicateVerdict(0.0, ())

    # Normalizado por el peso disponible: comparar dos avisos con pocos datos
    # no debe dar confianza alta solo porque coincidio lo poco que habia.
    available = sum(w for w, _ in weights)
    achieved = sum(w for w, ok in weights if ok)
    confidence = achieved / available if available else 0.0

    # Con poca evidencia disponible, techo mas bajo.
    if available < 0.6:
        confidence *= 0.7

    return DuplicateVerdict(round(confidence, 3), tuple(signals))


def find_duplicate(candidate: Listing, pool: list[Listing]) -> tuple[Listing, DuplicateVerdict] | None:
    """El mejor duplicado de `candidate` en `pool`, si supera el umbral."""
    best: tuple[Listing, DuplicateVerdict] | None = None
    for other in pool:
        if other.source == candidate.source:
            continue  # mismo portal: ya lo cubre la constraint UNIQUE
        verdict = duplicate_confidence(candidate, other)
        if verdict.is_duplicate and (best is None or verdict.confidence > best[1].confidence):
            best = (other, verdict)
    return best
