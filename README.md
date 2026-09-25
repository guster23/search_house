# House Watch Uruguay

Recibís un Telegram cuando aparece una casa que cumple tus criterios en los
portales inmobiliarios uruguayos.

Sin servidor, sin dominio, sin frontend, sin IA, **sin computadora prendida** y
sin pagar nada: es un batch job efímero que GitHub Actions dispara cada hora.

```
GitHub Actions (scheduler)  →  Python (proceso efímero)  →  Turso (estado)
                                        ↓
                                     Telegram
```

---

## Estado actual de las fuentes

Verificado con requests reales el **2026-09-25**:

| Fuente | Estado | Detalle |
|---|---|---|
| **InfoCasas** | ✅ activa | Página server-rendered con `__NEXT_DATA__`. Sin navegador, sin API key. |
| **MercadoLibre** | 🚫 bloqueada | Devuelve **HTTP 200** con su página anti-bot (`suspicious-traffic-frontend`). La API pública da 403 sin OAuth. |
| **Gallito** | 🚫 bloqueada | Cloudflare managed challenge (`cf-mitigated: challenge`). |

Las dos bloqueadas quedan declaradas en `config.yaml` con `enabled: false` y
documentadas en su módulo. No se intenta evadir bloqueos ni resolver CAPTCHAs.

> **Por qué importa el caso de MercadoLibre:** devuelve `200`, no un error. Un
> scraper que confíe en el status code reportaría "0 propiedades" para siempre
> sin avisar nada. Por eso la detección de scrapers rotos mira el **contenido**
> de la respuesta, nunca el código HTTP.

InfoCasas alcanza de sobra para arrancar: una sola búsqueda devuelve ~3.900
casas en Montevideo, y el JSON de la página de resultados ya trae descripción
completa, coordenadas, superficies, dormitorios, baños, amenities e
inmobiliaria. **Nunca hace falta abrir la página de detalle**, así que un run
completo son unos 10 requests y ~20 segundos.

---

## Instalación

### 1. Crear el repositorio privado

```bash
gh repo create house-watch --private --source=. --push
```

Tiene que ser **privado**: `config.yaml` contiene tus criterios de búsqueda.
Los secretos nunca se versionan.

> Los workflows programados se desactivan solos tras 60 días de inactividad
> **solo en repos públicos**. En uno privado no hace falta ningún keepalive.

### 2. Crear la base en Turso

```bash
curl -sSfL https://get.tur.so/install.sh | bash
turso auth signup
turso db create house-watch
turso db show house-watch --url          # → TURSO_DATABASE_URL
turso db tokens create house-watch       # → TURSO_AUTH_TOKEN
```

### 3. Aplicar las migraciones

```bash
export TURSO_DATABASE_URL=...
export TURSO_AUTH_TOKEN=...
pip install -e '.[turso]'
house-watch run --migrate-only
```

Las migraciones también se aplican solas en cada ejecución (son idempotentes),
así que este paso es opcional pero sirve para confirmar que la conexión anda.

### 4. Crear el bot de Telegram

