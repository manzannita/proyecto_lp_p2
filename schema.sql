-- NoticIA EC - esquema de base de datos
-- Fuente de verdad unica para el scraper (Ruby) y el backend (Flask).
--
-- Escrito para SQLite (desarrollo) manteniendo compatibilidad con PostgreSQL:
-- se evitan tipos y funciones especificos de un motor. Al migrar a PostgreSQL
-- lo unico que hay que cambiar es INTEGER PRIMARY KEY AUTOINCREMENT por
-- GENERATED ALWAYS AS IDENTITY.
--
-- Se usa ON CONFLICT ... DO NOTHING y no "INSERT OR IGNORE" a proposito:
-- OR IGNORE es sintaxis exclusiva de SQLite y ademas silencia CUALQUIER
-- violacion de restriccion (NOT NULL, CHECK, FK), no solo el duplicado.
--
-- Las fechas se guardan como TEXT en ISO-8601 UTC ('YYYY-MM-DD HH:MM:SS'),
-- que es ordenable lexicograficamente y portable entre ambos motores.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- medios: los diarios digitales de los que se recolecta
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS medios (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre   TEXT    NOT NULL,
    slug     TEXT    NOT NULL UNIQUE,
    url_feed TEXT    NOT NULL,
    activo   INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
);

-- ---------------------------------------------------------------------------
-- temas: catalogo cerrado de categorias tematicas
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS temas (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT    NOT NULL,
    slug   TEXT    NOT NULL UNIQUE
);

-- ---------------------------------------------------------------------------
-- noticias
--
-- tema_id es NULL a proposito: el scraper inserta la noticia "cruda" y el
-- pipeline de clasificacion en Python (issue #2) la completa despues.
--   tema_id IS NULL  ->  pendiente de clasificar
-- Esto permite reclasificar todo el historico cuando cambie la taxonomia,
-- sin necesidad de volver a descargar los feeds.
--
-- url_hash es la llave anti-duplicados: SHA-256 de la URL normalizada
-- (sin querystring de tracking ni fragmento). La restriccion UNIQUE es lo que
-- garantiza la idempotencia del scraper a nivel de motor, no un SELECT previo.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS noticias (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    medio_id          INTEGER NOT NULL REFERENCES medios (id) ON DELETE CASCADE,
    tema_id           INTEGER          REFERENCES temas  (id) ON DELETE SET NULL,
    titular           TEXT    NOT NULL,
    resumen           TEXT,
    url               TEXT    NOT NULL,
    url_hash          TEXT    NOT NULL UNIQUE,
    categoria_origen  TEXT,
    fecha_publicacion TEXT    NOT NULL,
    fecha_recoleccion TEXT    NOT NULL,
    clasificado_en    TEXT
);

-- Indices pensados para las tres preguntas de analisis del proyecto:
--   top-temas          -> filtra por fecha y agrupa por tema
--   comparativa medios -> agrupa por medio y tema
--   series semanales   -> filtra por tema y recorre fechas
CREATE INDEX IF NOT EXISTS idx_noticias_fecha
    ON noticias (fecha_publicacion);
CREATE INDEX IF NOT EXISTS idx_noticias_tema_fecha
    ON noticias (tema_id, fecha_publicacion);
CREATE INDEX IF NOT EXISTS idx_noticias_medio_tema
    ON noticias (medio_id, tema_id);

-- ---------------------------------------------------------------------------
-- Semillas
-- ---------------------------------------------------------------------------

-- URLs verificadas contra los sitios reales el 2026-08-16.
-- Se usa el feed general de cada medio a proposito: mezclar feeds por seccion
-- sesgaria el conteo de temas hacia las secciones elegidas, que es justamente
-- lo que la pregunta de analisis pretende medir sin sesgo.
INSERT INTO medios (nombre, slug, url_feed, activo) VALUES
    ('El Universo', 'el-universo', 'https://www.eluniverso.com/arc/outboundfeeds/rss/?outputType=xml', 1),
    ('Primicias',   'primicias',   'https://www.primicias.ec/rss/home.xml',                              1)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO temas (nombre, slug) VALUES
    ('Politica',      'politica'),
    ('Economia',      'economia'),
    ('Seguridad',     'seguridad'),
    ('Salud',         'salud'),
    ('Deportes',      'deportes'),
    ('Clima',         'clima'),
    ('Internacional', 'internacional'),
    ('Otros',         'otros')
ON CONFLICT (slug) DO NOTHING;
