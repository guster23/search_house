# HANDOFF — search_house

Estado al **2026-10-02**: MercadoLibre **descartada** y extraída del proyecto
por completo. La fuente activa es **InfoCasas** (API interna, ~3.900 casas,
~20 s por run). El pipeline corre horario en GitHub Actions a $0.

## Veredicto final sobre MercadoLibre (diagnóstico 2026-09-30 → 10-02)

Requisito duro del usuario: todo debe correr 100% en GitHub Actions, costo $0.
Ninguna vía hacia ML cumple ambas condiciones:

1. **API oficial `/sites/MLU/search` → 403 `forbidden`**: con App Token
   (`client_credentials`) y con token de usuario. El OAuth AC+RT funcionó
   perfecto (`/users/me` 200, `/users/{id}/items/search` 200), pero la
   búsqueda pública está bloqueada a nivel de app (política para apps
   personales nuevas). El permiso VIS del DevCenter es solo para inmobiliarias
   que publican, no para buscar. RSS: 404.
2. **Web con curl → 302 a `/gz/account-verification`** (muro de login).
3. **Chrome headless en el runner → muro** (página de error / `abuse-china-wall`).
4. **Chrome real headed bajo Xvfb + perfil persistente → muro de login igual.**
   Corridas verificadas por API y evidencia publicada (rama `probe-veredicto`,
   ya eliminada): el runner sin cookies recibe "ingresa a tu cuenta" con
   trace-id nuevo en cada intento.
5. **Trasplante de cookies del perfil local (anonimas, con clearance
   `c_*`/`_bmc`) al runner via Secret → muro de login igual.** ML liga la
   confianza a la IP residencial, no solo al device.

Alternativas restantes (fuera de alcance por decisión del usuario):
- Proxy residencial o API de scraping: ~$5-15/mes, rompe el objetivo $0.
- Certificar la app en el DevCenter: lenta (semanas), incierta, y mientras
  tanto no hay búsqueda.
- Loguear la cuenta real desde el runner: pondría la cuenta (vendedor) en
  riesgo de marcado/suspensión. Descartado.

## Extraccion de ML del codigo (2026-10-02)

Eliminado:
- `src/house_watch/sources/mercadolibre.py` (fuente API REST)
- `src/house_watch/ml_auth.py` (OAuth AC+RT, TokenManager)
- `tests/test_mercadolibre.py`, `tests/test_ml_auth.py`
- `tests/fixtures/mercadolibre_antibot.html`
- `scripts/` completo (probes headless, headed, CI y export de cookies)
- `.github/workflows/test-ml-probe.yml` (workflow de diagnóstico)

Limpieza: `cli.py` (comando `ml-auth`, flags `--redirect-uri/--no-pkce`,
inyección de TokenStore), `config.py` (secretos `ML_CLIENT_ID/SECRET`),
`config.yaml` (fuente), `watch.yml` (env ML), `README.md` (sección 7b, tabla
de fuentes, estructura), `health.py` (docstring), `tests/conftest.py`
(fixture antibot), `tests/test_infocasas.py`, `tests/test_config.py`,
`tests/test_pipeline.py` (referencias).

Pendiente manual del usuario (no urgente):
- Borrar los secrets `ML_CLIENT_ID`, `ML_CLIENT_SECRET` y `ML_STORAGE_STATE`
  en Settings → Secrets and variables → Actions.
- (Opcional) Borrar la app y sus tokens en el DevCenter de MercadoLibre.
- (Opcional) Limpiar `app_state` de Turso: claves `ml_access_token` y
  `ml_refresh_token`.
- (Opcional) Borrar del repo los screenshots `screenshot_ml.png` y
  `screenshot_tmp.png` (artefactos del diagnostico, siguen trackeados).

## Arquitectura (resumen)

- Un proceso por corrida, sin scheduler interno; el scheduler es Actions
  (`watch.yml`, cron `17 * * * *`, timeout 2 min, concurrency serializada).
- `ListingSource` / `ListingRepository` / `Notifier` son interfaces; fuentes
  registradas en `SOURCES` dentro de `cli.py`.
- Deteccion de scrapers rotos por **contenido** (`SourceResult.plausible`),
  nunca por status code (leccion aprendida con ML y su 200 anti-bot).
- Persistencia: Turso (libsql) en produccion, SQLite en tests/local. Tabla
  `app_state` para estado KV arbitrario.
- Sin Playwright ni navegadores en produccion: InfoCasas es server-rendered.

## Como seguir (opciones para reemplazar ML)

- **Gallito**: bloqueada por Cloudflare managed challenge. Revisar cada tanto
  si abre, o evaluar proxy (mismo costo que para ML).
- **Proxy residencial compartido** (~$5-15/mes) delante de InfoCasas no hace
  falta (no esta bloqueada); solo tendria sentido si se reintenta ML/Gallito.
- **Mas busquedas de InfoCasas** (mas zonas, alquileres): gratis, inmediato,
  mismo modulo. Es el camino de menor riesgo hoy.

## Comandos utiles

```bash
# Tests
# (110 antes de extraer ML; 76 ahora).
.venv/bin/python -m pytest -q

# Run local contra Turso (seco, sin Telegram)
house-watch run --config config.yaml --dry-run

# Corrida manual en Actions
# Actions → House Watch → Run workflow
```
