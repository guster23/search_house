"""Editor visual de config.yaml para House Watch Uruguay.

Levanta una UI web local con Streamlit donde podes editar todos los
parametros de busqueda, filtros, scoring y alertas sin tocar YAML a mano.
Al guardar, valida con el mismo load_config() del proyecto antes de escribir.

Uso:
    pip install streamlit           # (o: pip install -e '.[ui]')
    streamlit run scripts/config_editor.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from house_watch.config import ConfigError, Secrets, load_config  # noqa: E402

CONFIG_PATH = ROOT / "config.yaml"

# -- helpers -----------------------------------------------------------------

DEPARTMENTS = [
    "Artigas", "Canelones", "Cerro Largo", "Colonia", "Durazno",
    "Flores", "Florida", "Lavalleja", "Maldonado", "Montevideo",
    "Paysandú", "Río Negro", "Rivera", "Rocha", "Salto",
    "San José", "Soriano", "Tacuarembó", "Treinta y Tres",
]

KNOWN_NEIGHBORHOODS = [
    "Aguada", "Atahualpa", "Barrio Sur", "Brazo Oriental", "Buceo",
    "Capurro", "Carrasco", "Centro", "Cerrito", "Ciudad Vieja",
    "Colón", "Cordon", "El Pinar", "Goes", "Jacinto Vera",
    "La Blanqueada", "La Comercial", "La Teja", "Lagomar", "Larrañaga",
    "Malvín", "Malvín Norte", "Maroñas", "Neptunia", "Nuevo París",
    "Palermo", "Parque Batlle", "Parque Rodó", "Paso de la Arena",
    "Paso Molino", "Peñarol", "Piedras Blancas", "Pocitos",
    "Pocitos Nuevo", "Prado", "Punta Carretas", "Punta Gorda",
    "Reducto", "Sayago", "Solymar", "Tres Cruces", "Unión",
    "Villa Dolores", "Villa Española", "Villa Muñoz",
]

FEATURES = ["garage", "fondo", "padron_unico", "acepta_banco", "parrillero", "piscina"]


def load_raw() -> dict:
    if CONFIG_PATH.exists():
        return yaml.safe_load(CONFIG_PATH.read_text("utf-8")) or {}
    return {}


def save_config(data: dict) -> str | None:
    """Escribe config.yaml y valida. Devuelve error o None si ok."""
    CONFIG_PATH.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    try:
        load_config(CONFIG_PATH, secrets=Secrets())
        return None
    except ConfigError as exc:
        return str(exc)


# -- UI ----------------------------------------------------------------------

st.set_page_config(page_title="House Watch — Config Editor", page_icon="🏠", layout="wide")
st.title("🏠 House Watch — Editor de Configuración")
st.caption("Edita tus criterios de búsqueda. Al guardar se valida automáticamente.")

raw = load_raw()

# ---- Fuentes ---------------------------------------------------------------
st.header("🔍 Fuentes y búsquedas")

sources_raw = raw.get("sources") or {}

src_infocasas = sources_raw.get("infocasas") or {}
src_gallito = sources_raw.get("gallito") or {}

col_ic, col_ga = st.columns(2)

with col_ic:
    st.subheader("InfoCasas")
    ic_enabled = st.checkbox("Habilitada", value=src_infocasas.get("enabled", True), key="ic_en")
    ic_searches = src_infocasas.get("searches") or []
    st.markdown("**Búsquedas** (una URL por línea):")
    ic_text = st.text_area(
        "URLs InfoCasas",
        value="\n".join(s.get("url", "") for s in ic_searches),
        height=100,
        key="ic_urls",
        label_visibility="collapsed",
        help="Pega la URL de búsqueda de InfoCasas. Evita URLs con '-y-' (robots.txt las prohíbe).",
    )

with col_ga:
    st.subheader("Gallito")
    ga_enabled = st.checkbox("Habilitada", value=src_gallito.get("enabled", True), key="ga_en")
    ga_searches = src_gallito.get("searches") or []
    st.markdown("**Búsquedas** (una URL por línea):")
    ga_text = st.text_area(
        "URLs Gallito",
        value="\n".join(s.get("url", "") for s in ga_searches),
        height=100,
        key="ga_urls",
        label_visibility="collapsed",
    )

# ---- Filtros ---------------------------------------------------------------
st.header("🚫 Filtros duros")
st.caption("Si una propiedad no pasa estos filtros, no se alerta nunca.")

filters_raw = raw.get("filters") or {}

fcol1, fcol2, fcol3 = st.columns(3)
with fcol1:
    currency = st.selectbox("Moneda", ["USD", "UYU"], index=0 if filters_raw.get("currency", "USD") == "USD" else 1)
    max_price = st.number_input("Precio máximo", min_value=0, value=int(filters_raw.get("max_price", 200000)), step=5000)
with fcol2:
    min_bedrooms = st.number_input("Dormitorios mínimos", min_value=0, value=int(filters_raw.get("min_bedrooms", 2)), step=1)
    min_built = st.number_input("M² edificados mínimos", min_value=0, value=int(filters_raw.get("min_built_area_m2", 60)), step=10)
with fcol3:
    allowed_depts = st.multiselect(
        "Departamentos aceptados",
        options=DEPARTMENTS,
        default=[d for d in (filters_raw.get("allowed_departments") or []) if d in DEPARTMENTS],
        help="Vacío = todos los departamentos.",
    )

existing_neighborhoods = filters_raw.get("allowed_neighborhoods") or []
all_hood_options = sorted(set(KNOWN_NEIGHBORHOODS + existing_neighborhoods))
allowed_hoods = st.multiselect(
    "Barrios permitidos (lista blanca)",
    options=all_hood_options,
    default=[n for n in existing_neighborhoods if n in all_hood_options],
    help="Solo se alertan propiedades en estos barrios. Vacío = todos.",
)

st.markdown("**Palabras de rechazo** (una por línea):")
reject_kw = st.text_area(
    "Reject keywords",
    value="\n".join(filters_raw.get("reject_keywords") or []),
    height=100,
    label_visibility="collapsed",
)

# ---- Scoring ---------------------------------------------------------------
st.header("⭐ Scoring de preferencias")
st.caption("Determinista, sin IA. Ajustá los puntos de cada criterio.")

scoring_raw = raw.get("scoring") or {}

scol1, scol2 = st.columns(2)
with scol1:
    base_score = st.slider("Puntaje base", 0, 100, int(scoring_raw.get("base", 50)))

    st.markdown("**Rango de precio ideal**")
    ideal_raw = scoring_raw.get("ideal_price") or {}
    ip_col1, ip_col2, ip_col3 = st.columns(3)
    with ip_col1:
        ideal_min = st.number_input("Mín USD", min_value=0, value=int(ideal_raw.get("min", 0)), step=5000, key="ip_min")
    with ip_col2:
        ideal_max = st.number_input("Máx USD", min_value=0, value=int(ideal_raw.get("max", 200000)), step=5000, key="ip_max")
    with ip_col3:
        ideal_pts = st.number_input("Puntos", min_value=0, max_value=50, value=int(ideal_raw.get("points", 20)), key="ip_pts")

with scol2:
    beds_raw = scoring_raw.get("bedrooms") or {}
    beds_ideal = st.number_input("Dormitorios ideales (mín)", min_value=0, value=int(beds_raw.get("ideal_min", 2)), key="beds_ideal")
    beds_pts = st.number_input("Puntos dormitorios", min_value=0, max_value=50, value=int(beds_raw.get("points", 5)), key="beds_pts")

    land_raw = scoring_raw.get("land_area") or {}
    land_min = st.number_input("Terreno mínimo m²", min_value=0, value=int(land_raw.get("min_m2", 150)), key="land_min")
    land_pts = st.number_input("Puntos terreno", min_value=0, max_value=50, value=int(land_raw.get("points", 10)), key="land_pts")

pn_raw = scoring_raw.get("preferred_neighborhoods") or {}
pn_names = pn_raw.get("names") or []
all_pn_options = sorted(set(KNOWN_NEIGHBORHOODS + pn_names))
st.markdown("**Barrios preferidos** (dan puntos extra al score)")
pcol1, pcol2 = st.columns([3, 1])
with pcol1:
    pref_hoods = st.multiselect(
        "Barrios preferidos",
        options=all_pn_options,
        default=[n for n in pn_names if n in all_pn_options],
        label_visibility="collapsed",
    )
with pcol2:
    pref_pts = st.number_input("Puntos", min_value=0, max_value=50, value=int(pn_raw.get("points", 15)), key="pn_pts")

st.markdown("**Puntos por característica**")
feat_raw = scoring_raw.get("features") or {}
feat_cols = st.columns(len(FEATURES))
feat_values = {}
for i, feat in enumerate(FEATURES):
    with feat_cols[i]:
        feat_values[feat] = st.number_input(
            feat.replace("_", " ").title(),
            min_value=0, max_value=20,
            value=int(feat_raw.get(feat, 0)),
            key=f"feat_{feat}",
        )

# ---- Alertas ---------------------------------------------------------------
st.header("📢 Alertas")

alerts_raw = raw.get("alerts") or {}
acol1, acol2, acol3 = st.columns(3)
with acol1:
    min_score = st.number_input("Score mínimo para alertar", min_value=0, max_value=100,
                                value=int(alerts_raw.get("minimum_alert_score", 0)),
                                help="0 = alerta todo lo que pase filtros duros.")
with acol2:
    drop_pct = st.number_input("Umbral baja de precio (%)", min_value=0, max_value=50,
                               value=int(alerts_raw.get("price_drop_threshold_percent", 5)))
with acol3:
    max_alerts = st.number_input("Máx alertas por corrida", min_value=1, max_value=50,
                                 value=int(alerts_raw.get("max_alerts_per_run", 8)))

# ---- Oportunidad -----------------------------------------------------------
st.header("💡 Detección de oportunidad")
opp_raw = raw.get("opportunity") or {}
opp_enabled = st.checkbox("Habilitada", value=opp_raw.get("enabled", True), key="opp_en")

# ---- Scraping --------------------------------------------------------------
st.header("🛡️ Protección contra scraping")
scraping_raw = raw.get("scraping") or {}
scr1, scr2, scr3 = st.columns(3)
with scr1:
    max_pages = st.number_input("Máx páginas por fuente", min_value=1, max_value=20,
                                value=int(scraping_raw.get("max_search_pages_per_source", 5)))
with scr2:
    req_timeout = st.number_input("Timeout (segundos)", min_value=1, max_value=60,
                                  value=int(scraping_raw.get("request_timeout_seconds", 10)))
with scr3:
    retries = st.number_input("Reintentos", min_value=0, max_value=5,
                              value=int(scraping_raw.get("retries", 2)))

# ---- Runtime ----------------------------------------------------------------
st.header("⏱️ Runtime")
deadline = st.number_input("Deadline (segundos)", min_value=10, max_value=300,
                           value=int(raw.get("runtime", {}).get("deadline_seconds", 100)))

weekly = st.checkbox("Resumen semanal", value=raw.get("weekly_summary", True))

# -- Guardar ------------------------------------------------------------------
st.divider()

def _build_searches(text: str) -> list[dict]:
    searches = []
    for i, line in enumerate(text.strip().splitlines()):
        url = line.strip()
        if url:
            searches.append({"name": f"search-{i}", "url": url})
    return searches


if st.button("💾 Guardar configuración", type="primary", use_container_width=True):
    data = {
        "sources": {
            "infocasas": {
                "enabled": ic_enabled,
                "searches": _build_searches(ic_text),
            },
            "gallito": {
                "enabled": ga_enabled,
                "searches": _build_searches(ga_text),
            },
        },
        "filters": {
            "currency": currency,
            "max_price": max_price,
            "min_bedrooms": min_bedrooms,
            "min_built_area_m2": min_built,
            "reject_keywords": [k.strip() for k in reject_kw.splitlines() if k.strip()],
            "allowed_departments": allowed_depts,
            "allowed_neighborhoods": allowed_hoods,
        },
        "scoring": {
            "base": base_score,
            "ideal_price": {"min": ideal_min, "max": ideal_max, "points": ideal_pts},
            "preferred_neighborhoods": {"points": pref_pts, "names": pref_hoods},
            "bedrooms": {"ideal_min": beds_ideal, "points": beds_pts},
            "land_area": {"min_m2": land_min, "points": land_pts},
            "features": feat_values,
        },
        "alerts": {
            "minimum_alert_score": min_score,
            "price_drop_threshold_percent": drop_pct,
            "max_alerts_per_run": max_alerts,
        },
        "opportunity": {
            "enabled": opp_enabled,
            "min_comparables": int(opp_raw.get("min_comparables", 15)),
            "built_area_bucket_m2": int(opp_raw.get("built_area_bucket_m2", 50)),
            "land_area_bucket_m2": int(opp_raw.get("land_area_bucket_m2", 400)),
            "significant_discount_percent": int(opp_raw.get("significant_discount_percent", 10)),
        },
        "scraping": {
            "max_search_pages_per_source": max_pages,
            "max_detail_requests_per_run": int(scraping_raw.get("max_detail_requests_per_run", 20)),
            "request_timeout_seconds": req_timeout,
            "retries": retries,
            "jitter_ms": scraping_raw.get("jitter_ms", [150, 450]),
        },
        "runtime": {"deadline_seconds": deadline},
        "health": raw.get("health") or {
            "degrade_after_consecutive_failures": 3,
            "mark_inactive_after_missed_observations": 4,
        },
        "retention": raw.get("retention") or {
            "scrape_runs_days": 90,
            "listing_versions_days": 365,
        },
        "weekly_summary": weekly,
    }

    err = save_config(data)
    if err:
        st.error(f"❌ Configuración inválida: {err}")
    else:
        st.success("✅ config.yaml guardado y validado correctamente.")
        st.balloons()
