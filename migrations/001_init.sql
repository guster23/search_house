-- House Watch Uruguay -- schema inicial.
-- Compatible SQLite y Turso/libSQL (mismo DDL en dev y produccion).

CREATE TABLE IF NOT EXISTS listings (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source             TEXT    NOT NULL,
    external_id        TEXT    NOT NULL,
    canonical_url      TEXT    NOT NULL,
    title              TEXT,
    description        TEXT,
    currency           TEXT,
    price              REAL,
    price_usd          REAL,
    bedrooms           INTEGER,
    bathrooms          INTEGER,
    built_area_m2      REAL,
    land_area_m2       REAL,
    neighborhood       TEXT,
    city               TEXT,
    department         TEXT,
    address            TEXT,
    latitude           REAL,
    longitude          REAL,
    agency             TEXT,
    image_url          TEXT,
    first_seen_at      TEXT    NOT NULL,
    last_seen_at       TEXT    NOT NULL,
    published_at       TEXT,
    active             INTEGER NOT NULL DEFAULT 1,
    -- Cuantas corridas *sanas* seguidas no vimos esta propiedad (seccion 28).
    missed_observations INTEGER NOT NULL DEFAULT 0,
    fingerprint        TEXT,
    score              INTEGER,
    opportunity_score  INTEGER,
    description_hash   TEXT,
    -- Estado actual. La historia vive en listing_versions.
    data_hash          TEXT,
    features_json      TEXT,
    UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_listings_active_comparables
    ON listings (active, neighborhood, bedrooms);
CREATE INDEX IF NOT EXISTS idx_listings_fingerprint
    ON listings (fingerprint);

-- Solo se inserta cuando cambia algo relevante (seccion 11).
CREATE TABLE IF NOT EXISTS listing_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id  INTEGER NOT NULL REFERENCES listings (id) ON DELETE CASCADE,
    observed_at TEXT    NOT NULL,
    price       REAL,
    data_hash   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_versions_listing
    ON listing_versions (listing_id, observed_at);

CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER REFERENCES listings (id) ON DELETE SET NULL,
    alert_type TEXT    NOT NULL,
    score      INTEGER,
    created_at TEXT    NOT NULL,
    -- NULL = la fila se reservo pero Telegram todavia no confirmo el envio.
    sent_at    TEXT,
    payload    TEXT,
    dedupe_key TEXT    NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_alerts_unsent ON alerts (sent_at);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     TEXT    NOT NULL,
    finished_at    TEXT,
    source         TEXT    NOT NULL,
    pages_fetched  INTEGER NOT NULL DEFAULT 0,
    items_seen     INTEGER NOT NULL DEFAULT 0,
    items_new      INTEGER NOT NULL DEFAULT 0,
    items_changed  INTEGER NOT NULL DEFAULT 0,
    alerts_sent    INTEGER NOT NULL DEFAULT 0,
    status         TEXT    NOT NULL,
    error          TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_started ON scrape_runs (started_at);

CREATE TABLE IF NOT EXISTS source_health (
    source                  TEXT PRIMARY KEY,
    state                   TEXT    NOT NULL DEFAULT 'ok',  -- ok | degraded | blocked
    last_success_at         TEXT,
    consecutive_failures    INTEGER NOT NULL DEFAULT 0,
    consecutive_zero_results INTEGER NOT NULL DEFAULT 0,
    last_error              TEXT,
    last_nonzero_result_at  TEXT,
    degraded_notified_at    TEXT
);

-- Estado chico clave/valor (ej. fecha del ultimo resumen semanal).
CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
