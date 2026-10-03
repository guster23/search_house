"""Cliente HTTP compartido (seccion 8).

HTTP-first: httpx con timeouts, reintentos con backoff, pooling y compresion.
Solo se piden documentos; nunca imagenes, fuentes, video ni analytics, porque
un batch job que descarga assets desperdicia tiempo y cuota sin ganar nada.
"""

from __future__ import annotations

import logging
import random
import time

import httpx

from .budget import ExecutionBudget

log = logging.getLogger(__name__)

# UA de navegador real. Si un portal nos bloquea, lo registramos y seguimos.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-UY,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


class FetchError(Exception):
    """Fallo de red o respuesta no utilizable tras agotar reintentos."""


class HttpFetcher:
    def __init__(self, cfg_scraping: dict, budget: ExecutionBudget):
        self._timeout = float(cfg_scraping.get("request_timeout_seconds", 10))
        self._retries = int(cfg_scraping.get("retries", 2))
        jitter = cfg_scraping.get("jitter_ms") or [150, 450]
        self._jitter_ms = (int(jitter[0]), int(jitter[-1]))
        self._budget = budget
        self._last_request_at: dict[str, float] = {}
        self._client = httpx.Client(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=self._timeout,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
        )

    def __enter__(self) -> "HttpFetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _sleep_jitter(self, host: str) -> None:
        """Pausa corta entre requests al mismo dominio."""
        last = self._last_request_at.get(host)
        if last is not None:
            delay = random.uniform(*self._jitter_ms) / 1000.0
            elapsed = time.monotonic() - last
            if elapsed < delay:
                time.sleep(delay - elapsed)
        self._last_request_at[host] = time.monotonic()

    def get(self, url: str) -> httpx.Response:
        """GET con reintentos. Respeta el presupuesto de ejecucion."""
        host = httpx.URL(url).host or ""
        last_error: Exception | None = None

        for attempt in range(self._retries + 1):
            if not self._budget.can_afford(1.0):
                raise FetchError(f"presupuesto agotado antes de pedir {url}")

            self._sleep_jitter(host)
            try:
                response = self._client.get(
                    url, timeout=self._budget.timeout_for(self._timeout)
                )
            except httpx.HTTPError as exc:
                last_error = exc
                log.warning("GET %s fallo (intento %d): %s", url, attempt + 1, exc)
            else:
                if response.status_code < 400:
                    return response
                last_error = FetchError(f"HTTP {response.status_code} en {url}")
                # 4xx que no sea rate limit no mejora reintentando.
                if response.status_code != 429 and response.status_code < 500:
                    break
                log.warning("GET %s -> HTTP %s", url, response.status_code)

            if attempt < self._retries:
                backoff = min(2.0**attempt, self._budget.remaining())
                if backoff <= 0:
                    break
                time.sleep(backoff)

        raise FetchError(f"no se pudo obtener {url}: {last_error}")
