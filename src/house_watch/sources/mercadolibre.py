"""MercadoLibre Uruguay -- bloqueado por deteccion de bots.

Comprobado en vivo (2026-09-25):

  GET https://listado.mercadolibre.com.uy/inmuebles/casas/venta/montevideo/
    -> HTTP 200, pero el cuerpo es la pagina anti-bot de MercadoLibre
       ("suspicious-traffic-frontend"), sin ningun resultado.
       Agregar headers de navegador completos NO ayuda.

  GET https://api.mercadolibre.com/sites/MLU/search?category=MLU1466
    -> HTTP 403 {"message":"forbidden"}  (la API publica requiere OAuth)

Ojo con el detalle importante: devuelve **200**, no un error. Por eso la
deteccion de scraper roto mira el contenido y no el status code (seccion 24).

Para habilitarla hara falta navegador real (seccion 9) y medir el
comportamiento desde la IP del runner, que no es la misma que la de casa.
"""

from __future__ import annotations

from .base import BlockedSource


class MercadoLibreSource(BlockedSource):
    name = "mercadolibre"
    reason = "bloqueada: sirve la pagina anti-bot 'suspicious-traffic' con HTTP 200"

    #: Marcadores que identifican la pagina anti-bot en vez de resultados.
    ANTIBOT_MARKERS = ("suspicious-traffic", "Verificando", "captcha")
