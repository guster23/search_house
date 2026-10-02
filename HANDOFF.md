# Handoff — Integración MercadoLibre (rama `feat/mercadolibre-api`)

> Resumen de la sesión de trabajo para retomar el debugging después.

## Contexto del proyecto

House Watch Uruguay: batch job en GitHub Actions (cada hora) que monitorea
portales inmobiliarios, normaliza, filtra y manda alertas por Telegram.
Estado en Turso. InfoCasas funciona (~207 items/run). Gallito bloqueada
(Cloudflare). MercadoLibre es la fuente que se está integrando.

## Diagnóstico final del bug (confirmado, no hipótesis)

Cadena de problemas resueltos en orden:

1. ~~Secrets no inyectados en el workflow~~ → commit `8a35976`.
2. ~~`/sites/MLU/search` devuelve **403 `{"message":"forbidden",...}`** con
   App Token (`client_credentials`), incluso con params mínimos
   (`?category=MLU1459&limit=1`), con o sin token en el header~~.

**Causa raíz confirmada empíricamente:**

- Mismo token funciona en `/users/me` (200) y `/users/{id}/items/search` (200),
  así que ni el token ni la cuenta están mal.
- `/sites/MLU/search` da 403 **con y sin token** → el endpoint está
  restringido para apps nuevas (restricción conocida de ML desde ~2023/24);
  requiere token de **usuario**.
- La solución es OAuth **Authorization Code + Refresh Token (AC+RT)**: token
  de usuario estándar, que sí puede buscar por categoría sobre todos los
  vendedores. `/users/{id}/items/search` NO reemplaza la búsqueda global
  (solo sirve para publicaciones de un vendedor conocido).

## Semántica de tokens ML (documentación oficial, verificada 2026-10-01)