En Telegram, hablá con [@BotFather](https://t.me/BotFather):

```
/newbot
```

Te devuelve el `TELEGRAM_BOT_TOKEN`.

### 5. Mandarle un mensaje al bot

Buscá tu bot en Telegram y escribile cualquier cosa (`hola`). Sin este paso el
bot no puede iniciar la conversación.

### 6. Obtener el `chat_id`

```bash
curl -s "https://api.telegram.org/bot<TU_TOKEN>/getUpdates" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"][0]["message"]["chat"]["id"])'
```

### 7. Cargar los secrets en GitHub

`Settings → Secrets and variables → Actions → New repository secret`:

```
TURSO_DATABASE_URL
TURSO_AUTH_TOKEN
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

O por CLI:

```bash
gh secret set TURSO_DATABASE_URL
gh secret set TURSO_AUTH_TOKEN
gh secret set TELEGRAM_BOT_TOKEN
gh secret set TELEGRAM_CHAT_ID
```

### 8. Configurar `config.yaml`

**Este es el paso que más incide en la calidad de los resultados.**

Armá la búsqueda a mano en el portal, con sus propios filtros (zona, precio,
dormitorios), y pegá la URL resultante:

```yaml
sources:
  infocasas:
    enabled: true
    searches:
      - name: costa-canelones
        url: https://www.infocasas.com.uy/venta/casas/canelones/hasta-250000-dolares
```

⚠️ El `robots.txt` de InfoCasas prohíbe las URLs de filtro combinado `*-y-*`
(por ejemplo `/venta/casas-y-apartamentos/`). Usá una búsqueda por tipo de
propiedad. Si te equivocás, el programa falla al arrancar con un mensaje claro
en vez de scrapear algo que no debe.

Después ajustá `filters`, `scoring` y `alerts` a tu caso. Los valores que vienen
son un ejemplo, no tus preferencias.

### 9. Ejecutar a mano

`Actions → House Watch → Run workflow`.

**La primera corrida no manda ninguna alerta.** Guarda el catálogo actual como
línea de base: alertar sobre 200 casas que llevan meses publicadas sería ruido,
no información. A partir de la segunda corrida avisa solo de lo que aparece.

### 10. Confirmar

Después de la segunda corrida deberías empezar a recibir mensajes cuando
aparezca algo que cumpla tus criterios.

---

## Uso local

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# Corrida completa contra SQLite, imprimiendo en pantalla en vez de Telegram
house-watch run --db ./local.db --dry-run

# Con Telegram real, todavía local
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
house-watch run --db ./local.db

pytest -q
```

Opciones útiles: `--source infocasas` (limita a una fuente, aunque esté
deshabilitada), `--migrate-only`, `--verbose`.

---

## Cómo decide qué alertar

```
búsqueda → normalizar → comparar con la base → filtros duros → score
                                                                 ↓
                                        score ≥ mínimo  →  reservar alerta
                                                                 ↓
                                                            Telegram
```

- **Filtros duros** (`filters`): precio, dormitorios, departamento y palabras
  que descalifican (nuda propiedad, derechos posesorios, ocupada, remate).
- **Score de preferencias** (`scoring`): determinista, 0–100. Todos los pesos
  están en `config.yaml`; se ajustan sin tocar código.
- **Score de oportunidad**: compara el precio por m² edificado contra la
  mediana de propiedades parecidas (misma zona, mismos dormitorios, superficie
  similar). Necesita al menos 15 comparables, así que **queda en blanco las
  primeras semanas** y aparece solo cuando hay historia suficiente. Las alertas
  nunca dependen de él.

### Garantías

| Situación | Qué pasa |
|---|---|
| GitHub ejecuta el mismo run dos veces | Un solo Telegram. La reserva en la tabla `alerts` con `dedupe_key` único lo impide. |
| Telegram se cae justo después de reservar | La alerta queda pendiente y se reenvía en la corrida siguiente. No se pierde. |
| Un portal se cae | Las demás fuentes siguen. Cada una está aislada. |
| Un scraper se rompe | Tras 3 corridas sin resultados plausibles avisa **una sola vez**, y avisa de nuevo cuando se recupera. |
| Un scraper devuelve 0 por estar roto | **No** marca todo el historial como inactivo. Las ausencias solo cuentan si la fuente estuvo sana. |
| Aparecen 40 casas de golpe | Manda como mucho `max_alerts_per_run` y reparte el resto en las corridas siguientes. No descarta ninguna. |
| Una propiedad baja de precio | Alerta si supera `price_drop_threshold_percent`, una vez por precio nuevo. |

---

## Costo

| Servicio | Uso | Costo |
|---|---|---|
| Repositorio GitHub | privado | $0 |
| GitHub Actions | ~744 min/mes de 2.000 gratis | $0 |
| Turso | despreciable frente a 5 GB / 500M lecturas / 10M escrituras | $0 |
| Telegram | — | $0 |
| Servidor, dominio, SSL, frontend, LLM | no existen | $0 |
| **Total** | | **$0/mes** |

Actions factura por minuto entero redondeando hacia arriba, así que 24 runs
diarios de ~20 segundos cuestan 24 minutos por día (744/mes), no 8.

Si algún proveedor cambia sus límites, la lógica de negocio no está acoplada a
ninguno: `ListingRepository`, `ListingSource` y `Notifier` son interfaces, y el
scheduler puede pasar a `cron`, `launchd` o un runner propio sin tocar el resto.

---

## Estructura

```
src/house_watch/
├── cli.py              punto de entrada (sin scheduler interno)
├── pipeline.py         orquestación de un run
├── config.py           config.yaml + secretos del entorno
├── models.py           Listing, SourceResult, RunStats
├── budget.py           deadline de ejecución
├── http.py             cliente httpx con reintentos y jitter
├── browser.py          fallback de navegador (no instanciado)
├── sources/            infocasas · mercadolibre · gallito
├── repository/         interfaz + una implementación SQL, dos conexiones
├── notify/             interfaz + Telegram + formato de mensajes
├── normalize.py        texto, números, ubicaciones, amenities
├── filters.py          filtros duros y tempranos
├── scoring.py          score de preferencias
├── opportunity.py      comparables y mediana
├── health.py           detección de scrapers rotos
└── dedupe.py           cross-posting entre portales
```

Los tests corren contra la **respuesta real** de InfoCasas capturada en
`tests/fixtures/`, incluida la página anti-bot de MercadoLibre como caso
negativo.

## Mantenimiento

No requiere ninguno en condiciones normales. Cuando un portal cambia su
estructura, el sistema te avisa por Telegram en vez de fallar en silencio.

Para mirar el estado:

```bash
turso db shell house-watch "SELECT * FROM source_health"
turso db shell house-watch "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 10"
```
