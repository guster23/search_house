"""Salud de fuentes y deteccion de scrapers rotos (seccion 24).

La premisa: una fuente que devuelve 0 resultados no necesariamente funciono:
puede estar sirviendo una pagina anti-bot con HTTP 200, indistinguible de un
scraper roto si uno confiara en el status code. Por eso la senal de exito es
`SourceResult.plausible`, que mira el contenido, y nunca el status code.

Se avisa una sola vez al degradarse y una sola vez al recuperarse, para que el
monitoreo no se convierta en ruido horario.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import SourceResult, utcnow


@dataclass
class HealthTransition:
    source: str
    state: str
    became_degraded: bool = False
    recovered: bool = False
    message: str | None = None

    @property
    def should_notify(self) -> bool:
        return self.became_degraded or self.recovered


def evaluate(health: dict, result: SourceResult, threshold: int) -> tuple[dict, HealthTransition]:
    """Actualiza el estado de salud y decide si corresponde avisar.

    Devuelve (nuevo estado, transicion). No toca la DB ni Telegram: el
    pipeline se encarga de persistir y notificar.
    """
    health = dict(health)
    previous_state = health.get("state", "ok")
    now = utcnow()

    if result.ok:
        health["consecutive_failures"] = 0
        health["consecutive_zero_results"] = 0
        health["last_success_at"] = now
        health["last_error"] = None
        if result.listings:
            health["last_nonzero_result_at"] = now
        health["state"] = "ok"

        if previous_state in ("degraded", "blocked"):
            health["degraded_notified_at"] = None
            return health, HealthTransition(
                source=result.source, state="ok", recovered=True,
                message=f"✅ {result.source} volvió a funcionar.",
            )
        return health, HealthTransition(source=result.source, state="ok")

    # Fallo: request roto, parser roto o respuesta no plausible.
    failures = int(health.get("consecutive_failures") or 0) + 1
    health["consecutive_failures"] = failures
    health["last_error"] = result.error
    if not result.listings:
        health["consecutive_zero_results"] = int(
            health.get("consecutive_zero_results") or 0
        ) + 1

    if failures < threshold:
        # Todavia puede ser un hipo puntual; no molestamos.
        health["state"] = previous_state if previous_state == "blocked" else "ok"
        return health, HealthTransition(source=result.source, state=health["state"])

    health["state"] = "degraded"
    if health.get("degraded_notified_at"):
        # Ya avisamos; no repetir cada hora (seccion 24).
        return health, HealthTransition(source=result.source, state="degraded")

    health["degraded_notified_at"] = now
    return health, HealthTransition(
        source=result.source, state="degraded", became_degraded=True,
        message=(
            f"⚠️ House Watch\n\n{result.source} parece haber cambiado.\n\n"
            f"{failures} ejecuciones consecutivas sin resultados.\n\n"
            "Las demás fuentes siguen funcionando."
        ),
    )
