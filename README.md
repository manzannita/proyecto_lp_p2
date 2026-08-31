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
Capa de presentación    dashboard/   HTML + JS nativo + Chart.js vendorizado
                                     servido por Flask en el mismo origen
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

**Todas** las rutas `/api/*` exigen la clave de `API_KEY`, presentada de una de
dos formas: el header `X-API-Key` (clientes programáticos, `curl`, los tests) o
la **cookie de sesión** que el servidor entrega junto con el dashboard
(navegador). Sin ninguna de las dos responden `401` en JSON. La comparación usa
`hmac.compare_digest` en ambos caminos. Ninguna clave está en el código, y
tampoco en el JavaScript del dashboard — ver [Dashboard](#dashboard).

### Integridad de las transacciones

Toda escritura pasa por el context manager `transaccion()` de `backend/db.py`:
`COMMIT` al salir bien, `ROLLBACK` ante cualquier excepción. Todas las consultas
usan placeholders `?`; nunca se concatena la entrada del usuario al SQL.

## Dashboard

### Vista: comparativa entre medios

La pestaña `#/comparativa` responde qué temas priorizan de manera distinta El
Universo y Primicias con barras agrupadas, una conclusión textual y una tabla de
brechas. El control de normalización distingue entre el porcentaje dentro de la
agenda de cada medio (lectura predeterminada) y el porcentaje sobre el volumen
global. La selección múltiple de temas y el modo elegido quedan en el query
string (`?temas=seguridad,economia&normalizar=false`), de modo que el análisis se
puede recargar o compartir. El filtro global de medio se ignora deliberadamente
porque esta vista siempre compara los dos medios.

La misma pestaña incluye la auditoría del pre-procesamiento: cobertura total,
clasificadas y pendientes, barras apiladas por medio y el peso de `otros`. Cada
gráfico tiene una tabla equivalente y la nota metodológica aclara que los
porcentajes usan solo noticias clasificadas y que los RSS no constituyen un
archivo histórico completo. Si hay pendientes, la pantalla indica ejecutar
`python -m backend.pipeline.procesar`.

Con el backend corriendo, el dashboard está en la raíz:

```bash
flask --app backend.app:crear_app run --port 5000
# abrir http://127.0.0.1:5000/
```

**No hay paso de build.** Ni `npm install`, ni bundler, ni transpilación: son
módulos ES nativos que el navegador carga directamente. Chart.js y las dos
tipografías están **vendorizadas** en `dashboard/vendor/`, así que el dashboard
se ve igual sin conexión a internet.

### Vistas

| Ruta | Pregunta de análisis | Visualización | Issue |
|---|---|---|---|
| `#/tendencias` | Los temas más cubiertos | Barras horizontales | [#6](../../issues/6) Annabella |
| `#/comparativa` | Qué prioriza cada medio | Barras agrupadas | [#7](../../issues/7) Valentina |
| `#/series` | Variación semana a semana | Líneas | [#8](../../issues/8) Cristian |
| `#/buscador` | Búsqueda por tema o palabra clave | Lista paginada | [#8](../../issues/8) Cristian |
| `#/asistente` | Preguntas en lenguaje natural | Hilo con fuentes citadas | [#3](../../issues/3) Cristian |

### Vista: asistente de IA

`dashboard/js/vistas/asistente.js` es la única vista que **escribe** contra la
API, y de ahí salen sus cuatro diferencias con las otras:

- **No se dispara sola.** Las demás vuelven a consultar en cada cambio de
  filtro; aquí cada llamada consume cuota de un proveedor pago, así que la
  petición sale solo cuando la persona envía la pregunta.
- **Lleva token CSRF**, por ser un `POST` autenticado por cookie (ver más
  abajo).
- **Muestra sus fuentes** debajo de cada respuesta: las noticias reales que se
  le pasaron al modelo. Sin esa lista la respuesta sería indistinguible de una
  alucinación.
- **No usa la barra de filtros.** El contexto lo arma `recuperador.py` leyendo
  la propia pregunta; si hay filtros puestos, la vista lo avisa en pantalla
  para que nadie concluya que el asistente miente.

Las preguntas sugeridas están verificadas contra el corpus: una sugerencia que
responde «no tengo datos suficientes» hace parecer roto al asistente en el
primer clic. `backend/tests/test_fundamentacion.py` las cubre.

### Vista: evolución semanal

`dashboard/js/vistas/series.js` — gráfico de líneas sobre
`GET /api/tendencias/series-semanales`, con dos modos que se eligen con un
selector segmentado:

- **Comparar temas**: hasta 3 temas del catálogo cerrado en el mismo gráfico,
  una línea por tema. Cada tema pide su propio endpoint y las tres peticiones
  van en paralelo con `Promise.all` (cada una cancela solo a la petición
  anterior de ese mismo tema, no a las de los otros dos: `api.js` separa la
  clave de cancelación por tema).
- **Por medio**: fija un tema y compara sus líneas entre El Universo y
  Primicias. Estas peticiones comparten tema y por lo tanto la misma clave de
  cancelación en `api.js`, así que se piden en secuencia y no en paralelo —
  pedirlas en paralelo haría que cada una cancelara a la anterior antes de
  que llegara su respuesta.

Cada línea trae su propia tarjeta de KPI (total del periodo, promedio
semanal, semana pico y variación de la última semana), con "sin dato
suficiente" cuando el backend manda `null` en vez de inventar un porcentaje.
La última semana de cada serie se dibuja con el tramo final punteado —nunca
sólida— porque casi siempre está incompleta y una caída ahí no es una
tendencia real. Como la leyenda por defecto de Chart.js queda vacía en
cualquier gráfico con más de una serie (el tema global de `graficos.js`
reemplaza `plugins.legend.labels` sin volver a definir su `generateLabels`),
la vista dibuja su propia leyenda en HTML combinando color, forma del
marcador y el nombre del tema o medio, para que identificar una línea nunca
dependa solo del color.

Hacer clic en un punto del gráfico navega al buscador (`#/buscador`) ya
filtrado por ese tema (o medio) y esa semana — es el enlace verificable entre
un pico de la serie y las noticias concretas que lo produjeron. La vista
también expone una `<table>` con las mismas semanas y totales, asociada al
`<canvas>` para que el gráfico tenga un equivalente accesible.

### Vista: buscador

`dashboard/js/vistas/buscador.js` — consume `GET /api/noticias` con un campo
de texto (debounce de 300 ms) y selectores de tema, medio y rango de fechas.
El campo de búsqueda y el selector de tema se guardan en el query string
(`?q=&tema=&pagina=`); el rango de fechas y el medio son los filtros
globales que ya gestiona `estado.js` y por eso la vista reacciona a ellos
sin suscribirse por su cuenta — `main.js` ya llama a `actualizar()` en cada
cambio.

Cada resultado se arma con `el()` de `ui.js`, nunca con `innerHTML`: el
titular y el resumen vienen de sitios externos y son entrada no confiable.
El término buscado se resalta dentro del titular y el resumen envolviendo
las coincidencias en `<mark>` mediante nodos de texto (comparando el texto
normalizado —minúsculas y sin tildes, igual que el backend— mientras se
inserta el texto original). El titular enlaza al artículo original con
`target="_blank"` y `rel="noopener noreferrer"`. Una región `aria-live` anuncia
el número de resultados, y el estado "sin resultados" sugiere ampliar el
rango o quitar un filtro en vez de mostrar una lista vacía sin explicación.

### La API key no vive en el JavaScript

Si el JS del navegador mandara el header `X-API-Key`, la clave sería visible en
DevTools y en el código fuente de la página, y la seguridad del avance 1
quedaría en nada. En su lugar:

1. `GET /` entrega el dashboard **y** deja la clave en una cookie `HttpOnly` +
   `SameSite=Strict` (`backend/routes/dashboard.py`).
2. `requiere_api_key` acepta la clave del header **o** de esa cookie
   (`backend/auth.py`).
3. El JS solo hace `fetch(url, { credentials: "same-origin" })` y nunca ve la
   clave: `HttpOnly` la vuelve inalcanzable desde JavaScript, así que un XSS no
   la puede exfiltrar, y `SameSite=Strict` impide que otro sitio provoque
   peticiones autenticadas.

### CSRF: por qué el POST del asistente lleva un segundo token

Mientras todos los endpoints fueron `GET`, la cookie de sesión no abría ningún
riesgo de falsificación: un `GET` no cambia estado. `POST
/api/asistente/preguntar` sí consume cuota de un proveedor pago, así que lleva
además `@requiere_csrf`, con el patrón de **doble envío**:

1. `GET /` emite un token aleatorio en la cookie `noticia_ec_csrf`. Esa cookie
   **no** es `HttpOnly`, a propósito: el JavaScript tiene que poder leerla.
2. El `fetch` la copia en el header `X-CSRF-Token` (`dashboard/js/api.js`).
3. El servidor exige que cookie y header coincidan.

Funciona porque otro sitio puede provocar una petición que arrastre las cookies
de la persona, pero **no puede leerlas** (lo impide la *same-origin policy*), así
que no puede construir el header. Es la segunda línea: la primera sigue siendo
`SameSite=Strict`.

Un cliente que se autentica con `X-API-Key` queda exento: no depende de
cookies, así que no hay nada que falsificar.

### Imprimir el dashboard

El concepto visual es papel impreso, así que el dashboard se imprime de verdad:
**Imprimir → Guardar como PDF** da una hoja presentable sin capturas, útil para
pegar evidencia en el informe. La hoja de impresión (`css/base.css`,
`@media print`) saca la navegación, los filtros y los botones, y deja el
cabezote con el periodo, las cifras y los datos.

Una decisión que conviene conocer: **en papel no sale el gráfico, sale la tabla
equivalente.** Chart.js redibuja el `<canvas>` de forma asíncrona cuando cambia
el ancho del contenedor, y la paginación del navegador es síncrona: la hoja es
más angosta que la pantalla, y el PDF salía con las barras a medio dibujar. Se
puede forzar un `resize()` en `beforeprint`, pero el resultado sigue dependiendo
de quién gane la carrera, y un gráfico que a veces sale vacío es peor que no
imprimirlo. La tabla lleva los mismos números y es la única forma de auditarlos
en papel. Lo único que no se puede hacer desde CSS es abrirla —un `<details>`
cerrado no lo abre ningún selector—, así que lo hace el handler de
`beforeprint` en `main.js`, que la devuelve a como estaba al terminar.

### Estructura y reparto

```
dashboard/
├── index.html                shell: cabezote, nav, filtros y 5 secciones VACÍAS
├── vendor/                   Chart.js 4.4.3 y las tipografías (sin CDN)
├── css/  base.css            tokens, tipografía, layout
│      componentes.css        tarjetas, fichas, tablas, estados
└── js/
    ├── api.js                único módulo que hace fetch
    ├── estado.js             filtros globales sincronizados con la URL
    ├── graficos.js           tema único de Chart.js y la paleta
    ├── ui.js                 DOM, estados y formateo
    ├── main.js               router por hash y contrato de vistas
    └── vistas/               un archivo por persona
```

**Regla anti-conflicto:** `index.html` solo tiene las cuatro `<section>` vacías;
cada vista genera su DOM desde su propio módulo de `js/vistas/`. Así los issues
#6, #7 y #8 nunca editan el mismo archivo. El contrato que implementa cada vista
(`montar` / `actualizar` / `desmontar`) está documentado al inicio de `main.js`.

### Decisiones de visualización

- **Paleta validada, no elegida a ojo.** Los ocho colores de serie
  (`--serie-1..8` en `base.css`) pasan los chequeos de banda de luminosidad,
  croma, contraste sobre el papel y separación para daltonismo protan/deutan; los
  tres primeros la pasan incluso comparando todos los pares entre sí, así que una
  vista puede superponer hasta tres series. El **orden es el mecanismo de
  seguridad**: no se reordena ni se recicla, y un noveno tema va a `otros`.
- **El color sigue a la entidad, no al ranking.** Una sola serie se pinta de un
  solo color; teñir cada barra según su tamaño duplicaría en color lo que el
  largo ya dice.
- **Cada gráfico tiene su tabla equivalente.** Un `<canvas>` no existe para un
  lector de pantalla, y el tooltip nunca puede ser la única forma de leer un dato.
- **Los estados vacío y de error son parte de la vista**, con el mensaje que
  manda el backend y un botón de reintento — nunca un gráfico en blanco.

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

### `GET /api/temas` — catálogo compartido

Catálogo cerrado de temas con cuántas noticias tiene clasificadas cada uno.
Existe para que el dashboard **no escriba los slugs a mano**: los selectores de
tema se arman con esta respuesta, así que agregar un tema a `schema.sql` y a
`pipeline/temas.yml` lo hace aparecer solo en la interfaz.

```bash
curl -H "X-API-Key: $API_KEY" http://127.0.0.1:5000/api/temas
```

```json
[
  { "id": 1, "nombre": "Politica", "slug": "politica", "total_noticias": 34 },
  { "id": 2, "nombre": "Economia", "slug": "economia", "total_noticias": 21 }
]
```

El orden es el del catálogo (por `id`) y **no** por volumen: el dashboard le
asigna a cada tema un color según su posición en esta lista, y un orden que
dependiera de los datos repintaría los gráficos en cada cambio de filtro.

### `GET /api/noticias` — Cristian (issue #8)

Buscador de noticias por palabra clave y/o filtros de catálogo. Es el
respaldo verificable del gráfico de `series-semanales`: permite pasar de un
pico en la serie a las noticias concretas que lo produjeron.

| Parámetro | Tipo | Valor por defecto | Descripción |
|---|---|---|---|
| `q` | texto | — | opcional, mínimo 2 caracteres; busca en `titular` y `resumen` |
| `tema` | slug | todos | opcional |
| `medio` | slug | todos | opcional |
| `desde` | `YYYY-MM-DD` | — | opcional |
| `hasta` | `YYYY-MM-DD` | — | opcional |
| `pagina` | int | `1` | ≥ 1 |
| `por_pagina` | int | `20` | entre 1 y 50 |

```bash
curl -H "X-API-Key: $API_KEY" \
  "http://127.0.0.1:5000/api/noticias?q=extorsion&tema=seguridad&pagina=1&por_pagina=20"
```

```json
{
  "total": 137,
  "pagina": 1,
  "por_pagina": 20,
  "paginas": 7,
  "noticias": [
    {
      "id": 1,
      "titular": "Fiscalía investiga caso de extorsión en el norte",
      "resumen": "...",
      "url": "https://...",
      "medio": "El Universo",
      "medio_slug": "el-universo",
      "tema": "Seguridad",
      "tema_slug": "seguridad",
      "fecha_publicacion": "2026-08-21 14:03:00"
    }
  ]
}
```

**Búsqueda sin tildes y sin distinguir mayúsculas.** `q` se compara contra
`titular`/`resumen` normalizando ambos lados (minúsculas y sin diacríticos
vía `unicodedata.normalize("NFKD", ...)`) con una función registrada en la
conexión SQLite (`conexion.create_function`), porque el motor no trae un
`unaccent()` de fábrica. Buscar `economia` encuentra "económica" y viceversa.

**SQL parametrizado, sin excepción.** El `LIKE` va con placeholders y el
comodín se arma en el parámetro (`f"%{termino}%"`), nunca interpolado en el
string del SQL; además se escapan `%`, `_` y `\` de la entrada del usuario
para que no actúen como comodines silenciosos dentro del patrón.

`total` se calcula con un `COUNT(*)` que reutiliza exactamente los mismos
filtros que la consulta paginada, para que `paginas` siempre coincida con
`ceil(total / por_pagina)`. El orden es `fecha_publicacion DESC, id DESC`: el
desempate por `id` no es cosmético — sin él, dos noticias con la misma fecha
pueden duplicarse o desaparecer al cambiar de página.

Errores: `400` si `q` tiene menos de 2 caracteres, si `pagina` es menor a 1,
si `por_pagina` está fuera de 1–50, si una fecha no parsea, si `desde > hasta`
o si `tema`/`medio` no existen en el catálogo (el mensaje incluye el valor
rechazado). `401` sin API key. Sin coincidencias responde `200` con
`"noticias": []` y `"total": 0`, nunca `404`.

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
| `LLM_API_KEY` | Clave del proveedor. Se obtiene en [console.anthropic.com](https://console.anthropic.com) → *Settings* → *API keys*; empieza con `sk-ant-api`. |
| `LLM_MODELO` | `claude-opus-5`, `claude-sonnet-5` o `claude-haiku-4-5`. Sin sufijo de fecha. |
| `LLM_WORKSPACE_ID` | **Opcional.** Solo si la clave está ligada a una identidad dentro de una organización que usa *workspaces*: la API responde `400` pidiendo el id del workspace en el que actúa (empieza con `wrkspc_`). Con una clave normal se deja vacío. |

Si faltan las dos primeras, `backend/services/asistente_ia.py` falla con un
mensaje claro apenas se necesita el LLM, no a medias de una petición con un
error críptico del proveedor.

**Diagnóstico de la configuración:**

```bash
python -m backend.verificar_llm
```

Desde el dashboard *cualquier* fallo del proveedor se ve igual — «el asistente
no está disponible» —, que es lo correcto de cara al usuario pero inservible
para depurar. Ese comando distingue una variable que falta, de una clave
rechazada, de un modelo inexistente, de una organización que exige *workspace*,
de falta de saldo, de un problema de red; y dice qué hacer en cada caso. Nunca
imprime la clave: solo su prefijo, su largo y una huella, que alcanza para
confirmar que el `.env` cambió de verdad.

> **Una suscripción a Claude no es crédito de API.** Son dos productos con
> facturación separada: la clave tiene que venir de la consola de API y esa
> cuenta necesita saldo propio. Sin saldo, la API responde `400` con
> `credit balance is too low` — no `429`, que es lo que uno esperaría.

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
  "modelo": "claude-haiku-4-5"
}
```

Body: `pregunta` (obligatorio, 1 a 500 caracteres) y `limite_contexto`
(opcional, 1 a 50, por defecto 20).

Cada llamada usa un timeout de 30 s y reintenta una vez ante un error
transitorio (5xx, 429 o fallo de red); no reintenta ante `400`/`401`, que son
errores del cliente frente al proveedor. Los reintentos y la espera exponencial
los hace el SDK oficial, no código propio.

Errores: `400` si falta `pregunta`, viene vacía o supera 500 caracteres, o si
`limite_contexto` no es un entero entre 1 y 50. `401` sin API key. `429` si el
proveedor aplica límite de tasa. `503` con
`{"error": "El asistente no esta disponible en este momento"}` ante timeout o
caída del proveedor — nunca se filtra el stack trace ni el mensaje crudo del
proveedor, aunque sí se registra en el log del servidor. `403` si la petición
viene autenticada por cookie y sin el token CSRF; un cliente que manda
`X-API-Key` queda exento.

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
2. **`backend/services/asistente_ia.py`** — cliente del proveedor (Anthropic,
   Messages API, vía el SDK oficial `anthropic`). Es la **única** pieza que
   habla con el proveedor: cambiarlo solo toca este archivo, y ya pasó una vez
   —de OpenAI a Anthropic— sin que ninguna capa de arriba se enterara. Usa un
   prompt de sistema
   (`backend/services/prompts.py`) que obliga a responder solo con el
   contexto entregado, citar el medio de cada dato y decir explícitamente "no
   tengo datos suficientes" cuando el contexto no alcance. Los errores del
   proveedor se envuelven en `LLMTimeout`, `LLMRateLimit` y `LLMError` para
   que la ruta decida el código HTTP sin filtrar el mensaje crudo.

**Variables de entorno:** ver `LLM_API_KEY`, `LLM_MODELO` y
`LLM_WORKSPACE_ID` en la sección del endpoint `POST /api/asistente/preguntar`
más abajo, junto con el comando `python -m backend.verificar_llm`.

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
│   ├── app.py                 factory + registro de todos los blueprints
│   ├── config.py              variables de entorno
│   ├── db.py                  conexión, transaccion(), consultas
│   ├── auth.py                @requiere_api_key (header o cookie) + @requiere_csrf
│   ├── init_db.py             crea la base desde schema.sql
│   ├── verificar_llm.py       diagnostica la configuración del asistente
│   ├── requirements.txt
│   ├── routes/
│   │   ├── tendencias.py      #1 Annabella
│   │   ├── medios.py          #2 Valentina
│   │   ├── series.py          #3 Cristian
│   │   ├── asistente.py       #3 Cristian
│   │   ├── dashboard.py       #6 Annabella  sirve el dashboard + cookies
│   │   ├── noticias.py        #8 Cristian   buscador paginado
│   │   └── temas.py           catálogo compartido por las vistas
│   ├── pipeline/              #2 Valentina
│   ├── services/              #3 Cristian
│   └── tests/
│       ├── conftest.py        fixtures compartidas
│       └── test_*.py
├── dashboard/                 frontend (ver la sección Dashboard)
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

Todos los blueprints se registran de una vez en `app.py`, y el que todavía no
está implementado entra como stub (así entraron `medios.py`, `series.py` y
`asistente.py` en el avance 1, y `noticias.py` en el avance 2). De esa forma
cada issue solo toca su propio archivo de rutas y `app.py` no genera conflictos
de merge. Al cierre del avance 3 no queda ningún stub.
