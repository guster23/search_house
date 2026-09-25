"""Notificador de Telegram.

Deliberadamente simple: un POST a sendMessage. El token nunca se loguea ni
aparece en excepciones (seccion 12), por eso los errores reportan solo el
codigo de estado y la descripcion que devuelve la API.
"""

from __future__ import annotations

import logging

import httpx

from .base import NotifyError

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 10.0):
        self._token = bot_token
        self._chat_id = chat_id
        self._timeout = timeout

    def send(self, text: str) -> None:
        url = f"{API_BASE}/bot{self._token}/sendMessage"
        try:
            response = httpx.post(
                url,
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    # Sin parse_mode: los titulos de los avisos traen
                    # caracteres que romperian Markdown y harian fallar el envio.
                    "disable_web_page_preview": False,
                },
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise NotifyError(f"no se pudo contactar a Telegram: {exc}") from exc

        if response.status_code != 200:
            # Nunca incluir la URL: contiene el token.
            detail = ""
            try:
                detail = response.json().get("description", "")
            except Exception:  # pragma: no cover
                pass
            raise NotifyError(f"Telegram respondio HTTP {response.status_code}: {detail}")
