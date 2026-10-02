"""Tests del flujo OAuth Authorization Code + Refresh Token de MercadoLibre.

Los canjes se mockean: acá se testea lógica (PKCE, extracción de código,
rotación y persistencia), no red.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from house_watch.ml_auth import (
    MlAuthError,
    STATE_ACCESS_TOKEN,
    STATE_REFRESH_TOKEN,
    TokenManager,
    TokenPair,
    authorization_url,
    exchange_code,
    extract_code,
    generate_pkce,
    refresh,
)


class FakeStore:
    def __init__(self):
        self.data: dict[str, str] = {}

    def get_state(self, key: str) -> str | None:
        return self.data.get(key)

    def set_state(self, key: str, value: str) -> None:
        self.data[key] = value


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------

def test_generate_pkce_challenge_es_sha256_del_verifier():
    verifier, challenge = generate_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == expected


def test_generate_pkce_verifiers_son_unicos():
    a = generate_pkce()
    b = generate_pkce()
    assert a[0] != b[0]


# ---------------------------------------------------------------------------
# authorization_url y extract_code
# ---------------------------------------------------------------------------

def test_authorization_url_contiene_params_obligatorios():
    url = authorization_url("12345", "http://localhost/", "CHA-LEN-GE")
    assert url.startswith("https://auth.mercadolibre.com.uy/authorization?")
    assert "response_type=code" in url
    assert "client_id=12345" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%2F" in url
    assert "code_challenge=CHA-LEN-GE" in url
    assert "code_challenge_method=S256" in url


def test_authorization_url_sin_pkce_omite_challenge():
    url = authorization_url("12345", "http://localhost/", None)
    assert "code_challenge" not in url


def test_extract_code_de_url_completa():
    assert extract_code("https://localhost/?code=TG-abc123&state=xyz") == "TG-abc123"


def test_extract_code_de_codigo_pelado():
    assert extract_code("TG-abc123") == "TG-abc123"


def test_extract_code_rechaza_basura():
    with pytest.raises(MlAuthError, match="authorization_code"):
        extract_code("https://localhost/?error=permission_denied")
    with pytest.raises(MlAuthError, match="authorization_code"):
        extract_code("")


# ---------------------------------------------------------------------------
# Canjes: exchange_code y refresh
# ---------------------------------------------------------------------------

def test_exchange_code_envia_grant_correcto():
    with patch("house_watch.ml_auth.httpx.post") as post:
        post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"access_token": "APP_USR-x", "refresh_token": "TG-1"},
        )
        pair = exchange_code("id", "sec", "CODE", "http://localhost/", "VER")

    data = post.call_args.kwargs["data"]
    assert data["grant_type"] == "authorization_code"
    assert data["code"] == "CODE"
    assert data["code_verifier"] == "VER"
    assert data["redirect_uri"] == "http://localhost/"
    assert pair.access_token == "APP_USR-x"
    assert pair.refresh_token == "TG-1"


def test_exchange_code_error_http_se_reporta_con_body():
    with patch("house_watch.ml_auth.httpx.post") as post:
        post.return_value = MagicMock(
            status_code=400,
            text='{"error":"invalid_grant","message":"code expired"}',
        )
        with pytest.raises(MlAuthError, match="invalid_grant"):
            exchange_code("id", "sec", "CODE", "http://localhost/")


def test_refresh_envia_grant_correcto():
    with patch("house_watch.ml_auth.httpx.post") as post:
        post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"access_token": "APP_USR-2", "refresh_token": "TG-2"},
        )
        pair = refresh("id", "sec", "TG-viejo")

    data = post.call_args.kwargs["data"]
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "TG-viejo"
    assert pair.refresh_token == "TG-2"


# ---------------------------------------------------------------------------
# TokenManager: rotación y persistencia
# ---------------------------------------------------------------------------

def _manager(store: FakeStore) -> TokenManager:
    return TokenManager(store, "id", "sec")


def test_manager_sin_tokens_pide_ml_auth():
    with pytest.raises(MlAuthError, match="ml-auth"):
        _manager(FakeStore()).get_access_token()


def test_manager_refresca_y_rota_refresh_token():
    store = FakeStore()
    store.set_state(STATE_REFRESH_TOKEN, "TG-viejo")

    with patch("house_watch.ml_auth.httpx.post") as post:
        post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"access_token": "AT-nuevo", "refresh_token": "TG-nuevo"},
        )
        token = _manager(store).get_access_token()

    assert token == "AT-nuevo"
    # Rotación: el refresh_token guardado es el NUEVO, no el consumido.
    assert store.get_state(STATE_REFRESH_TOKEN) == "TG-nuevo"
    # El access token quedó cacheado con expiración.
    cached = json.loads(store.get_state(STATE_ACCESS_TOKEN))
    assert cached["token"] == "AT-nuevo"
    assert cached["expires_at"] > time.time()


def test_manager_reusa_access_token_vigente_sin_refrescar():
    """Si el access token persistido no expiró, no hay POST (rota menos)."""
    store = FakeStore()
    store.set_state(
        STATE_ACCESS_TOKEN,
        json.dumps({"token": "AT-cache", "expires_at": time.time() + 3600}),
    )
    store.set_state(STATE_REFRESH_TOKEN, "TG-algo")

    with patch("house_watch.ml_auth.httpx.post") as post:
        token = _manager(store).get_access_token()

    post.assert_not_called()
    assert token == "AT-cache"
    # El refresh_token no se tocó.
    assert store.get_state(STATE_REFRESH_TOKEN) == "TG-algo"


def test_manager_access_token_expirado_se_refresca():
    """Un access_token vencido se descarta y se canjea el refresh."""
    store = FakeStore()
    store.set_state(
        STATE_ACCESS_TOKEN,
        json.dumps({"token": "AT-viejo", "expires_at": time.time() - 10}),
    )
    store.set_state(STATE_REFRESH_TOKEN, "TG-vigente")

    with patch("house_watch.ml_auth.httpx.post") as post:
        post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"access_token": "AT-nuevo", "refresh_token": "TG-nuevo"},
        )
        token = _manager(store).get_access_token()

    assert token == "AT-nuevo"
    assert store.get_state(STATE_REFRESH_TOKEN) == "TG-nuevo"


def test_manager_repr_no_filtra_valores():
    pair = TokenPair(access_token="APP_USR-SUPERSECRETO", refresh_token="TG-SECRETO")
    assert "SUPERSECRETO" not in repr(pair)
    assert "SECRETO" not in str(pair)
