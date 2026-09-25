from house_watch.models import Listing
from house_watch.sources.infocasas import extract_search_payload, parse_listing


def listings_from(html: str) -> list[Listing]:
    items, _ = extract_search_payload(html)
    return [parse_listing(i) for i in items]


def test_primera_carga_son_todos_nuevos(repo, infocasas_html):
    outcome = repo.upsert_listings("infocasas", listings_from(infocasas_html))
    assert len(outcome.new) == 21
    assert outcome.unchanged == 0


def test_ver_lo_mismo_de_nuevo_no_escribe_versiones(repo, infocasas_html):
    """Volver a ver una propiedad sin cambios no debe generar escrituras."""
    repo.upsert_listings("infocasas", listings_from(infocasas_html))
    versiones_antes = repo._conn.execute(
        "SELECT COUNT(*) FROM listing_versions"
    ).fetchone()[0]

    outcome = repo.upsert_listings("infocasas", listings_from(infocasas_html))

    assert (len(outcome.new), len(outcome.changed), outcome.unchanged) == (0, 0, 21)
    versiones_despues = repo._conn.execute(
        "SELECT COUNT(*) FROM listing_versions"
    ).fetchone()[0]
    assert versiones_despues == versiones_antes


def test_una_baja_de_precio_se_detecta_como_cambio(repo, infocasas_html):
    repo.upsert_listings("infocasas", listings_from(infocasas_html))

    bajadas = listings_from(infocasas_html)
    bajadas[0].price_usd = 240000.0
    outcome = repo.upsert_listings("infocasas", bajadas)

    assert len(outcome.changed) == 1
    _, anterior = outcome.changed[0]
    assert anterior.price_usd == 269000.0
    assert repo._conn.execute("SELECT COUNT(*) FROM listing_versions").fetchone()[0] == 22


def test_has_any_listings_distingue_la_primera_corrida(repo, infocasas_html):
    assert repo.has_any_listings("infocasas") is False
    repo.upsert_listings("infocasas", listings_from(infocasas_html))
    assert repo.has_any_listings("infocasas") is True


def test_reserva_de_alerta_es_idempotente(repo):
    primera = repo.reserve_alert(
        dedupe_key="new:infocasas:123", listing_id=None,
        alert_type="new", score=80, payload="hola",
    )
    segunda = repo.reserve_alert(
        dedupe_key="new:infocasas:123", listing_id=None,
        alert_type="new", score=80, payload="hola",
    )
    assert primera is not None
    assert segunda is None  # una ejecucion duplicada no reserva de nuevo


def test_las_alertas_sin_confirmar_quedan_pendientes(repo):
    alert_id = repo.reserve_alert(
        dedupe_key="k", listing_id=None, alert_type="new", score=1, payload="texto"
    )
    assert [a.id for a in repo.pending_alerts()] == [alert_id]
    repo.mark_alert_sent(alert_id)
    assert repo.pending_alerts() == []


def test_desaparecidos_se_desactivan_recien_tras_varias_ausencias(repo, infocasas_html):
    todos = listings_from(infocasas_html)
    repo.upsert_listings("infocasas", todos)
    presentes = [l.external_id for l in todos[:20]]

    for _ in range(3):
        repo.mark_missing("infocasas", presentes, threshold=4)
    activos = repo._conn.execute(
        "SELECT COUNT(*) FROM listings WHERE active = 1"
    ).fetchone()[0]
    assert activos == 21, "no debe desactivarse antes del umbral"

    repo.mark_missing("infocasas", presentes, threshold=4)
    activos = repo._conn.execute(
        "SELECT COUNT(*) FROM listings WHERE active = 1"
    ).fetchone()[0]
    assert activos == 20


def test_volver_a_ver_una_propiedad_reinicia_el_contador(repo, infocasas_html):
    todos = listings_from(infocasas_html)
    repo.upsert_listings("infocasas", todos)
    for _ in range(3):
        repo.mark_missing("infocasas", [l.external_id for l in todos[:20]], threshold=4)

    repo.upsert_listings("infocasas", todos)  # reaparece
    fila = repo._conn.execute(
        "SELECT missed_observations FROM listings WHERE external_id = ?",
        (todos[20].external_id,),
    ).fetchone()
    assert fila[0] == 0


def test_comparables_exige_propiedades_parecidas(repo):
    base = dict(source="infocasas", canonical_url="u", neighborhood="Solymar", bedrooms=3)
    pool = [
        Listing(external_id=str(i), price_usd=200000, built_area_m2=110, land_area_m2=400, **base)
        for i in range(20)
    ]
    # Un caseron que no debe entrar en la comparacion.
    pool.append(
        Listing(external_id="outlier", price_usd=900000, built_area_m2=400,
                land_area_m2=2000, **base)
    )
    repo.upsert_listings("infocasas", pool)

    samples = repo.comparables(
        neighborhood="Solymar", bedrooms=3, built_area_m2=110, land_area_m2=400,
        built_bucket=50, land_bucket=400, exclude_id=None,
    )
    assert len(samples) == 20
    assert all(abs(s - 200000 / 110) < 1e-6 for s in samples)
