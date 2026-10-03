"""Punto de entrada. Un proceso, una corrida, y termina.

No hay scheduler interno a proposito (seccion 4): el scheduler de produccion
es GitHub Actions. Nada de while True, sleep ni APScheduler.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace

from .config import ConfigError, Secrets, load_config
from .notify.base import NullNotifier
from .notify.telegram import TelegramNotifier
from .pipeline import Pipeline
from .repository.connection import connect
from .repository.sql import SqlListingRepository
from .sources.gallito import GallitoSource
from .sources.infocasas import InfocasasSource

log = logging.getLogger("house_watch")

SOURCES = {
    "infocasas": InfocasasSource(),
    "gallito": GallitoSource(),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="house-watch",
        description="Monitor de propiedades en portales uruguayos.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run"],
        help="accion a ejecutar (solo 'run'; puede omitirse).",
    )
    parser.add_argument("--config", default="config.yaml", help="ruta a config.yaml")
    parser.add_argument(
        "--db",
        default=None,
        help="ruta a SQLite local. Si se omite, usa Turso via TURSO_DATABASE_URL.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="no envia a Telegram: imprime los mensajes por pantalla.",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=None,
        help="limita el run a esta fuente (se puede repetir).",
    )
    parser.add_argument(
        "--migrate-only",
        action="store_true",
        help="aplica las migraciones y sale.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        cfg = load_config(args.config, secrets=Secrets.from_env())
    except ConfigError as exc:
        log.error("Configuracion invalida: %s", exc)
        return 2

    if args.source:
        wanted = set(args.source)
        unknown = wanted - set(cfg.sources)
        if unknown:
            log.error("Fuente(s) desconocida(s): %s", ", ".join(sorted(unknown)))
            return 2
        # --source fuerza esa fuente aunque este deshabilitada en config.yaml,
        # y apaga el resto.
        cfg.sources = {
            name: replace(src, enabled=name in wanted)
            for name, src in cfg.sources.items()
        }

    try:
        conn, backend = connect(db_path=args.db, secrets=cfg.secrets)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2

    repo = SqlListingRepository(conn)
    try:
        repo.migrate()

        if args.migrate_only:
            log.info("Migraciones aplicadas sobre %s. Nada mas que hacer.", backend)
            return 0

        if args.dry_run:
            notifier = NullNotifier()
            log.info("Modo dry-run: no se envia nada a Telegram.")
        elif cfg.secrets.has_telegram:
            notifier = TelegramNotifier(
                cfg.secrets.telegram_bot_token, cfg.secrets.telegram_chat_id
            )
        else:
            log.warning(
                "Sin TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID: se corre como dry-run."
            )
            notifier = NullNotifier()

        return Pipeline(cfg, repo, notifier, SOURCES).run()
    finally:
        repo.close()


if __name__ == "__main__":
    sys.exit(main())
