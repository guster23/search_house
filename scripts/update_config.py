"""Actualizador de config.yaml desde GitHub Actions o CLI.

Permite modificar los parametros mas frecuentes de busqueda y filtros,
valida con load_config() y guarda los cambios de forma segura.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from house_watch.config import ConfigError, Secrets, load_config  # noqa: E402

CONFIG_PATH = ROOT / "config.yaml"


def update_config(
    max_price: int | None = None,
    min_bedrooms: int | None = None,
    min_built_area_m2: int | None = None,
    minimum_alert_score: int | None = None,
    allowed_departments: list[str] | None = None,
    allowed_neighborhoods: list[str] | None = None,
    enable_infocasas: bool | None = None,
    enable_gallito: bool | None = None,
) -> None:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"No existe {CONFIG_PATH}")

    raw: dict[str, Any] = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}

    # Actualizar fuentes
    if "sources" in raw:
        if enable_infocasas is not None and "infocasas" in raw["sources"]:
            raw["sources"]["infocasas"]["enabled"] = enable_infocasas
        if enable_gallito is not None and "gallito" in raw["sources"]:
            raw["sources"]["gallito"]["enabled"] = enable_gallito

    # Actualizar filtros
    if "filters" not in raw:
        raw["filters"] = {}

    if max_price is not None:
        raw["filters"]["max_price"] = max_price
    if min_bedrooms is not None:
        raw["filters"]["min_bedrooms"] = min_bedrooms
    if min_built_area_m2 is not None:
        raw["filters"]["min_built_area_m2"] = min_built_area_m2
    if allowed_departments is not None:
        raw["filters"]["allowed_departments"] = allowed_departments
    if allowed_neighborhoods is not None:
        raw["filters"]["allowed_neighborhoods"] = allowed_neighborhoods

    # Actualizar alertas
    if "alerts" not in raw:
        raw["alerts"] = {}
    if minimum_alert_score is not None:
        raw["alerts"]["minimum_alert_score"] = minimum_alert_score

    # Volcar a un archivo temporal para validar antes de sobrescribir
    new_yaml = yaml.dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False)
    temp_path = CONFIG_PATH.with_suffix(".tmp.yaml")
    temp_path.write_text(new_yaml, encoding="utf-8")

    try:
        load_config(temp_path, secrets=Secrets())
    except ConfigError as exc:
        if temp_path.exists():
            temp_path.unlink()
        raise ConfigError(f"La configuracion resultante no es valida: {exc}") from exc

    # Si valida correctamente, reemplazamos el config real
    temp_path.replace(CONFIG_PATH)
    print("✅ config.yaml actualizado y validado correctamente.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Actualizar config.yaml de forma segura")
    parser.add_argument("--max-price", type=int, help="Precio maximo en USD")
    parser.add_argument("--min-bedrooms", type=int, help="Dormitorios minimos")
    parser.add_argument("--min-built-area", type=int, help="M2 edificados minimos")
    parser.add_argument("--min-score", type=int, help="Score minimo para alertar (0-100)")
    parser.add_argument("--departments", type=str, help="Departamentos permitidos separados por coma")
    parser.add_argument("--neighborhoods", type=str, help="Barrios permitidos separados por coma")
    parser.add_argument("--enable-infocasas", type=str, choices=["true", "false", "keep"], default="keep")
    parser.add_argument("--enable-gallito", type=str, choices=["true", "false", "keep"], default="keep")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    depts = None
    if args.departments is not None and args.departments.strip():
        depts = [d.strip() for d in args.departments.split(",") if d.strip()]

    hoods = None
    if args.neighborhoods is not None and args.neighborhoods.strip():
        hoods = [h.strip() for h in args.neighborhoods.split(",") if h.strip()]

    ic_en = None
    if args.enable_infocasas != "keep":
        ic_en = args.enable_infocasas == "true"

    ga_en = None
    if args.enable_gallito != "keep":
        ga_en = args.enable_gallito == "true"

    update_config(
        max_price=args.max_price,
        min_bedrooms=args.min_bedrooms,
        min_built_area_m2=args.min_built_area,
        minimum_alert_score=args.min_score,
        allowed_departments=depts,
        allowed_neighborhoods=hoods,
        enable_infocasas=ic_en,
        enable_gallito=ga_en,
    )


if __name__ == "__main__":
    main()
