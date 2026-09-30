import pytest

from house_watch.config import ConfigError, Secrets, load_config


def test_rechaza_urls_que_robots_txt_prohibe(tmp_path):
    """InfoCasas prohibe en robots.txt los filtros combinados '*-y-*'."""
    path = tmp_path / "c.yaml"
    path.write_text(
        "sources:\n"
        "  infocasas:\n"
        "    enabled: true\n"
        "    searches:\n"
        "      - url: https://www.infocasas.com.uy/venta/casas-y-apartamentos/montevideo\n"
    )
    with pytest.raises(ConfigError, match="robots.txt"):
        load_config(path, secrets=Secrets())


def test_acepta_una_busqueda_por_tipo(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(
        "sources:\n"
        "  infocasas:\n"
        "    enabled: true\n"
        "    searches:\n"
        "      - url: https://www.infocasas.com.uy/venta/casas/montevideo\n"
    )
    cfg = load_config(path, secrets=Secrets())
    assert len(cfg.enabled_sources()) == 1


def test_secrets_nunca_se_filtran_en_repr():
    secrets = Secrets(telegram_bot_token="123:SUPERSECRETO", telegram_chat_id="99")
    assert "SUPERSECRETO" not in repr(secrets)
    assert "SUPERSECRETO" not in str(secrets)


def test_fuentes_habilitadas_por_defecto(cfg):
    # InfoCasas + MercadoLibre (API oficial). Gallito sigue bloqueada.
    names = [s.name for s in cfg.enabled_sources()]
    assert "infocasas" in names
    assert "mercadolibre" in names
    assert "gallito" not in names


def test_config_faltante_da_error_claro(tmp_path):
    with pytest.raises(ConfigError, match="No existe"):
        load_config(tmp_path / "nope.yaml", secrets=Secrets())
