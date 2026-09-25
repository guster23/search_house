"""Interfaz de notificacion (seccion 38)."""

from __future__ import annotations

from typing import Protocol


class NotifyError(Exception):
    """Fallo al entregar el mensaje. Se reintenta en el proximo run."""


class Notifier(Protocol):
    def send(self, text: str) -> None:
        """Entrega el mensaje. Lanza NotifyError si no se pudo."""


class NullNotifier:
    """No envia nada: se usa en --dry-run y en los tests."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)
        print("\n----- TELEGRAM (dry-run) -----")
        print(text)
        print("------------------------------")
