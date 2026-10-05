"""Fallback de navegador (seccion 9).

Abstraccion deliberadamente vacia: hoy ningun scraper activo la necesita, asi
que el workflow NO instala Playwright ni Chromium y el run es de segundos.

Cuando haga falta (por ejemplo para Gallito, bloqueado por Cloudflare), implementar aca
con: Chromium headless, bloqueo de imagenes/fuentes/media/analytics, timeout
agresivo y cierre garantizado de context y browser.

No se intenta resolver CAPTCHAs. Ante un bloqueo se registra source_degraded y
se sigue con las demas fuentes.
"""

from __future__ import annotations


class BrowserUnavailable(RuntimeError):
    pass


class BrowserFetcher:
    """No se instancia salvo que un scraper declare requires_browser = True."""

<<<<<<< Updated upstream
    def __init__(self, *_args, **_kwargs):
        raise BrowserUnavailable(
            "Ningun scraper activo requiere navegador. Instalar Playwright y "
            "implementar BrowserFetcher antes de habilitar una fuente con "
            "requires_browser = True."
        )
=======
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
        self._ua = user_agent or DEFAULT_UA
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
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
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

        Usa un contexto nuevo por peticion para evitar que Cloudflare ligue cookies
        de navegacion secuencial y dispare un challenge en la segunda pagina.
        """
        if self._budget and self._budget.exhausted:
            raise BrowserFetchError("Presupuesto de ejecucion agotado")

        self._ensure_browser()

        last_resp = None
        last_error = None

        for attempt in range(1, retries + 2):
            if self._budget and self._budget.exhausted:
                raise BrowserFetchError("Presupuesto agotado durante los reintentos")

            context = None
            try:
                log.debug("Navegando %s (intento %d/%d)", url, attempt, retries + 1)
                context = self._browser.new_context(
                    user_agent=self._ua,
                    locale="es-UY",
                    viewport={"width": 1280, "height": 800},
                )
                page = context.new_page()
                resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                # Da tiempo a que el challenge de Cloudflare se resuelva solo
                page.wait_for_timeout(int(wait_seconds * 1000))

                status = resp.status if resp else 0
                title = page.title()
                html = page.content()

                is_challenge = (
                    status == 403
                    or any(t in title.lower() for t in INTERSTITIAL_TITLES)
                )

                if not is_challenge and status == 200:
                    return BrowserResponse(
                        status_code=status,
                        text=html,
                        title=title,
                        url=page.url,
                    )

                last_resp = BrowserResponse(
                    status_code=status,
                    text=html,
                    title=title,
                    url=page.url,
                )

                if is_challenge:
                    log.warning(
                        "Cloudflare challenge detectado en %s (status %d, titulo '%s'), intento %d/%d",
                        url, status, title, attempt, retries + 1,
                    )
                    if attempt <= retries:
                        time.sleep(2.0)
                        continue
                else:
                    log.warning(
                        "Respuesta HTTP %d inesperada en %s, intento %d/%d",
                        status, url, attempt, retries + 1,
                    )
                    if attempt <= retries:
                        time.sleep(1.0)
                        continue

            except Exception as exc:
                last_error = exc
                log.warning("Fallo al navegar %s (intento %d/%d): %s", url, attempt, retries + 1, exc)
                if attempt <= retries:
                    time.sleep(2.0)
            finally:
                if context:
                    try:
                        context.close()
                    except Exception:
                        pass

        if last_resp is not None:
            return last_resp
        raise BrowserFetchError(f"Fallo al cargar {url}: {last_error}")

    def close(self):
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
>>>>>>> Stashed changes
