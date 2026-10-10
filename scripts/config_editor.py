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

# Barrios de Montevideo (62 oficiales INE, nombres simplificados)
_BARRIOS_MVD = [
    "Aguada", "Aires Puros", "Atahualpa",
    "Bañados de Carrasco", "Barrio Sur", "Belvedere", "Brazo Oriental", "Buceo",
    "Capurro", "Carrasco", "Carrasco Norte", "Casabó", "Casavalle", "Centro",
    "Cerrito", "Cerro", "Ciudad Vieja", "Colón", "Conciliación", "Cordón",
    "Flor de Maroñas",
    "Goes",
    "Ituzaingó",
    "Jacinto Vera", "Jardines del Hipódromo",
    "La Blanqueada", "La Comercial", "La Figurita", "La Paloma", "La Teja",
    "Larrañaga", "Las Acacias", "Las Canteras", "Lezica", "Melilla",
    "Malvín", "Malvín Norte", "Manga", "Maroñas", "Mercado Modelo",
    "Nuevo París",
    "Palermo", "Parque Batlle", "Parque Rodó", "Paso de la Arena",
    "Paso de las Duranas", "Peñarol", "Piedras Blancas", "Pocitos",
    "Pocitos Nuevo", "Prado", "Punta Carretas", "Punta de Rieles", "Punta Gorda",
    "Reducto",
    "Santiago Vázquez", "Sayago",
    "Tres Cruces", "Tres Ombúes",
    "Unión",
    "Villa Dolores", "Villa Española", "Villa García", "Villa Muñoz",
]

# Localidades de Canelones (Ciudad de la Costa + Costa de Oro + interior)
_LOCALIDADES_CAN = [
    "Atlántida",
    "Barra de Carrasco", "Barros Blancos",
    "Canelones", "Ciudad de la Costa", "Colinas de Solymar", "Colonia Nicolich",
    "Costa Azul",
    "El Bosque", "El Pinar", "Empalme Olmos",
    "La Floresta", "La Paz", "Lagomar", "Las Piedras", "Las Toscas",
    "Lomas de Solymar",
    "Marindia", "Médanos de Solymar",
    "Neptunia",
    "Pando", "Parque Carrasco", "Parque del Plata", "Paso Carrasco",
    "Pinamar", "Progreso",
    "Salinas", "San José de Carrasco", "Santa Lucía", "Shangrilá", "Solymar",
    "Toledo",
]

KNOWN_NEIGHBORHOODS = sorted(_BARRIOS_MVD + _LOCALIDADES_CAN)

FEATURES = ["garage", "fondo", "padron_unico", "acepta_banco", "parrillero", "piscina"]

# Mapeo legible de importancia → puntos
_IMPORTANCE_LEVELS = {"Nada": 0, "Poco": 5, "Medio": 10, "Alto": 15, "Clave": 20}
_IMPORTANCE_OPTIONS = list(_IMPORTANCE_LEVELS.keys())

# Mapeo más chico para features
_FEAT_LEVELS = {"Poco": 2, "Medio": 5, "Alto": 10}
_FEAT_OPTIONS = list(_FEAT_LEVELS.keys())


def _closest_importance(value: int, levels: dict[str, int] | None = None) -> str:
    """Dado un valor numérico, devuelve el nivel de importancia más cercano."""
    lvl = levels or _IMPORTANCE_LEVELS
    return min(lvl, key=lambda k: abs(lvl[k] - value))


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
st.header("⭐ Puntaje de preferencias")
st.markdown(
    "Cada propiedad arranca con un **puntaje base** y suma puntos si cumple tus preferencias. "
    "Cuanto más importancia le das a un criterio, más peso tiene. "
    "Si el puntaje final supera el **score mínimo** de alertas, te notificamos por Telegram."
)

scoring_raw = raw.get("scoring") or {}

base_score = st.slider("Puntaje base (todas las propiedades arrancan con esto)", 0, 100, int(scoring_raw.get("base", 50)))

st.divider()

# -- Precio ideal
st.subheader("💰 Precio ideal")
st.caption("Si el precio está dentro de este rango, suma puntos.")
ideal_raw = scoring_raw.get("ideal_price") or {}
ip_col1, ip_col2, ip_col3 = st.columns(3)
with ip_col1:
    ideal_min = st.number_input("Mínimo USD", min_value=0, value=int(ideal_raw.get("min", 0)), step=5000, key="ip_min")
with ip_col2:
    ideal_max = st.number_input("Máximo USD", min_value=0, value=int(ideal_raw.get("max", 200000)), step=5000, key="ip_max")
with ip_col3:
    ideal_pts = _IMPORTANCE_LEVELS[
        st.select_slider("Importancia", options=_IMPORTANCE_OPTIONS,
                         value=_closest_importance(int(ideal_raw.get("points", 20))),
                         key="ip_imp")
    ]

st.divider()

# -- Dormitorios y terreno
st.subheader("🏗️ Espacio")
sp_col1, sp_col2 = st.columns(2)
with sp_col1:
    beds_raw = scoring_raw.get("bedrooms") or {}
    beds_ideal = st.number_input("Dormitorios ideales (mínimo)", min_value=0, value=int(beds_raw.get("ideal_min", 2)), key="beds_ideal")
    beds_pts = _IMPORTANCE_LEVELS[
        st.select_slider("Importancia dormitorios", options=_IMPORTANCE_OPTIONS,
                         value=_closest_importance(int(beds_raw.get("points", 5))),
                         key="beds_imp")
    ]

