"""Tests de las invariantes del run completo.

Las dos que importan de verdad: una ejecucion duplicada no duplica avisos, y
una fuente caida no arrastra a las demas.
"""

from dataclasses import replace

import pytest

from house_watch.config import SearchConfig, SourceConfig
from house_watch.models import Listing, SourceResult
from house_watch.notify.base import NotifyError
from house_watch.pipeline import Pipeline
from house_watch.sources.base import BaseSource


class FakeSource(BaseSource):
    """Fuente controlada: devuelve lo que le digamos, sin tocar la red."""

    def __init__(self, name: str, listings: list[Listing], *, plausible=True, error=None,
                 raises: Exception | None = None):
        self.name = name
        self.requires_browser = False
        self._listings = listings
        self._plausible = plausible
        self._error = error
        self._raises = raises
        self.calls = 0

    def search(self, searches, fetcher, budget, cfg) -> SourceResult:
        self.calls += 1
        if self._raises:
            raise self._raises
        return SourceResult(
            source=self.name, listings=list(self._listings),
            pages_fetched=1, plausible=self._plausible, error=self._error,
        )

    def needs_detail(self, listing, known):
        return False


class RecordingNotifier:
    def __init__(self, fail_times: int = 0):
        self.sent: list[str] = []
        self._fail_times = fail_times

    def send(self, text: str) -> None:
        if self._fail_times > 0:
            self._fail_times -= 1
            raise NotifyError("Telegram caido")
        self.sent.append(text)


def good_listing(external_id: str, source="fake", **kwargs) -> Listing:
    base = dict(
        source=source, external_id=external_id,
        canonical_url=f"https://x/{external_id}",
        title="Casa linda", description="Casa con garage y parrillero, apto banco",
        price_usd=198000, currency="U$S", bedrooms=3, bathrooms=2,
        built_area_m2=115, land_area_m2=420, neighborhood="Solymar",
        department="Canelones",
    )
    base.update(kwargs)
    return Listing(**base)


@pytest.fixture
def fake_cfg(cfg):
    cfg.sources = {
        "fake": SourceConfig(
            name="fake", enabled=True,
            searches=(SearchConfig(name="s", url="https://example.invalid/s"),),
        )
    }
    return cfg


def run_pipeline(cfg, repo, source, notifier) -> Pipeline:
    pipeline = Pipeline(cfg, repo, notifier, {source.name: source})
    pipeline.run()
    return pipeline


def test_la_primera_corrida_no_alerta_nada(fake_cfg, repo):
    """Cold start: el catalogo entero es 'nuevo' pero lleva meses publicado."""
    source = FakeSource("fake", [good_listing(str(i)) for i in range(10)])
    notifier = RecordingNotifier()

    run_pipeline(fake_cfg, repo, source, notifier)

    assert notifier.sent == []
    assert repo._conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 10


def test_alerta_solo_lo_que_aparece_despues_de_la_linea_de_base(fake_cfg, repo):
    base = [good_listing(str(i)) for i in range(10)]
    notifier = RecordingNotifier()

    run_pipeline(fake_cfg, repo, FakeSource("fake", base), notifier)
    assert notifier.sent == []

    nueva = good_listing("999")
    run_pipeline(fake_cfg, repo, FakeSource("fake", base + [nueva]), notifier)

    assert len(notifier.sent) == 1
    assert "Nueva propiedad interesante" in notifier.sent[0]


def test_una_ejecucion_duplicada_no_manda_dos_telegram(fake_cfg, repo):
    """La garantia de la seccion 22, probada de punta a punta."""
    base = [good_listing(str(i)) for i in range(5)]
    notifier = RecordingNotifier()
    run_pipeline(fake_cfg, repo, FakeSource("fake", base), notifier)

    con_nueva = base + [good_listing("nueva")]
    run_pipeline(fake_cfg, repo, FakeSource("fake", con_nueva), notifier)
    assert len(notifier.sent) == 1

    # GitHub dispara el mismo run otra vez.
    run_pipeline(fake_cfg, repo, FakeSource("fake", con_nueva), notifier)
    assert len(notifier.sent) == 1, "una propiedad vieja no vuelve a alertarse"


def test_si_telegram_falla_la_alerta_no_se_pierde(fake_cfg, repo):
    base = [good_listing(str(i)) for i in range(3)]
    run_pipeline(fake_cfg, repo, FakeSource("fake", base), RecordingNotifier())

    con_nueva = base + [good_listing("nueva")]
    caido = RecordingNotifier(fail_times=1)
    run_pipeline(fake_cfg, repo, FakeSource("fake", con_nueva), caido)
    assert caido.sent == []
    assert len(repo.pending_alerts()) == 1

    # Al run siguiente Telegram anda y la alerta se entrega, una sola vez.
    sano = RecordingNotifier()
    run_pipeline(fake_cfg, repo, FakeSource("fake", con_nueva), sano)
    assert len(sano.sent) == 1
    assert repo.pending_alerts() == []


