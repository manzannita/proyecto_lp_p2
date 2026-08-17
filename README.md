# NoticIA EC

Plataforma que recolecta noticias de medios digitales ecuatorianos (El Universo
y Primicias) vía RSS, las clasifica por tema, muestra tendencias en un dashboard
y ofrece un asistente de IA generativa que responde preguntas sobre las noticias
recolectadas.

Proyecto de la asignatura **Lenguajes de Programación** — ESPOL.

## Arquitectura

```
Capa de extracción      scraper/     Ruby + HTTParty + Nokogiri
        │                            descarga los feeds RSS y guarda las
        │                            noticias en crudo (tema_id = NULL)
        ▼
Base de datos           schema.sql   SQLite en desarrollo, PostgreSQL en producción
        │                            tablas: medios, temas, noticias
        ▼
Capa de procesamiento   backend/     Python + Flask + pandas
   y API                             clasifica, calcula tendencias y expone la API
        ▼
Capa de presentación    dashboard/   Chart.js / Plotly  (avance posterior)
```

### Reparto del equipo

| Integrante | Módulo | Pregunta de análisis | Issue |
|---|---|---|---|
| Annabella | Recolección (scraper) | Los 5 temas más cubiertos | [#1](../../issues/1) |
| Valentina | Preprocesamiento y clasificación | Diferencias entre El Universo y Primicias | [#2](../../issues/2) |
| Cristian | Asistente de IA generativa | Variación semana a semana por tema | [#3](../../issues/3) |

### Dónde vive la clasificación por tema

En **Python** (`backend/pipeline/`), no en el scraper de Ruby. El scraper inserta
las noticias con `tema_id = NULL` y el pipeline las completa después. Así hay una
sola implementación, y reclasificar cuando cambie la taxonomía es un `UPDATE`
sobre lo ya guardado en vez de volver a descargar todos los feeds.

## Requisitos previos

- **Ruby** ≥ 3.0 (probado con 3.3.12) y Bundler
- **Python** ≥ 3.10 (probado con 3.11)
- No hace falta instalar el CLI de SQLite: la base se crea con un script de Python.

## Instalación

```bash
git clone https://github.com/manzannita/proyecto_lp_p2.git
cd proyecto_lp_p2
```

**1. Variables de entorno**

```bash
cp .env.example .env      # en Windows:  copy .env.example .env
```

Editar `.env` y generar una `API_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

> En Windows, si creas el `.env` con PowerShell usa `-Encoding utf8`; el backend
> ya lee el archivo con `utf-8-sig`, así que un BOM tampoco lo rompe.

**2. Backend (Python)**

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
source .venv/bin/activate         # Linux / macOS
pip install -r backend/requirements.txt
```

**3. Scraper (Ruby)**

```bash
cd scraper && bundle install && cd ..
```

## Base de datos

`schema.sql` es la **fuente de verdad única** de las tablas, compartida por el
scraper y el backend. Para crearla:

```bash
python -m backend.init_db
```

Es idempotente: se puede correr las veces que haga falta sin duplicar nada. Crea
`medios`, `temas` y `noticias`, los índices, y siembra los dos medios y el
catálogo de temas.

| Tabla | Para qué |
|---|---|
| `medios` | El Universo y Primicias, con la URL de su feed |
| `temas` | Catálogo cerrado: política, economía, seguridad, salud, deportes, clima, internacional, otros |
| `noticias` | Una fila por nota. `tema_id IS NULL` = pendiente de clasificar |

La deduplicación la garantiza el motor: `url_hash` (SHA-256 de la URL
normalizada) tiene restricción `UNIQUE`.

> Si modificas `schema.sql`, avísalo en los tres issues antes de mergear: afecta
> a todo el equipo.

## Uso: scraper (Ruby)

```bash
cd scraper && bundle exec ruby scraper.rb
```

Recorre los medios activos de `scraper/config/medios.yml`, descarga cada feed,
lo parsea e inserta las noticias nuevas. Al terminar imprime un resumen:

```
RESUMEN DE LA RECOLECCION
--------------------------------------------------------------
MEDIO          ESTADO            LEIDAS   NUEVAS  DUPLICADAS
el-universo    ok                   100      100           0
primicias      ok                    30       30           0
--------------------------------------------------------------
TOTAL                               130      130           0
```

Códigos de salida: `0` si al menos un medio se procesó, `1` si fallaron todos.

**Manejo de errores.** Cada excepción de red se rescata de forma explícita, con
3 reintentos y backoff exponencial (1 s, 2 s, 4 s). Si un medio falla, se
registra y la corrida **continúa con el siguiente**: un diario caído nunca aborta
la recolección completa.

**Optimización.** El cliente guarda `ETag`, `Last-Modified` y el SHA-256 del
cuerpo de cada feed en `scraper/.cache/feeds.json`. Si el feed no cambió, se
omite el parseo y la escritura en la base.

> Verificado el 2026-08-16: Primicias no envía validadores, y El Universo los
> envía pero su CDN **no honra** el `If-None-Match` (responde 200 con el mismo
> ETag). Por eso existe el fallback por hash del cuerpo, que es el que realmente
> ahorra trabajo hoy. El `GET` condicional se mantiene porque es correcto y
> gratis: si el CDN empieza a honrarlo, ahorra además la transferencia.

Después de recolectar, el siguiente paso es clasificar (issue #2):

```bash
python -m backend.pipeline.procesar
```

## Uso: backend (Flask)

```bash
flask --app backend.app:crear_app run --port 5000
```

Sonda sin autenticación para verificar que levantó:

```bash
curl http://127.0.0.1:5000/health
# {"estado":"ok"}
```

### Seguridad

**Todas** las rutas `/api/*` exigen el header `X-API-Key` con el valor de la
variable de entorno `API_KEY`. Sin él responden `401` en JSON. La comparación usa
`hmac.compare_digest`. Ninguna clave está en el código.

### Integridad de las transacciones

Toda escritura pasa por el context manager `transaccion()` de `backend/db.py`:
`COMMIT` al salir bien, `ROLLBACK` ante cualquier excepción. Todas las consultas
usan placeholders `?`; nunca se concatena la entrada del usuario al SQL.

## Endpoints de la API

### `GET /api/tendencias/top-temas` — Annabella (issue #1)

Ranking de temas por cantidad de noticias.

| Param | Tipo | Default | Notas |
|---|---|---|---|
| `limite` | int | `5` | entre 1 y 50 |
| `desde` | `YYYY-MM-DD` | primera noticia | opcional |
| `hasta` | `YYYY-MM-DD` | hoy | opcional |
| `medio` | slug | todos | `el-universo` o `primicias` |

```bash
curl -H "X-API-Key: $API_KEY" \
  "http://127.0.0.1:5000/api/tendencias/top-temas?limite=5&medio=primicias"
```

```json
{
  "periodo": { "desde": "2026-08-01", "hasta": "2026-08-16" },
  "medio": "primicias",
  "total_noticias": 412,
  "clasificadas": 394,
  "sin_clasificar": 18,
  "limite": 5,
  "temas": [
    { "tema": "Seguridad", "slug": "seguridad", "total": 98, "porcentaje": 24.9 }
  ]
}
```

El ranking solo cuenta noticias ya clasificadas; las pendientes se reportan en
`sin_clasificar` para detectar si el pipeline del issue #2 está atrasado.

Errores: `400` si una fecha no parsea, si `desde > hasta`, si `limite` está fuera
de rango o si el `medio` no existe. `401` sin API key. Un periodo sin datos
devuelve `200` con `"temas": []`, no `404`.

### `GET /api/medios` y `GET /api/medios/comparativa` — Valentina (issue #2)

`GET /api/medios` devuelve el catálogo de medios activos y el total de noticias
recolectadas por cada uno. `GET /api/medios/comparativa` compara su distribución
temática.

| Parámetro | Tipo | Valor por defecto | Descripción |
|---|---|---|---|
| `desde` | `YYYY-MM-DD` | primera noticia | Inicio opcional del periodo |
| `hasta` | `YYYY-MM-DD` | hoy | Fin opcional del periodo |
| `temas` | slugs CSV | todos | Ejemplo: `seguridad,politica` |
| `normalizar` | bool | `true` | Porcentajes dentro de cada medio |

```bash
curl -H "X-API-Key: $API_KEY" \
  "http://127.0.0.1:5000/api/medios/comparativa?temas=seguridad,politica"
```

La respuesta contiene conteos y porcentajes por medio. `brechas` muestra la
diferencia en puntos porcentuales y qué medio prioriza cada tema, ordenada de
mayor a menor. Con `normalizar=false`, los porcentajes usan como denominador el
total combinado de ambos medios. Un periodo sin datos responde `200` con listas
vacías; fechas, booleanos o slugs inválidos responden `400`.

### `GET /api/tendencias/series-semanales` — Cristian (issue #3)

Evolución semana a semana de la cantidad de noticias sobre un tema. Agrupa por
semana ISO (lunes como inicio) y rellena con `total: 0` las semanas sin
noticias dentro del periodo, para que el gráfico del dashboard no mienta sobre
la tendencia.

| Parámetro | Tipo | Valor por defecto | Descripción |
|---|---|---|---|
| `tema` | slug | — | **obligatorio**, ej. `clima`, `seguridad` |
| `desde` | `YYYY-MM-DD` | primera noticia del tema | opcional |
| `hasta` | `YYYY-MM-DD` | hoy | opcional |
| `medio` | slug | todos | opcional, filtra por medio |

```bash
curl -H "X-API-Key: $API_KEY" \
  "http://127.0.0.1:5000/api/tendencias/series-semanales?tema=seguridad"
```

```json
{
  "tema": "seguridad",
  "granularidad": "semana",
  "periodo": { "desde": "2026-07-20", "hasta": "2026-08-16" },
  "serie": [
    { "semana_inicio": "2026-07-20", "semana_iso": "2026-W30", "total": 14 },
    { "semana_inicio": "2026-07-27", "semana_iso": "2026-W31", "total": 0 },
    { "semana_inicio": "2026-08-03", "semana_iso": "2026-W32", "total": 22 }
  ],
  "resumen": {
    "total_periodo": 36,
    "promedio_semanal": 12.0,
    "semana_pico": "2026-W32",
    "variacion_ultima_semana_pct": null
  }
}
```

El relleno de huecos y los cálculos del resumen (`promedio_semanal`,
`semana_pico`, `variacion_ultima_semana_pct`) se hacen con `pandas`
(`resample('W-MON')`) sobre la serie diaria ya consultada con SQL
parametrizado. `variacion_ultima_semana_pct` es `null` cuando hay menos de dos
semanas en el periodo o la penúltima semana no tiene noticias con las que
comparar.

Errores: `400` si falta `tema`, si una fecha no parsea, si `desde > hasta` o
si el `medio` no existe. `404` si el slug de `tema` no está en el catálogo.
`401` sin API key. Un tema válido sin noticias en el rango responde `200` con
`"serie": []`, no `404`.

### `POST /api/asistente/preguntar` — Cristian (issue #3)

Asistente de IA generativa que responde preguntas en lenguaje natural
**fundamentadas únicamente en las noticias recolectadas** — nunca inventa
datos. Antes de llamar al LLM, `backend/services/recuperador.py` busca en la
base (con `LIKE` parametrizado, nunca concatenando la entrada del usuario) las
noticias relacionadas con la pregunta; si no encuentra ninguna, la ruta
responde `200` con un mensaje de "no tengo datos suficientes" **sin llamar al
LLM**, para no gastar cuota ni arriesgar una alucinación.

**Variables de entorno** (agregar a `.env`, nunca al código):

| Variable | Para qué |
|---|---|
| `LLM_API_KEY` | Clave del proveedor del LLM (OpenAI). Se obtiene en [platform.openai.com/api-keys](https://platform.openai.com/api-keys). |
| `LLM_MODELO` | Modelo a usar, ej. `gpt-4o-mini`. |

Si falta cualquiera de las dos, `backend/services/asistente_ia.py` falla con
un mensaje claro apenas se necesita el LLM, no a medias de una petición con un
error críptico del proveedor.

```bash
curl -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"pregunta": "¿De qué se habló más esta semana en seguridad?", "limite_contexto": 20}' \
  http://127.0.0.1:5000/api/asistente/preguntar
```

```json
{
  "respuesta": "Durante la semana del 3 de agosto predominaron los operativos policiales, segun El Universo...",
  "fuentes": [
    { "titular": "Operativo policial deja seis detenidos en Duran", "medio": "El Universo", "url": "https://...", "fecha": "2026-08-05" }
  ],
  "noticias_consultadas": 18,
  "modelo": "gpt-4o-mini"
}
```

Body: `pregunta` (obligatorio, 1 a 500 caracteres) y `limite_contexto`
(opcional, 1 a 50, por defecto 20).

Cada llamada al proveedor usa un timeout de 30 s y reintenta una vez ante un
error transitorio (5xx o timeout de red); no reintenta ante `401`/`429`, ya
que repetir la misma petición no cambia el resultado.

Errores: `400` si falta `pregunta`, viene vacía o supera 500 caracteres, o si
`limite_contexto` no es un entero entre 1 y 50. `401` sin API key. `429` si el
proveedor aplica límite de tasa. `503` con
`{"error": "El asistente no esta disponible en este momento"}` ante timeout o
caída del proveedor — nunca se filtra el stack trace ni el mensaje crudo del
proveedor.

## Pipeline de clasificación

El pipeline toma las noticias pendientes (`tema_id IS NULL`), normaliza su texto,
las clasifica y actualiza cada lote dentro de una transacción:

```bash
python -m backend.pipeline.procesar
python -m backend.pipeline.procesar --lote 200
python -m backend.pipeline.procesar --reclasificar
```

Una segunda ejecución normal es idempotente y reporta `Procesadas: 0`.
`--reclasificar` vuelve a evaluar todo el histórico. El resumen final muestra el
total procesado, la distribución por tema, cuántas noticias cayeron en `otros` y
el tiempo empleado.

Las reglas viven en `backend/pipeline/temas.yml`. Cada slug debe coincidir con la
tabla `temas`. Se pueden ajustar `claves`, `peso` y `prioridad` sin modificar
Python. El titular pesa el doble que el resumen y los empates se resuelven por
la prioridad declarada. Las palabras vacías se mantienen en
`backend/pipeline/stopwords_es.txt`.

## Asistente de IA

Arma el contexto antes de llamar al LLM en dos pasos, para que la respuesta
esté siempre fundamentada en lo que realmente se recolectó:

1. **`backend/services/recuperador.py`** — `recuperar_contexto(pregunta,
   limite=20)` extrae términos de la pregunta, busca coincidencias en
   `titular`/`resumen` con `LIKE` parametrizado, detecta filtros de tema/fecha
   mencionados en la pregunta, y ordena por relevancia (peso doble al
   titular) y recencia. Si no hay coincidencias devuelve `[]`.
2. **`backend/services/asistente_ia.py`** — cliente HTTP del proveedor
   (OpenAI, Chat Completions). Usa un prompt de sistema
   (`backend/services/prompts.py`) que obliga a responder solo con el
   contexto entregado, citar el medio de cada dato y decir explícitamente "no
   tengo datos suficientes" cuando el contexto no alcance. Los errores del
   proveedor se envuelven en `LLMTimeout`, `LLMRateLimit` y `LLMError` para
   que la ruta decida el código HTTP sin filtrar el mensaje crudo.

**Variables de entorno:** ver `LLM_API_KEY` y `LLM_MODELO` en la sección del
endpoint `POST /api/asistente/preguntar` más abajo.

## Cómo correr los tests

**Backend (pytest):**

```bash
pytest
```

Las fixtures compartidas viven en `backend/tests/conftest.py` y levantan una BD
SQLite temporal creada desde `schema.sql` y sembrada con ~30 noticias de dos
medios, varios temas y varias semanas. **Los issues #2 y #3 las reutilizan**, así
que se puede testear sin esperar a que el scraper traiga datos reales.

Fixtures disponibles: `bd_temporal`, `app`, `cliente` (sin credenciales, para
probar los 401) y `cliente_auth` (con el header ya puesto).

**Scraper (RSpec):**

```bash
cd scraper && bundle exec rspec
```

Los tests usan **WebMock**: ninguno toca la red de verdad.

## Estructura del repositorio

```
proyecto_lp_p2/
├── schema.sql                 fuente de verdad de las tablas
├── .env.example
├── pytest.ini
├── backend/
│   ├── app.py                 factory + registro de los 4 blueprints
│   ├── config.py              variables de entorno
│   ├── db.py                  conexión, transaccion(), consultas
│   ├── auth.py                decorador @requiere_api_key
│   ├── init_db.py             crea la base desde schema.sql
│   ├── requirements.txt
│   ├── routes/
│   │   ├── tendencias.py      #1 Annabella
│   │   ├── medios.py          #2 Valentina
│   │   ├── series.py          #3 Cristian
│   │   └── asistente.py       #3 Cristian
│   ├── pipeline/              #2 Valentina
│   ├── services/              #3 Cristian
│   └── tests/
│       ├── conftest.py        fixtures compartidas
│       └── test_tendencias.py
└── scraper/
    ├── scraper.rb             orquestador
    ├── Gemfile
    ├── config/medios.yml      feeds RSS
    ├── lib/
    │   ├── rss_client.rb      descarga, reintentos, caché
    │   ├── parser.rb          Nokogiri, normalización de URLs y fechas
    │   └── repositorio.rb     persistencia y deduplicación
    └── spec/                  RSpec + WebMock
```

Los cuatro blueprints se registran de una vez en `app.py`, con `medios.py`,
`series.py` y `asistente.py` como stubs. Así los issues #2 y #3 solo tocan su
propio archivo de rutas y `app.py` no genera conflictos de merge.
