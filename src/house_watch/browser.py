"""Manejo de navegador para portales con Cloudflare / JavaScript (seccion 9).

Permite ejecutar Chromium (headed bajo Xvfb o headless) con Playwright,
gestionando reintentos ante intersticiales de Cloudflare, reutilizando
cookies/clearance entre paginas y cerrando de forma garantizada todos
los recursos (contexto, navegador, proceso).
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_LINUX_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

INTERSTITIAL_TITLES = ("just a moment", "un momento", "attention required")


class BrowserUnavailable(RuntimeError):
    """Playwright o Chromium no estan disponibles."""


class BrowserFetchError(Exception):
    """Error al cargar una pagina con el navegador."""


@dataclass
class BrowserResponse:
    status_code: int
    text: str
    title: str = ""
    url: str = ""


class BrowserFetcher:
    """Ejecutor de navegacion para scrapers que requieren browser real."""

    def __init__(
        self,
        scraping_cfg: dict | None = None,
        budget=None,
        headless: bool | None = None,
        user_agent: str | None = None,
    ):
        self._cfg = scraping_cfg or {}
        self._budget = budget
        self._headless = headless
        if user_agent:
            self._ua = user_agent
        elif sys.platform.startswith("linux"):
            self._ua = DEFAULT_LINUX_UA
        else:
            self._ua = DEFAULT_UA
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _determine_headless(self) -> bool:
        if self._headless is not None:
            return self._headless
        env = os.environ.get("HOUSE_WATCH_HEADLESS", "").lower()
        if env in ("1", "true", "yes"):
            return True
        if env in ("0", "false", "no"):
            return False
        # En Linux sin DISPLAY no se puede abrir headed salvo bajo Xvfb.
        if sys.platform != "darwin" and not os.environ.get("DISPLAY"):
            return True
        # En el runner bajo Xvfb o en macOS, headless=False es el caso mas favorable.
        return False

    def _ensure_browser(self):
        if self._browser is not None:
            return

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserUnavailable(
                "Playwright no esta instalado. Instalar con: "
                "pip install 'house-watch[browser]' && python -m playwright install --with-deps chromium"
            ) from exc

        headless = self._determine_headless()
        log.info("Iniciando Chromium (headless=%s)", headless)

        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            self._context = self._browser.new_context(
                user_agent=self._ua,
                locale="es-UY",
                viewport={"width": 1280, "height": 800},
            )
            self._page = self._context.new_page()
        except Exception as exc:
            self.close()
            raise BrowserUnavailable(f"No se pudo iniciar Chromium: {exc}") from exc

    def get(
        self,
        url: str,
        wait_seconds: float = 6.0,
        retries: int = 2,
        timeout_ms: int = 30000,
    ) -> BrowserResponse:
        """Carga una URL con el navegador, reintentando si salta challenge de Cloudflare.

        Mantiene el contexto de navegacion para que las cookies de clearance
        (cf_clearance) persistan a lo largo de las siguientes paginas.
        """
        if self._budget and self._budget.exhausted:
            raise BrowserFetchError("Presupuesto de ejecucion agotado")

        self._ensure_browser()

        last_resp = None
        last_error = None

        for attempt in range(1, retries + 2):
            if self._budget and self._budget.exhausted:
                raise BrowserFetchError("Presupuesto agotado durante los reintentos")

            try:
                log.debug("Navegando %s (intento %d/%d)", url, attempt, retries + 1)
                if self._page is None or self._page.is_closed():
                    if self._context is None:
                        self._context = self._browser.new_context(
                            user_agent=self._ua,
                            locale="es-UY",
                            viewport={"width": 1280, "height": 800},
                        )
                    self._page = self._context.new_page()

                resp = self._page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                # Espera adaptativa para dar tiempo a que Cloudflare resuelva el challenge
                max_wait = max(wait_seconds, 12.0)
                deadline = time.monotonic() + max_wait
                while time.monotonic() < deadline:
                    title = self._page.title()
                    if not any(t in title.lower() for t in INTERSTITIAL_TITLES):
                        break

                    # Si Cloudflare Turnstile muestra un checkbox interactivo, intentar cliquearlo
                    try:
                        for frame in self._page.frames:
                            cb = frame.locator("input[type='checkbox'], .ctp-checkbox-label, #challenge-stage input")
                            if cb.is_visible():
                                cb.click()
                                break
                    except Exception:
                        pass

                    self._page.wait_for_timeout(500)

                status = resp.status if resp else 0
                title = self._page.title()
                html = self._page.content()

                is_challenge = any(t in title.lower() for t in INTERSTITIAL_TITLES)

                if not is_challenge:
                    # El challenge se resolvio o no hubo challenge. Si la respuesta inicial
                    # fue 403 por el interstitial pero el titulo cambio a la pagina real,
                    # el estado efectivo es 200.
                    final_status = 200 if status == 403 else status
                    return BrowserResponse(
                        status_code=final_status,
                        text=html,
                        title=title,
                        url=self._page.url,
                    )

                last_resp = BrowserResponse(
                    status_code=403,
                    text=html,
                    title=title,
                    url=self._page.url,
                )

                log.warning(
                    "Cloudflare challenge detectado en %s (status %d, titulo '%s'), intento %d/%d",
                    url, status, title, attempt, retries + 1,
                )
                if attempt <= retries:
                    time.sleep(2.0)
                    continue

            except Exception as exc:
                last_error = exc
                log.warning("Fallo al navegar %s (intento %d/%d): %s", url, attempt, retries + 1, exc)
                if attempt <= retries:
                    time.sleep(2.0)

        if last_resp is not None:
            return last_resp
        raise BrowserFetchError(f"Fallo al cargar {url}: {last_error}")

    def close(self):
        if self._page:
            try:
                self._page.close()
            except Exception:
                pass
            self._page = None
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def __enter__(self) -> BrowserFetcher:
        self._ensure_browser()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
