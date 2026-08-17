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

_Pendiente._

### `POST /api/asistente/preguntar` — Cristian (issue #3)

_Pendiente._

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

_Pendiente — issue #3 (Cristian)._

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