def test_baja_de_precio_alerta_una_vez_por_precio(fake_cfg, repo):
    base = [good_listing("casa", price_usd=230000)]
    run_pipeline(fake_cfg, repo, FakeSource("fake", base), RecordingNotifier())

    notifier = RecordingNotifier()
    bajada = [good_listing("casa", price_usd=215000)]  # -6.52%, supera el 5%
    run_pipeline(fake_cfg, repo, FakeSource("fake", bajada), notifier)
    assert len(notifier.sent) == 1
    assert "Bajó de precio" in notifier.sent[0]

    run_pipeline(fake_cfg, repo, FakeSource("fake", bajada), notifier)
    assert len(notifier.sent) == 1, "el mismo precio no vuelve a alertar"


def test_baja_menor_al_umbral_no_alerta(fake_cfg, repo):
    base = [good_listing("casa", price_usd=200000)]
    run_pipeline(fake_cfg, repo, FakeSource("fake", base), RecordingNotifier())

    notifier = RecordingNotifier()
    apenas = [good_listing("casa", price_usd=196000)]  # -2%, por debajo del 5%
    run_pipeline(fake_cfg, repo, FakeSource("fake", apenas), notifier)
    assert notifier.sent == []


def test_el_techo_de_alertas_difiere_pero_no_descarta(fake_cfg, repo):
    fake_cfg.alerts = {**fake_cfg.alerts, "max_alerts_per_run": 2}
    base = [good_listing(str(i)) for i in range(3)]
    run_pipeline(fake_cfg, repo, FakeSource("fake", base), RecordingNotifier())

    muchas = base + [good_listing(f"n{i}") for i in range(5)]
    notifier = RecordingNotifier()
    run_pipeline(fake_cfg, repo, FakeSource("fake", muchas), notifier)

    assert len(notifier.sent) == 2, "respeta el techo por corrida"
    assert len(repo.pending_alerts()) == 3, "las otras quedan reservadas, no perdidas"

    # Se drenan de a poco en las corridas siguientes.
    segundo = RecordingNotifier()
    run_pipeline(fake_cfg, repo, FakeSource("fake", muchas), segundo)
    assert len(segundo.sent) == 2
    assert len(repo.pending_alerts()) == 1


def test_una_fuente_que_explota_no_frena_a_las_demas(cfg, repo):
    """Seccion 23: MercadoLibre OK, InfoCasas ERROR, Gallito OK."""
    sana = FakeSource("sana", [good_listing("1", source="sana")])
    rota = FakeSource("rota", [], raises=RuntimeError("parser roto"))

    cfg.sources = {
        name: SourceConfig(
            name=name, enabled=True,
            searches=(SearchConfig(name="s", url="https://example.invalid/s"),),
        )
        for name in ("rota", "sana")
    }
    Pipeline(cfg, repo, RecordingNotifier(), {"rota": rota, "sana": sana}).run()

    assert sana.calls == 1, "la fuente sana igual corrio"
    estados = dict(
        repo._conn.execute("SELECT source, status FROM scrape_runs").fetchall()
    )
    assert estados["rota"] == "error"
    assert estados["sana"] == "ok"


def test_una_fuente_caida_no_desactiva_el_historial(fake_cfg, repo):
    """Seccion 28: 0 resultados por scraper roto != todas desaparecieron."""
    base = [good_listing(str(i)) for i in range(5)]
    run_pipeline(fake_cfg, repo, FakeSource("fake", base), RecordingNotifier())

    rota = FakeSource("fake", [], plausible=False, error="bloqueado")
    for _ in range(10):
        run_pipeline(fake_cfg, repo, rota, RecordingNotifier())

    activos = repo._conn.execute(
        "SELECT COUNT(*) FROM listings WHERE active = 1"
    ).fetchone()[0]
    assert activos == 5, "el historial sigue intacto pese al scraper roto"


def test_una_fuente_rota_termina_avisando_una_sola_vez(fake_cfg, repo):
    base = [good_listing(str(i)) for i in range(3)]
    run_pipeline(fake_cfg, repo, FakeSource("fake", base), RecordingNotifier())

    notifier = RecordingNotifier()
    rota = FakeSource("fake", [], plausible=False, error="sin resultados")
    for _ in range(6):
        run_pipeline(fake_cfg, repo, rota, notifier)

    degradadas = [m for m in notifier.sent if "parece haber cambiado" in m]
    assert len(degradadas) == 1

    run_pipeline(fake_cfg, repo, FakeSource("fake", base), notifier)
    assert any("volvió a funcionar" in m for m in notifier.sent)
