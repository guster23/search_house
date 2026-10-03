"""Gallito -- bloqueado por Cloudflare.

Comprobado en vivo (2026-09-25):

  GET https://www.gallito.com.uy/inmuebles/casas/venta
    -> HTTP 403
       server: cloudflare
       cf-mitigated: challenge
       cuerpo: "Just a moment..."

Es un managed challenge de Cloudflare. Habilitarla requeriria navegador real
y una IP que el challenge acepte, y aun asi puede no pasar.
"""

from __future__ import annotations

from .base import BlockedSource


class GallitoSource(BlockedSource):
    name = "gallito"
    reason = "bloqueada: Cloudflare managed challenge (cf-mitigated: challenge)"
