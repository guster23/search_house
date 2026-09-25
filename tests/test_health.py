from house_watch.health import evaluate
from house_watch.models import Listing, SourceResult

OK = SourceResult(source="infocasas", listings=[Listing("infocasas", "1", "u")], plausible=True)
ROTO = SourceResult(source="infocasas", listings=[], plausible=False, error="sin resultados")


def fresh() -> dict:
    return {
        "source": "infocasas", "state": "ok", "last_success_at": None,
        "consecutive_failures": 0, "consecutive_zero_results": 0,
        "last_error": None, "last_nonzero_result_at": None,
        "degraded_notified_at": None,
    }


def test_un_fallo_aislado_no_alerta():
    health, transition = evaluate(fresh(), ROTO, threshold=3)
    assert health["consecutive_failures"] == 1
    assert not transition.should_notify


def test_degrada_y_avisa_una_sola_vez_a_las_tres():
    health = fresh()
    notificaciones = 0
    for _ in range(6):
        health, transition = evaluate(health, ROTO, threshold=3)
        notificaciones += int(transition.should_notify)
    assert health["state"] == "degraded"
    # Seis corridas rotas, un solo Telegram: no se repite cada hora.
    assert notificaciones == 1


def test_avisa_la_recuperacion():
    health = fresh()
    for _ in range(3):
        health, _ = evaluate(health, ROTO, threshold=3)
    health, transition = evaluate(health, OK, threshold=3)
    assert health["state"] == "ok"
    assert transition.recovered
    assert "volvió a funcionar" in transition.message
    assert health["consecutive_failures"] == 0


def test_puede_volver_a_avisar_tras_recuperarse():
    health = fresh()
    for _ in range(3):
        health, _ = evaluate(health, ROTO, threshold=3)
    health, _ = evaluate(health, OK, threshold=3)
    notificaciones = 0
    for _ in range(3):
        health, transition = evaluate(health, ROTO, threshold=3)
        notificaciones += int(transition.became_degraded)
    assert notificaciones == 1