- `access_token` de usuario: **6 h** (`expires_in: 10800`).
- `refresh_token`: **de UN SOLO USO**. Cada canje devuelve uno nuevo y el
  anterior queda invalidado ("We only allow using the last REFRESH_TOKEN
  generated"). Dura 6 meses.
- Se invalida además si el usuario cambia su password o revoca la app.
- Grant habilitado requerido en DevCenter: "Authorization Code" (además del
  Client Credentials que ya estaba).

**Implicancia de arquitectura:** el refresh token rota en cada corrida y los
GitHub Secrets no se pueden escribir desde el runner → los tokens se
persisten en la **base** (tabla `app_state`, ya existente, vía
`get_state`/`set_state` del repo).

## Qué se implementó en esta sesión

Todo en la rama `feat/mercadolibre-api`, sin pushear aún:

- **`src/house_watch/ml_auth.py`** (nuevo): OAuth AC+RT completo.
  - `generate_pkce()` (S256; si la app no tiene PKCE, los params se omiten).
  - `authorization_url()`, `extract_code()` (acepta URL completa o código
    pelado), `exchange_code()`, `refresh()`.
  - `TokenManager`: en cada run usa el access_token persistido si no expiró
    (evita un POST por corrida: 5 de cada 6 runs no rotan), si no canjea el
    refresh y **persiste el nuevo primero** (si el proceso muere entre las
    dos escrituras, se pierde el access token, no la autorización).
  - `interactive_auth()`: flujo de una vez desde la terminal.
  - `TokenPair.__repr__` no filtra valores; solo longitudes.
- **`src/house_watch/sources/mercadolibre.py`**: ya no usa
  `client_credentials`; resuelve el token con `TokenManager` (store inyectado
  con `set_store()`), y el mensaje de error HTTP ahora **incluye el body**
  (`resp.text[:200]`), porque un 403 pelado no diagnosticable fue la mitad
  del tiempo perdido en esta sesión. `fetch_detail` manda el Bearer token.
- **`src/house_watch/cli.py`**: comando nuevo `house-watch ml-auth` (con
  `--redirect-uri`, default `http://localhost/`) e inyección del repo como
  token store antes del pipeline.
- **Tests**: `tests/test_ml_auth.py` (nuevo: PKCE, extract_code, canjes con
  mocks, rotación, cache del access token, anti-leak en repr) y
  `tests/test_mercadolibre.py` actualizado (mock de `_resolve_token`, caso
  sin store, 403 con body). **110 passed** en local.
- README (estado de fuentes + nueva sección "7b. Autorizar MercadoLibre") y
  config.yaml (comentario de la fuente) actualizados.

## Pasos para retomar (en orden)

1. **Commit y push** de los cambios de esta sesión.
2. **En el DevCenter de la app ML**: habilitar grant "Authorization Code" y
   registrar una Redirect URI. El DevCenter **rechaza `localhost`**; da igual:
   la URL no necesita existir ni cargar (el `code` via en la barra del
   navegador). Registrar una URL HTTPS válida cualquiera (ej. la home de un
   sitio propio, o `https://example.com/`) y pasarsela al comando con
   `--redirect-uri`; tiene que coincidir exactamente.
3. **Autorizar una vez, local, contra Turso de producción:**
   ```bash
   export TURSO_DATABASE_URL=... TURSO_AUTH_TOKEN=...
   export ML_CLIENT_ID=... ML_CLIENT_SECRET=...
   house-watch ml-auth --redirect-uri 'https://TU-URL-REGISTRADA/'
   ```

   Tras autorizar, el navegador intenta ir a la URL registrada y muy
   probablemente falle al cargar: es lo esperado. Copiar la URL completa de
   la barra de direcciones (incluye `?code=...`) y pegarla en la terminal.
4. **Probar un run local apuntando a Turso** (o directo en CI):
   ```bash
   house-watch run --dry-run
   ```
5. **Merge del PR a main** y corrida manual en Actions.
6. **Verificar:**
   ```bash
   turso db shell house-watch "SELECT source, status, items_seen, error FROM scrape_runs ORDER BY id DESC LIMIT 5"
   ```
   Esperado: `mercadolibre | ok | X`.

## Riesgos conocidos / plan B

- **Si el 403 persiste incluso con token de usuario**: el body del error (ya
  visible en `scrape_runs.error` y en los logs) va a decir si es scope
  faltante o bloqueo por app. En ese caso: revisar permisos marcados en
  DevCenter (read debe estar tildado), y si ML efectivamente bloqueó la app,
  quedaría solo scraping con navegador (`browser.py` existe como fallback no
  instanciado) o contactar soporte de DevCenter.
- **`invalid_grant` en un run** (refresh token consumido dos veces o
  expirado): el error lo dice y la solución es re-correr `ml-auth`. No
  debería pasar en operación normal: la rotación persiste el nuevo refresh
  ANTES de seguir, y el access token cacheado evita refreshear 5 de cada 6
  corridas.
- **PKCE**: si la app no lo tiene habilitado, el flujo funciona igual (los
  params se omiten). Si lo tiene, es obligatorio enviarlos.
- **`screenshot_tmp.png`** sin trackear: basura temporal, borrar.

## Archivos clave

| Archivo | Rol |
|---|---|
| `src/house_watch/ml_auth.py` | OAuth AC+RT: PKCE, canjes, rotación, persistencia |
| `src/house_watch/sources/mercadolibre.py` | Fuente ML: token de usuario + búsqueda paginada + detalle |
| `src/house_watch/cli.py` | `run` y `ml-auth`; inyecta el repo como token store |
| `.github/workflows/watch.yml` | Secrets ML ya inyectados al `env` (commit 8a35976) |
| `tests/test_ml_auth.py` | Tests del flujo OAuth |
| `tests/test_mercadolibre.py` | Tests de la fuente |

## Notas de diseño ya resueltas (no re-discutir)

- Sin credenciales/tokens, la fuente reporta error accionable ("corré
  `house-watch ml-auth`") y NO interrumpe el pipeline.
- El store de tokens es un `Protocol` (get_state/set_state): el repo SQL lo
  cumple; si mañana hay otro backend, solo cambia la inyección.
- Token de usuario compartido: el run completo usa un solo access_token.
- `needs_detail` solo abre detalle de items nuevos o con precio cambiado; la
  descripción viene de `/items/{id}/description`.
