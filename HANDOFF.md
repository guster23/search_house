# HANDOFF — search_house

Estado al **2026-10-03**: MercadoLibre **descartada** y extraída del proyecto
por completo. La fuente activa es **InfoCasas** (API interna, ~3.900 casas,
~20 s por run). El pipeline corre horario en GitHub Actions a $0.

**Novedad 2026-10-03**: Gallito **sí es accesible desde el runner** con un
navegador real (Chrome headed bajo Xvfb). Ver sección "Gallito" abajo.

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
- ~~(Opcional) Borrar del repo los screenshots `screenshot_ml.png` y
  `screenshot_tmp.png`~~: ya no estan en el repo.

## Gallito (investigacion + probe, 2026-10-03)

### Hallazgo: sitemap declarado en robots.txt

`https://www.gallito.com.uy/robots.txt` responde **200 incluso con httpx/curl**
(unico endpoint que pasa sin challenge). Su contenido declara intencion de
permitir crawling:

```
User-agent: *
Allow: /
Sitemap: https://www.gallito.com.uy/sitemap.xml
```

`/sitemap.xml` es un sitemapindex con sub-sitemaps por operacion y tipo:
`sitemap-venta-casas.xml`, `sitemap-alquiler-casas.xml`,
`sitemap-venta-apartamentos.xml` (+ `-1..4`), `sitemap-alquiler-apartamentos.xml`,
`sitemap-alquiler-venta-otros.xml`.

Los **slugs del sitemap traen datos estructurados**:
`/venta-casa-la-blanqueada-montevideo-4-dormitorios-inmuebles-29165314`
= operacion (`venta`/`alquiler`) + tipo (`casa`/`apartamento`) + barrio +
departamento + dormitorios + ID del aviso. Es decir, el sitemap solo ya
permite filtrar sin abrir cada pagina de detalle.

No existe API ni feed oficial de Gallito (busqueda web sin resultados).
Gallito pertenece a **El Pais** (relacionado con `inmuebles-data.elpais.com.uy`).

### Bloqueo con clientes HTTP

Sitemaps y paginas (busqueda y detalle) dan **403 `cf-mitigated: challenge`**
con httpx **y** curl, incluso desde IP residencial con UA Chrome real y HTTP/2.
Headers incluyen `accept-ch: Sec-CH-UA-*`, `critical-ch` y
`server-timing: chlray;desc="..."` (challenge ray de Cloudflare): es un
**Cloudflare managed challenge**.

### Probe de accesibilidad desde el runner

Creado para responder una pregunta que nunca se habia medido: Gallito, que con
httpx desde IP residencial da 403, es accesible desde una IP de datacenter?
No evade nada (sin proxies, sin rotar identidades, sin resolver challenges):
solo mide y publica evidencia.

- `scripts/probe_gallito.py`: mide 5 URLs (robots, sitemapindex, sitemap de
  venta-casas, pagina de busqueda, una pagina de detalle) con 3 clientes:
  **httpx**, **curl** y **Chrome real headed** (Playwright `headless=False`
  bajo Xvfb). Clasifica cada respuesta como `OK` / `CHALLENGE` / `HTTP_403` /
  `ERROR`. Veredicto global `ACCESIBLE` si algun cliente obtiene `OK`;
  exit 0/1.
- `.github/workflows/test-gallito-probe.yml`:
  `workflow_dispatch` + `push` filtrado a `scripts/probe_gallito.py` y al
  propio workflow; `ubuntu-latest`, timeout 8 min; instala `httpx playwright`
  + `playwright install --with-deps chromium`; corre
  `xvfb-run -a python scripts/probe_gallito.py | tee probe_gallito.txt`;
  sube artifact `gallito-probe-report` (14 dias) con `if: always()`.

Nota de implementacion: Cloudflare embebe scripts de challenge hasta en
paginas que **si** cargan, asi que buscar "challenge" en el body da falsos
positivos. La senal buena es status + `cf-mitigated` + **titulo de la
intersticial** (`"just a moment"`, `"un momento"`, `"attention required"`).

### Resultado del runner (2026-10-03T14:06Z)

- **httpx**: robots.txt 200 OK; sitemapindex / sitemap-venta-casas /
  `/inmuebles/venta` / detalle -> 403 `cf_mitigated: challenge` -> CHALLENGE.
- **curl**: identico (robots 200 OK, resto 403 CHALLENGE).
- **chrome_headed**: robots.txt 200 OK; sitemapindex 200 OK (9.194 B);
  `sitemap-venta-casas.xml` 200 OK (**9.314.625 B**); `/inmuebles/venta`
  200 OK ("Venta de Apartamentos y Casas en Uruguay | Gallito Luis", 249 KB);
  pagina de detalle -> 403 "Un momento…" CHALLENGE.
- **Veredicto: ACCESIBLE** (`verdicts=['CHALLENGE', 'OK']`).

Interpretacion: desde la IP de Azure el **navegador real headed pasa** el
managed challenge para sitemaps y pagina de busqueda (no para el detalle
probado). Es distinto del caso ML (muro de login que el navegador no pasaba).
Gallito es **potencialmente viable** con Playwright + sitemap. Pendiente:
confirmar si el detalle bloqueado es sistematico o puntual (aviso dado de baja)
y si el challenge se mantiene estable en corridas sucesivas.

### Medicion de estabilidad (en curso)

El probe acepta `--repeat N` (default 1) y `--delay S` (default 10), y el
workflow ahora corre **`--repeat 5 --delay 15`**: cada corrida abre un contexto
nuevo (cookies/clearance frescos) para ver si el challenge se resuelve de forma
consistente desde la misma IP o si es azaroso. La salida agrega un bloque
`stability` con el conteo de veredictos por URL. Resultados del runner:
**pendiente de push** (el workflow dispara al tocar `scripts/probe_gallito.py`).

### Via limpia (sin scraping)

`robots.txt` permite el crawling, pero Cloudflare bloquea el acceso
programatico. La via oficial y de riesgo cero seria escribirle a Gallito /
El Pais pidiendo un feed o acceso al sitemap sin challenge.

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
  (Gallito, si se implementa, seria la excepcion: requeriria Playwright.)

## Como seguir (opciones para reemplazar ML)

- **Gallito**: el probe del runner (2026-10-03) mostro que un **navegador real
  headed pasa** el challenge para el sitemap y la busqueda.
  Camino posible: Playwright (headed bajo Xvfb) + sitemap, sin proxies. Sigue
  gratis dentro de los minutos de CI. Falta decidir si se implementa y medir
  estabilidad del challenge en corridas sucesivas.
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
