"""OAuth de MercadoLibre: Authorization Code + Refresh Token (AC+RT).

La API `/sites/{site}/search` devuelve HTTP 403 para tokens de aplicación
(`client_credentials`); requiere token de usuario. Los refresh tokens de ML
son de UN SOLO USO: cada canje devuelve un access_token (6 h) y un
refresh_token NUEVO que hay que guardar de inmediato (docs oficiales:
"We only allow using the last REFRESH_TOKEN generated"; dura 6 meses).

Por eso la autenticación se divide en dos momentos:

1. `house-watch ml-auth` (interactivo, una vez): abre el navegador en la
   página de autorización de ML, el usuario pega la URL de redirección (o el
   `code`), se canjea por tokens y el refresh_token queda guardado en la base
   (tabla `app_state` via TokenStore).
2. Cada run: si hay access_token vigente en la base se usa; si no, se canjea
   el refresh_token (que devuelve uno nuevo, también persistido).

Nunca se loguean ni se imprimen valores de tokens. El `__repr__`/`__str__` del
resultado del canje muestra solo longitudes.

Requiere que en el DevCenter la app tenga el grant "Authorization Code"
habilitado (además de Client Credentials, que ya no se usa para buscar).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets as pysecrets
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

log = logging.getLogger(__name__)

API_BASE = "https://api.mercadolibre.com"
TOKEN_URL = f"{API_BASE}/oauth/token"

# Dominio de autorización para Uruguay (los docs usan .com.ar según el país).
AUTH_BASE = "https://auth.mercadolibre.com.uy/authorization"

# El access token expira en 6 h; lo renovamos 5 min antes para no correr
# una búsqueda con un token a punto de morir.
ACCESS_TOKEN_REFRESH_MARGIN_S = 300

# Claves en app_state.
STATE_REFRESH_TOKEN = "ml_refresh_token"
STATE_ACCESS_TOKEN = "ml_access_token"       # JSON: {"token": ..., "expires_at": epoch}


class MlAuthError(Exception):
    """No se pudo obtener/renovar el token de usuario."""


class TokenStore(Protocol):
    """Lo que la fuente necesita del repositorio para persistir tokens.

    `SqlListingRepository` ya lo cumple con get_state/set_state (tabla
    app_state). Protocol en vez de import directo para no acoplar módulos.
    """

    def get_state(self, key: str) -> str | None: ...

    def set_state(self, key: str, value: str) -> None: ...


@dataclass(frozen=True)
class TokenPair:
    """Respuesta de /oauth/token. El repr nunca muestra valores."""

    access_token: str
    refresh_token: str | None

    def __repr__(self) -> str:  # pragma: no cover - anti-leak
        return (
            f"TokenPair(access_token=<len {len(self.access_token)}>, "
            f"refresh_token={'<presente>' if self.refresh_token else '<no venia>'})"
        )

    __str__ = __repr__


# ---------------------------------------------------------------------------
# PKCE (si la app lo tiene habilitado; si no, los params se omiten solos)
# ---------------------------------------------------------------------------

def generate_pkce() -> tuple[str, str]:
    """Devuelve (code_verifier, code_challenge) con S256.

    ML solo soporta S256 y plain; S256 es el recomendado (los docs marcan
    plain como no recomendado).
    """
    verifier = base64.urlsafe_b64encode(pysecrets.token_bytes(48)).decode().rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


def authorization_url(client_id: str, redirect_uri: str, code_challenge: str | None) -> str:
    """URL para abrir en el navegador y autorizar la app."""
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    return f"{AUTH_BASE}?{urlencode(params)}"


def extract_code(pasted: str) -> str:
    """Extrae el authorization_code de lo que pegó el usuario.

    Acepta la URL completa de redirección (…?code=TG-xxx&state=…) o el código
    pelado. Lanza MlAuthError si no hay código.
    """
    pasted = pasted.strip()
    if "code=" in pasted:
        qs = parse_qs(urlparse(pasted).query)
        codes = qs.get("code")
        if codes and codes[0]:
            return codes[0]
    if pasted and "=" not in pasted and "/" not in pasted and " " not in pasted:
        return pasted
    raise MlAuthError(
        "no se pudo extraer el authorization_code; pegá la URL completa de "
        "redirección (https://…?code=…) o solo el código"
    )


# ---------------------------------------------------------------------------
# Canjes contra /oauth/token
# ---------------------------------------------------------------------------

def _post_token(data: dict, timeout: float = 15.0) -> TokenPair:
    try:
        resp = httpx.post(TOKEN_URL, data=data, timeout=timeout)
    except httpx.HTTPError as exc:
        raise MlAuthError(f"error de red contra /oauth/token: {exc}") from exc
    if resp.status_code != 200:
        raise MlAuthError(f"token fallido: HTTP {resp.status_code} — {resp.text[:200]}")
    body = resp.json()
    token = body.get("access_token")
    if not token:
        raise MlAuthError(f"respuesta sin access_token: {list(body.keys())}")
    return TokenPair(access_token=str(token), refresh_token=body.get("refresh_token"))


def exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str | None = None,
) -> TokenPair:
    """Canjea el authorization_code por el primer par de tokens."""
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if code_verifier:
        data["code_verifier"] = code_verifier
    return _post_token(data)


def refresh(
    client_id: str, client_secret: str, refresh_token: str
) -> TokenPair:
    """Canjea el refresh_token por uno nuevo.

    IMPORTANTE: la respuesta trae un refresh_token NUEVO y el anterior queda
    invalidado (un solo uso). El llamador debe persistir el nuevo de
    inmediato; si no, la única salida es re-autorizar la app.
    """
    return _post_token(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }
    )


# ---------------------------------------------------------------------------
# TokenManager: decide si usar el access_token guardado o refrescar
# ---------------------------------------------------------------------------

class TokenManager:
    """Obtiene un access_token de usuario válido, rotando el refresh_token.

    Orden de resolución en cada run:
      1. access_token persistido no expirado (evita un POST por corrida;
         dura 6 h y los runs son horarios, así que acierta 5 de cada 6).
      2. refresh_token persistido → refresh (y persistir el nuevo par).
    Si no hay nada persistido, el error indica correr `house-watch ml-auth`.
    """

    def __init__(self, store: TokenStore, client_id: str, client_secret: str):
        self._store = store
        self._client_id = client_id
        self._client_secret = client_secret

    def get_access_token(self) -> str:
        import json

        cached = self._store.get_state(STATE_ACCESS_TOKEN)
        if cached:
            try:
                data = json.loads(cached)
                if float(data.get("expires_at", 0)) > time.time() + ACCESS_TOKEN_REFRESH_MARGIN_S:
                    return str(data["token"])
            except (ValueError, KeyError, TypeError):
                log.debug("ml_access_token en app_state es inválido; se ignora")

        refresh_token = self._store.get_state(STATE_REFRESH_TOKEN)
        if not refresh_token:
            raise MlAuthError(
                "no hay tokens de MercadoLibre guardados; corré "
                "`house-watch ml-auth` una vez para autorizar la app"
            )

        pair = refresh(self._client_id, self._client_secret, refresh_token)
        self._persist(pair)
        return pair.access_token

    def _persist(self, pair: TokenPair) -> None:
        """Guarda access_token (con expiración) y el refresh_token nuevo.

        El refresh se persiste PRIMERO: si el proceso muere entre las dos
        escrituras, con el refresh nuevo guardado se pierde solo el access
        token (se regenera), nunca la autorización completa.
        """
        import json

        if pair.refresh_token:
            self._store.set_state(STATE_REFRESH_TOKEN, pair.refresh_token)
        else:
            log.warning(
                "mercadolibre: el canje no devolvió refresh_token; el actual "
                "pudo quedar consumido. Si el próximo run falla con "
                "invalid_grant, corré `house-watch ml-auth` de nuevo."
            )
        expires_at = time.time() + 6 * 3600  # expires_in 10800 según docs
        self._store.set_state(
            STATE_ACCESS_TOKEN,
            json.dumps({"token": pair.access_token, "expires_at": expires_at}),
        )


def interactive_auth(
    client_id: str, client_secret: str, redirect_uri: str, store: TokenStore,
    use_pkce: bool = True,
) -> None:
    """Flujo de autorización una sola vez, desde la terminal.

    1. Imprime la URL de autorización (e intenta abrirla en el navegador).
    2. El usuario autoriza y pega la URL de redirección (o el código).
    3. Canjea el código y persiste ambos tokens en la base.

    use_pkce=False para apps sin PKCE: si la pantalla de ML dice "la
    aplicación no puede conectarse a tu cuenta" con todo lo demás bien
    (grant habilitado, redirect_uri exacta), probar sin PKCE.
    """
    import webbrowser

    verifier: str | None = None
    challenge: str | None = None
    if use_pkce:
        verifier, challenge = generate_pkce()
    url = authorization_url(client_id, redirect_uri, challenge)
    print("\nAbrí esta URL en el navegador y autorizá la app:\n")
    print(url)
    try:
        webbrowser.open(url)
    except Exception:  # pragma: no cover
        pass

    print(
        "\nDespués de autorizar, el navegador va a intentar ir a "
        f"{redirect_uri}"
        "\nSi la página no carga (error, 404, sitio ajeno): está bien, es lo"
        "\nesperado. Copiá la URL COMPLETA de la barra de direcciones, que "
        "incluye\n?code=..., y pegala acá abajo."
    )
    pasted = input("\nURL de redirección (o solo el código) y Enter: ")
    code = extract_code(pasted)
    pair = exchange_code(
        client_id, client_secret, code, redirect_uri, code_verifier=verifier
    )
    TokenManager(store, client_id, client_secret)._persist(pair)
    print("Listo: tokens guardados en la base. Los runs próximos los usan solos.")
