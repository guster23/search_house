"""Fallback de navegador (seccion 9).

Abstraccion deliberadamente vacia: hoy ningun scraper activo la necesita, asi
que el workflow NO instala Playwright ni Chromium y el run es de segundos.

Cuando haga falta (por ejemplo para Gallito, bloqueado por Cloudflare), implementar aca
con: Chromium headless, bloqueo de imagenes/fuentes/media/analytics, timeout
agresivo y cierre garantizado de context y browser.

Ante un bloqueo se registra source_degraded y se sigue con las demas fuentes.
"""

from __future__ import annotations


class BrowserUnavailable(RuntimeError):
    pass


class BrowserFetcher:
    """No se instancia salvo que un scraper declare requires_browser = True."""

    def __init__(self, *_args, **_kwargs):
        raise BrowserUnavailable(
            "Ningun scraper activo requiere navegador. Instalar Playwright y "
            "implementar BrowserFetcher antes de habilitar una fuente con "
            "requires_browser = True."
        )