with sp_col2:
    land_raw = scoring_raw.get("land_area") or {}
    land_min = st.number_input("Terreno mínimo m²", min_value=0, value=int(land_raw.get("min_m2", 150)), key="land_min")
    land_pts = _IMPORTANCE_LEVELS[
        st.select_slider("Importancia terreno", options=_IMPORTANCE_OPTIONS,
                         value=_closest_importance(int(land_raw.get("points", 10))),
                         key="land_imp")
    ]

st.divider()

# -- Barrios preferidos
st.subheader("📍 Barrios preferidos")
st.caption("Estar en uno de estos barrios suma puntos extra.")
pn_raw = scoring_raw.get("preferred_neighborhoods") or {}
pn_names = pn_raw.get("names") or []
all_pn_options = sorted(set(KNOWN_NEIGHBORHOODS + pn_names))
pcol1, pcol2 = st.columns([3, 1])
with pcol1:
    pref_hoods = st.multiselect(
        "Barrios preferidos",
        options=all_pn_options,
        default=[n for n in pn_names if n in all_pn_options],
        label_visibility="collapsed",
    )
with pcol2:
    pref_pts = _IMPORTANCE_LEVELS[
        st.select_slider("Importancia zona", options=_IMPORTANCE_OPTIONS,
                         value=_closest_importance(int(pn_raw.get("points", 15))),
                         key="pn_imp")
    ]

st.divider()

# -- Features
st.subheader("🏡 Características deseadas")
st.caption("Marcá las que te importan y qué tan relevantes son.")
feat_raw = scoring_raw.get("features") or {}
feat_values: dict[str, int] = {}

_FEAT_LABELS = {
    "garage": "🚗 Garage",
    "fondo": "🌳 Fondo",
    "padron_unico": "📋 Padrón único",
    "acepta_banco": "🏦 Acepta banco",
    "parrillero": "🔥 Parrillero",
    "piscina": "🏊 Piscina",
}

# Mostrar en filas de 3
for row_start in range(0, len(FEATURES), 3):
    row_feats = FEATURES[row_start:row_start + 3]
    cols = st.columns(len(row_feats))
    for col, feat in zip(cols, row_feats):
        with col:
            current_val = int(feat_raw.get(feat, 0))
            enabled = st.checkbox(
                _FEAT_LABELS.get(feat, feat.replace("_", " ").title()),
                value=current_val > 0,
                key=f"feat_chk_{feat}",
            )
            if enabled:
                level = st.select_slider(
                    "Importancia",
                    options=_FEAT_OPTIONS,
                    value=_closest_importance(current_val, _FEAT_LEVELS) if current_val > 0 else "Medio",
                    key=f"feat_imp_{feat}",
                    label_visibility="collapsed",
                )
                feat_values[feat] = _FEAT_LEVELS[level]
            else:
                feat_values[feat] = 0

# -- Preview del puntaje
st.divider()
max_possible = base_score + ideal_pts + beds_pts + land_pts + pref_pts + sum(feat_values.values())
feat_total = sum(feat_values.values())

st.markdown("##### 📊 Resumen del puntaje")
preview_parts = [f"Base: **{base_score}**"]
if ideal_pts:
    preview_parts.append(f"Precio ideal: **+{ideal_pts}**")
if beds_pts:
    preview_parts.append(f"Dormitorios: **+{beds_pts}**")
if land_pts:
    preview_parts.append(f"Terreno: **+{land_pts}**")
if pref_pts:
    preview_parts.append(f"Zona preferida: **+{pref_pts}**")
if feat_total:
    preview_parts.append(f"Características: **+{feat_total}**")

preview_parts.append(f"**Máximo posible: {min(100, max_possible)} pts**")
st.info(" → ".join(preview_parts))

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


if st.button("💾 Guardar y Aplicar Configuración", type="primary", use_container_width=True):
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
        # Secciones técnicas: preservar del YAML original
        "opportunity": raw.get("opportunity") or {
            "enabled": True,
            "min_comparables": 15,
            "built_area_bucket_m2": 50,
            "land_area_bucket_m2": 400,
            "significant_discount_percent": 10,
        },
        "scraping": raw.get("scraping") or {
            "max_search_pages_per_source": 5,
            "max_detail_requests_per_run": 20,
            "request_timeout_seconds": 10,
            "retries": 2,
            "jitter_ms": [150, 450],
        },
        "runtime": raw.get("runtime") or {"deadline_seconds": 100},
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
        # Señal para el workflow de GitHub Actions si está corriendo en CI
        signal_file = ROOT / ".config_saved"
        signal_file.write_text("ok", encoding="utf-8")
        st.success("✅ config.yaml guardado y validado correctamente.")
        st.info("🚀 Si estás usando GitHub Actions, el runner detectará el cambio y hará commit a GitHub automáticamente. Ya podés cerrar esta pestaña.")
        st.balloons()
