"""Presupuesto de ejecucion (seccion 30).

El workflow corta a los 2 minutos. La app se pone un deadline mas corto para
poder cerrar ordenada: dejar de pedir paginas, persistir lo hecho y salir. Un
run parcial que guardo datos vale mucho mas que un run matado a mitad.
"""

from __future__ import annotations

import time


class ExecutionBudget:
    def __init__(self, deadline_seconds: float, *, reserve_seconds: float = 10.0):
        # `reserve_seconds` se guarda para el cierre: persistir, notificar y
        # actualizar salud de fuentes. `exhausted` lo tiene en cuenta.
        self._deadline = float(deadline_seconds)
        self._reserve = float(reserve_seconds)
        self._start = time.monotonic()
        self.stopped_early = False

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start

    def remaining(self) -> float:
        """Segundos utiles restantes, sin contar la reserva de cierre."""
        return max(0.0, self._deadline - self._reserve - self.elapsed)

    @property
    def exhausted(self) -> bool:
        if self.remaining() <= 0:
            self.stopped_early = True
            return True
        return False

    def can_afford(self, estimated_seconds: float) -> bool:
        """Alcanza para una operacion que estimamos que tarda tanto."""
        if self.remaining() <= estimated_seconds:
            self.stopped_early = True
            return False
        return True

    def timeout_for(self, configured: float) -> float:
        """Timeout de request acotado por lo que queda de presupuesto."""
        return max(1.0, min(float(configured), self.remaining()))
