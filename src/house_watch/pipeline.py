"""Orquestacion de un run completo.

Un run es: consultar fuentes -> normalizar -> comparar con el estado -> puntuar
-> persistir -> notificar -> salir. No queda nada corriendo.

Dos invariantes que gobiernan el diseño:

1. Una fuente que falla no puede arruinar a las demas (seccion 23). Cada
   fuente esta aislada en su propio try/except y su propio scrape_run.
2. Una ejecucion duplicada no puede duplicar notificaciones (seccion 22). La
   reserva en la tabla `alerts` es lo que lo garantiza, no un chequeo en
   memoria.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .budget import ExecutionBudget
from .config import Config
from .filters import passes_early_filters, passes_hard_filters
from .health import evaluate as evaluate_health
from .http import HttpFetcher
from .models import Listing, RunStats, SourceResult, utcnow
from .notify.base import NotifyError, Notifier
from .notify.messages import (
    new_listing_message,
    price_drop_message,
    weekly_summary_message,
)
from .opportunity import evaluate as evaluate_opportunity
from .scoring import price_drop_percent, score_listing, should_alert
from .sources.base import ListingSource

log = logging.getLogger(__name__)

WEEKLY_SUMMARY_KEY = "last_weekly_summary_at"


class Pipeline:
    def __init__(self, cfg: Config, repo, notifier: Notifier, sources: dict[str, ListingSource]):
        self._cfg = cfg
        self._repo = repo
        self._notifier = notifier
        self._sources = sources
        self._alerts_sent = 0
        # Techo de envios por corrida. Lo que no entra queda reservado con
        # sent_at NULL y lo drena flush_pending en las corridas siguientes.
        self._sends_left = cfg.max_alerts_per_run
        self._deferred = 0
        self._seeded: list[tuple[str, int]] = []

    # --- envio idempotente (seccion 22) -----------------------------------

    def _deliver(
        self, *, dedupe_key: str, text: str, listing_id: int | None = None,
        alert_type: str = "new", score: int | None = None,
    ) -> bool:
        """Reserva, envia y confirma. Devuelve True si se envio ahora.

        El orden importa: primero se reserva la fila con sent_at NULL, y solo
        si la reserva prospero se manda el mensaje. Un run duplicado no logra
        reservar y por lo tanto no manda nada. Si Telegram falla despues de la
        reserva, la fila queda pendiente y el proximo run la reintenta en vez
        de perder la alerta.
        """
        alert_id = self._repo.reserve_alert(
            dedupe_key=dedupe_key, listing_id=listing_id,
            alert_type=alert_type, score=score, payload=text,
        )
        if alert_id is None:
            log.debug("alerta ya enviada, se omite: %s", dedupe_key)
            return False

        if self._sends_left <= 0:
            # Reservada pero no enviada: queda pendiente a proposito.
            self._deferred += 1
            return False

        try:
            self._notifier.send(text)
        except NotifyError as exc:
            log.error("no se pudo enviar (%s); queda pendiente: %s", dedupe_key, exc)
            return False

        self._repo.mark_alert_sent(alert_id)
        self._alerts_sent += 1
        self._sends_left -= 1
        return True

    def flush_pending(self) -> int:
        """Reintenta alertas reservadas que nunca llegaron a enviarse."""
        pending = self._repo.pending_alerts()
        if not pending:
            return 0
        log.info("Reintentando %d alerta(s) pendiente(s)", len(pending))
        sent = 0
        for alert in pending:
            if self._sends_left <= 0:
                self._deferred += 1
                continue
            if not alert.payload:
                # Sin cuerpo no se puede reenviar; se descarta la reserva.
                self._repo.discard_alert(alert.id)
                continue
            try:
                self._notifier.send(alert.payload)
            except NotifyError as exc:
                log.warning("sigue fallando el envio de %s: %s", alert.dedupe_key, exc)
                continue
            self._repo.mark_alert_sent(alert.id)
            self._sends_left -= 1
            sent += 1
        return sent

    # --- una fuente -------------------------------------------------------

    def _collect(
        self, source: ListingSource, searches, fetcher: HttpFetcher, budget: ExecutionBudget
    ) -> SourceResult:
        try:
            return source.search(searches, fetcher, budget, self._cfg)
        except Exception as exc:  # aislamiento por fuente (seccion 23)
            log.exception("la fuente %s lanzo una excepcion", source.name)
            return SourceResult(source=source.name, plausible=False, error=str(exc))

    def _enrich_details(
        self, source: ListingSource, listings: list[Listing], existing: dict,
        fetcher: HttpFetcher, budget: ExecutionBudget,
    ) -> list[Listing]:
        """Abre el detalle solo donde hace falta (secciones 6, 14 y 15).

        El filtro temprano corre ANTES: si una casa de USD 420.000 no entra en
        el presupuesto, no se gasta un request en su detalle.
        """
        max_details = int(self._cfg.scraping.get("max_detail_requests_per_run", 20))
        used = 0
        enriched: list[Listing] = []

        for listing in listings:
            known = existing.get(listing.external_id)
            if (
                used < max_details
                and passes_early_filters(listing, self._cfg)
                and source.needs_detail(listing, known)
                and budget.can_afford(2.0)
            ):
                try:
                    listing = source.fetch_detail(listing, fetcher, budget)
                    used += 1
                except Exception as exc:
                    log.warning("detalle de %s fallo: %s", listing.canonical_url, exc)
            enriched.append(listing)

        if used:
            log.info("%s: %d detalle(s) abiertos", source.name, used)
        return enriched

    def _alert_for_new(self, listing: Listing) -> None:
        if not passes_hard_filters(listing, self._cfg) or not should_alert(listing, self._cfg):
            return
        opportunity = self._maybe_opportunity(listing)
        self._deliver(
            dedupe_key=f"new:{listing.source}:{listing.external_id}",
            text=new_listing_message(listing, opportunity),
            listing_id=listing.id, alert_type="new", score=listing.score,
        )

    def _alert_for_change(self, listing: Listing, prior) -> None:
        drop = price_drop_percent(prior.price_usd, listing.price_usd)
        if drop is None or drop < self._cfg.price_drop_threshold:
            return
        if not passes_hard_filters(listing, self._cfg):
            return
        # El precio nuevo entra en la clave: una segunda baja si debe alertar.
        key = f"price-drop:{listing.source}:{listing.external_id}:{listing.price_usd:.0f}"
        self._deliver(
            dedupe_key=key,
            text=price_drop_message(listing, prior.price_usd, drop),
            listing_id=listing.id, alert_type="price-drop", score=listing.score,
        )

    def _maybe_opportunity(self, listing: Listing):
        try:
            result = evaluate_opportunity(listing, self._repo, self._cfg)
        except Exception as exc:
            log.warning("no se pudo evaluar oportunidad: %s", exc)
            return None
        if result and listing.id:
            self._repo.set_opportunity_score(listing.id, result.score)
        return result

    def run_source(
        self, source: ListingSource, searches, fetcher: HttpFetcher, budget: ExecutionBudget
    ) -> tuple[RunStats, SourceResult]:
        stats = RunStats(source=source.name, started_at=utcnow())
        result = self._collect(source, searches, fetcher, budget)

        stats.pages_fetched = result.pages_fetched
        stats.items_seen = len(result.listings)

        if not result.ok:
            stats.status = "error"
            stats.error = result.error
            stats.finished_at = utcnow()
            return stats, result

        existing = self._repo.get_existing(
            source.name, [l.external_id for l in result.listings]
        )
        listings = self._enrich_details(source, result.listings, existing, fetcher, budget)

        for listing in listings:
            listing.score, listing.score_reasons = score_listing(listing, self._cfg)

        # Primera corrida de esta fuente: todo el catalogo es "nuevo". Alertar
        # mandaria decenas de mensajes de una propiedad que lleva meses
        # publicada. Se guarda la linea de base en silencio y se alerta recien
        # sobre lo que aparezca de ahi en adelante.
        seeding = not self._repo.has_any_listings(source.name)

        outcome = self._repo.upsert_listings(source.name, listings)
        stats.items_new = len(outcome.new)
        stats.items_changed = len(outcome.changed)

        before = self._alerts_sent
        if seeding:
            self._seeded.append((source.name, len(outcome.new)))
            log.info(
                "%s: primera corrida, %d propiedades guardadas como linea de "
                "base (sin alertas)", source.name, len(outcome.new),
            )
        else:
            for listing in outcome.new:
                self._alert_for_new(listing)
            for listing, prior in outcome.changed:
                self._alert_for_change(listing, prior)
        stats.alerts_sent = self._alerts_sent - before

        # Solo se cuentan ausencias si la fuente estuvo sana y completa: si no, un fallo
        # del scraper o un corte por presupuesto desactivaria el historial (seccion 28).
        if not budget.stopped_early and result.ok and not result.error:
            threshold = int(self._cfg.health.get("mark_inactive_after_missed_observations", 4))
            deactivated = self._repo.mark_missing(
                source.name, [l.external_id for l in listings], threshold
            )
            if deactivated:
                log.info("%s: %d propiedad(es) marcadas inactivas", source.name, deactivated)
        elif budget.stopped_early:
            log.info("%s: corrida parcial (presupuesto agotado), no se actualizan ausencias", source.name)

        stats.status = "partial" if budget.stopped_early else "ok"
        stats.finished_at = utcnow()
        return stats, result

    # --- run completo -----------------------------------------------------

    def run(self) -> int:
        budget = ExecutionBudget(self._cfg.deadline_seconds)
        self.flush_pending()

        states: dict[str, str] = {}
        with HttpFetcher(self._cfg.scraping, budget) as fetcher:
            for source_cfg in self._cfg.enabled_sources():
                source = self._sources.get(source_cfg.name)
                if source is None:
                    log.warning("fuente desconocida en config: %s", source_cfg.name)
                    continue

                stats, result = self.run_source(source, source_cfg.searches, fetcher, budget)
                self._repo.record_run(stats)
                log.info(
                    "%s: %d vistos, %d nuevos, %d cambiados, %d alertas [%s]",
                    stats.source, stats.items_seen, stats.items_new,
                    stats.items_changed, stats.alerts_sent, stats.status,
                )

                health = self._repo.get_health(source_cfg.name)
                threshold = int(self._cfg.health.get("degrade_after_consecutive_failures", 3))
                health, transition = evaluate_health(health, result, threshold)
                self._repo.save_health(health)
                states[source_cfg.name] = health["state"]

                if transition.should_notify and transition.message:
                    self._deliver(
                        # Una sola notificacion por transicion de estado.
                        dedupe_key=f"health:{source_cfg.name}:{transition.state}:{utcnow()[:13]}",
                        text=transition.message,
                        alert_type="health",
                    )

        self._maybe_weekly_summary(states)
        self._repo.purge(
            runs_days=int(self._cfg.retention.get("scrape_runs_days", 90)),
            versions_days=int(self._cfg.retention.get("listing_versions_days", 365)),
        )

        if self._deferred:
            log.info(
                "%d alerta(s) quedaron reservadas y se enviaran en las proximas "
                "corridas (techo de %d por run)",
                self._deferred, self._cfg.max_alerts_per_run,
            )
        log.info("Run terminado en %.1fs, %d alerta(s) enviadas",
                 budget.elapsed, self._alerts_sent)
        return 0

    def _maybe_weekly_summary(self, states: dict[str, str]) -> None:
        if not self._cfg.weekly_summary or self._seeded:
            # En la corrida de linea de base los numeros no significan nada.
            return
        last = self._repo.get_state(WEEKLY_SUMMARY_KEY)
        now = utcnow()

        if not last:
            # Primera vez: se fija el punto de partida y se espera una semana.
            # Mandar el resumen "de los ultimos 7 dias" una hora despues de la
            # instalacion daria numeros sin sentido.
            self._repo.set_state(WEEKLY_SUMMARY_KEY, now)
            return

        try:
            if datetime.fromisoformat(last) > datetime.fromisoformat(now) - timedelta(days=7):
                return
        except ValueError:
            pass

        counts = self._repo.counts_since(7)
        if self._deliver(
            dedupe_key=f"weekly:{now[:10]}",
            text=weekly_summary_message(counts, states),
            alert_type="weekly",
        ):
            self._repo.set_state(WEEKLY_SUMMARY_KEY, now)
