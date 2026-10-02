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
from .ml_auth import MlAuthError, interactive_auth
from .notify.base import NullNotifier
from .notify.telegram import TelegramNotifier
from .pipeline import Pipeline
from .repository.connection import connect
from .repository.sql import SqlListingRepository
from .sources.gallito import GallitoSource
from .sources.infocasas import InfocasasSource
from .sources.mercadolibre import MercadoLibreSource

log = logging.getLogger("house_watch")

SOURCES = {
    "infocasas": InfocasasSource(),
    "mercadolibre": MercadoLibreSource(),
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
        choices=["run", "ml-auth"],
        help="'run' (default) o 'ml-auth' (autorizacion unica de MercadoLibre).",
    )
    parser.add_argument(
        "--redirect-uri",
        default="http://localhost/",
        help=(
            "redirect_uri registrada en el DevCenter de ML (para ml-auth). "
            "Debe coincidir EXACTAMENTE. Si el DevCenter rechaza localhost, "
            "registrá una URL https cualquiera válida y pasala acá."
        ),
    )
    parser.add_argument(
        "--no-pkce",
        action="store_true",
        help=(
            "no usa PKCE en la autorización (para ml-auth). Probar si ML "
            "muestra 'la aplicación no puede conectarse a tu cuenta' con el "
            "grant habilitado y la redirect_uri exacta."
        ),
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

        if args.command == "ml-auth":
            return _ml_auth(cfg, repo, args.redirect_uri, use_pkce=not args.no_pkce)

        if args.migrate_only:
            log.info("Migraciones aplicadas sobre %s. Nada mas que hacer.", backend)
            return 0

        # La fuente de MercadoLibre persiste/rota sus tokens en app_state; el
        # repo se lo inyecta aca porque la interfaz ListingSource no lo pasa.
        if isinstance(SOURCES["mercadolibre"], MercadoLibreSource):
            SOURCES["mercadolibre"].set_store(repo)

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


def _ml_auth(cfg, repo, redirect_uri: str, use_pkce: bool = True) -> int:
    """Autorizacion unica de MercadoLibre: guarda refresh_token en la base."""
    if not cfg.secrets.has_mercadolibre:
        log.error(
            "Faltan ML_CLIENT_ID / ML_CLIENT_SECRET en el entorno; exportalos "
            "y volve a correr `house-watch ml-auth`."
        )
        return 2
    try:
        interactive_auth(
            cfg.secrets.ml_client_id,  # type: ignore[arg-type]
            cfg.secrets.ml_client_secret,  # type: ignore[arg-type]
            redirect_uri,
            store=repo,
            use_pkce=use_pkce,
        )
        return 0
    except MlAuthError as exc:
        log.error("Autorizacion MercadoLibre fallida: %s", exc)
        return 1
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
