"""Carga y validacion de configuracion.

La config no sensible vive en config.yaml; los secretos vienen del entorno
(GitHub Actions Secrets). Los dos nunca se mezclan: un secreto en el YAML es
un bug, y este modulo no lo lee de ahi.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Configuracion invalida. Se reporta al usuario, no se traga."""


# InfoCasas prohibe en robots.txt las URLs de filtro combinado "*-y-*".
_DISALLOWED_INFOCASAS = re.compile(r"/(venta|alquiler|arriendo)[^/]*/[^/]*-y-[^/]*")


@dataclass(frozen=True)
class SearchConfig:
    name: str
    url: str


@dataclass(frozen=True)
class SourceConfig:
    name: str
    enabled: bool
    searches: tuple[SearchConfig, ...]


@dataclass(frozen=True)
class Secrets:
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    turso_database_url: str | None = None
    turso_auth_token: str | None = None

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def has_turso(self) -> bool:
        return bool(self.turso_database_url and self.turso_auth_token)

    @classmethod
    def from_env(cls) -> "Secrets":
        return cls(
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
            turso_database_url=os.environ.get("TURSO_DATABASE_URL") or None,
            turso_auth_token=os.environ.get("TURSO_AUTH_TOKEN") or None,
        )

    def __repr__(self) -> str:  # pragma: no cover - proteccion anti-leak
        """Nunca exponer valores en logs ni en tracebacks (seccion 12)."""
        return (
            f"Secrets(telegram={'set' if self.has_telegram else 'unset'}, "
            f"turso={'set' if self.has_turso else 'unset'})"
        )


@dataclass
class Config:
    sources: dict[str, SourceConfig]
    filters: dict[str, Any]
    scoring: dict[str, Any]
    alerts: dict[str, Any]
    opportunity: dict[str, Any]
    scraping: dict[str, Any]
    runtime: dict[str, Any]
    health: dict[str, Any]
    retention: dict[str, Any]
    weekly_summary: bool = False
    secrets: Secrets = field(default_factory=Secrets)

    @property
    def deadline_seconds(self) -> float:
        return float(self.runtime.get("deadline_seconds", 100))

    @property
    def min_alert_score(self) -> int:
        return int(self.alerts.get("minimum_alert_score", 70))

    @property
    def max_alerts_per_run(self) -> int:
        return int(self.alerts.get("max_alerts_per_run", 8))

    @property
    def price_drop_threshold(self) -> float:
        return float(self.alerts.get("price_drop_threshold_percent", 5))

    def enabled_sources(self) -> list[SourceConfig]:
        return [s for s in self.sources.values() if s.enabled and s.searches]


def _require_mapping(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError(f"'{where}' debe ser un mapping, no {type(raw).__name__}")
    return raw


def _parse_sources(raw: Any) -> dict[str, SourceConfig]:
    sources: dict[str, SourceConfig] = {}
    for name, body in _require_mapping(raw, "sources").items():
        body = _require_mapping(body, f"sources.{name}")
        searches = []
        for i, item in enumerate(body.get("searches") or []):
            item = _require_mapping(item, f"sources.{name}.searches[{i}]")
            url = (item.get("url") or "").strip()
            if not url:
                raise ConfigError(f"sources.{name}.searches[{i}] no tiene 'url'")
            if name == "infocasas" and _DISALLOWED_INFOCASAS.search(url):
                raise ConfigError(
                    f"sources.{name}.searches[{i}]: la URL {url!r} usa un filtro "
                    "combinado '-y-', que el robots.txt de InfoCasas prohibe. "
                    "Usa una busqueda por tipo de propiedad (ej. /venta/casas/...)."
                )
            searches.append(SearchConfig(name=item.get("name") or f"search-{i}", url=url))
        sources[name] = SourceConfig(
            name=name,
            enabled=bool(body.get("enabled", False)),
            searches=tuple(searches),
        )
    if not sources:
        raise ConfigError("No hay ninguna fuente definida en 'sources'")
    return sources


def load_config(path: str | Path, secrets: Secrets | None = None) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"No existe el archivo de configuracion: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = _require_mapping(raw, "config.yaml")

    return Config(
        sources=_parse_sources(raw.get("sources")),
        filters=_require_mapping(raw.get("filters") or {}, "filters"),
        scoring=_require_mapping(raw.get("scoring") or {}, "scoring"),
        alerts=_require_mapping(raw.get("alerts") or {}, "alerts"),
        opportunity=_require_mapping(raw.get("opportunity") or {}, "opportunity"),
        scraping=_require_mapping(raw.get("scraping") or {}, "scraping"),
        runtime=_require_mapping(raw.get("runtime") or {}, "runtime"),
        health=_require_mapping(raw.get("health") or {}, "health"),
        retention=_require_mapping(raw.get("retention") or {}, "retention"),
        weekly_summary=bool(raw.get("weekly_summary", False)),
        secrets=secrets if secrets is not None else Secrets.from_env(),
    )
