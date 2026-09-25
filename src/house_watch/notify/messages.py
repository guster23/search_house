"""Formato de los mensajes de Telegram (secciones 20, 21, 26)."""

from __future__ import annotations

from ..models import Listing
from ..opportunity import OpportunityResult


def _money(amount: float | None, currency: str | None = "USD") -> str:
    if amount is None:
        return "precio no publicado"
    label = "USD" if (currency or "").upper() in ("USD", "U$S", "US$") else (currency or "")
    return f"{label} {amount:,.0f}".replace(",", ".")


def _location(listing: Listing) -> str:
    parts = [p for p in (listing.neighborhood, listing.department) if p]
    return ", ".join(dict.fromkeys(parts)) or "ubicación no informada"


def new_listing_message(
    listing: Listing, opportunity: OpportunityResult | None = None
) -> str:
    """Alerta de propiedad nueva interesante (seccion 20)."""
    lines = [
        "🏠 Nueva propiedad interesante",
        "",
        f"📍 {_location(listing)}",
        f"💰 {_money(listing.price_usd, listing.currency)}",
    ]
    if listing.bedrooms:
        lines.append(f"🛏 {listing.bedrooms} dormitorios")
    if listing.bathrooms:
        lines.append(f"🚿 {listing.bathrooms} baños")
    if listing.built_area_m2:
        lines.append(f"📐 {listing.built_area_m2:.0f} m²")
    if listing.land_area_m2:
        lines.append(f"🌳 {listing.land_area_m2:.0f} m² terreno")

    lines.append("")
    lines.append(f"⭐ Preferencias: {listing.score}/100")
    if opportunity:
        lines.append(f"📉 Oportunidad: {opportunity.score}/100")

    reasons = list(listing.score_reasons)
    if opportunity and opportunity.is_below_market:
        reasons.append(opportunity.summary())
    if reasons:
        lines.append("")
        lines.extend(f"+ {r}" for r in reasons)

    if listing.agency:
        lines.extend(["", listing.agency])
    lines.extend(["", listing.canonical_url])
    return "\n".join(lines)


def price_drop_message(listing: Listing, old_price: float, drop_percent: float) -> str:
    """Alerta de baja de precio (seccion 21)."""
    return "\n".join(
        [
            "📉 Bajó de precio",
            "",
            f"📍 {_location(listing)}",
            f"💰 {_money(old_price, listing.currency)} → "
            f"{_money(listing.price_usd, listing.currency)}",
            f"({drop_percent:.1f}% menos)",
            "",
            f"⭐ Preferencias: {listing.score}/100",
            "",
            listing.canonical_url,
        ]
    )


def weekly_summary_message(counts: dict, health: dict[str, str]) -> str:
    """Resumen semanal opcional (seccion 26)."""
    icons = {"ok": "✅", "degraded": "⚠️", "blocked": "🚫"}
    lines = [
        "🏠 House Watch",
        "",
        "Últimos 7 días:",
        "",
        f"{counts['seen']:,} listings revisados".replace(",", "."),
        f"{counts['new']} nuevos",
        f"{counts['interesting']} interesantes",
        f"{counts['alerts']} alertas enviadas",
        "",
    ]
    lines.extend(
        f"{source} {icons.get(state, '❔')}" for source, state in sorted(health.items())
    )
    return "\n".join(lines)
