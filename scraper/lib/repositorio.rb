# frozen_string_literal: true

require 'sqlite3'
require 'digest'

require_relative 'parser'

module NoticiaEC
  # Persistencia del scraper.
  #
  # Dos decisiones importantes:
  #
  #   1. La deduplicacion la garantiza el motor, no el codigo. url_hash tiene
  #      UNIQUE en schema.sql y se usa ON CONFLICT(url_hash) DO NOTHING. Un
  #      SELECT previo seria vulnerable a una condicion de carrera si dos
  #      corridas se solapan.
  #
  #      Se usa ON CONFLICT y NO "INSERT OR IGNORE" a proposito: OR IGNORE
  #      silencia CUALQUIER violacion de restriccion, asi que una noticia sin
  #      titular (NOT NULL) se descartaria en silencio en vez de avisarnos.
  #      ON CONFLICT solo ignora el duplicado de url_hash y deja que el resto
  #      de errores salgan a la superficie. Ademas es la misma sintaxis en
  #      PostgreSQL, que es a donde migra el proyecto.
  #
  #   2. Una transaccion por medio. Todas las noticias de un feed entran en un
  #      solo BEGIN/COMMIT: si algo revienta a mitad se hace ROLLBACK y no
  #      quedan filas parciales. Ademas es mucho mas rapido que un commit por
  #      fila, que es la optimizacion principal de la escritura.
  #
  # Todas las consultas van parametrizadas con placeholders (?).
  class Repositorio
    SQL_INSERT = <<~SQL
      INSERT INTO noticias (
        medio_id, tema_id, titular, resumen, url, url_hash,
        categoria_origen, fecha_publicacion, fecha_recoleccion
      ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT (url_hash) DO NOTHING
    SQL

    def initialize(ruta_bd:, logger:)
      @logger = logger
      @db = SQLite3::Database.new(ruta_bd)
      @db.results_as_hash = true
      @db.execute('PRAGMA foreign_keys = ON')
      # WAL permite que el backend lea mientras el scraper escribe.
      @db.execute('PRAGMA journal_mode = WAL')
    end

    def cerrar
      @db.close unless @db.closed?
    end

    # Asegura que el medio del YAML exista en la tabla y devuelve su id.
    def id_de_medio(slug:, nombre:, url_feed:)
      # DO UPDATE y no DO NOTHING: config/medios.yml es la fuente de verdad de
      # los medios, asi que si ahi cambia el nombre o la URL del feed, la tabla
      # tiene que seguirlo. Con DO NOTHING quedaba el valor de la primera
      # corrida para siempre.
      @db.execute(
        'INSERT INTO medios (nombre, slug, url_feed, activo) VALUES (?, ?, ?, 1) ' \
        'ON CONFLICT (slug) DO UPDATE SET nombre = excluded.nombre, ' \
        'url_feed = excluded.url_feed',
        [nombre, slug, url_feed]
      )
      fila = @db.get_first_row('SELECT id FROM medios WHERE slug = ?', [slug])
      raise "No se pudo resolver el medio '#{slug}'" if fila.nil?

      fila['id']
    end

    # Inserta el lote completo de un medio en una sola transaccion.
    # Devuelve { nuevas:, duplicadas: }.
    def guardar_lote(medio_id, noticias)
      return { nuevas: 0, duplicadas: 0 } if noticias.empty?

      recolectado_en = Time.now.utc.strftime('%Y-%m-%d %H:%M:%S')
      insertadas = 0

      @db.transaction
      begin
        sentencia = @db.prepare(SQL_INSERT)
        begin
          noticias.each do |noticia|
            sentencia.execute(
              medio_id,
              noticia[:titular],
              noticia[:resumen],
              noticia[:url],
              self.class.hash_de_url(noticia[:url]),
              noticia[:categoria_origen],
              noticia[:fecha_publicacion],
              recolectado_en
            )
            # changes > 0 solo cuando el INSERT realmente inserto la fila.
            insertadas += 1 if @db.changes.positive?
          end
        ensure
          sentencia.close
        end
        @db.commit
      # SQLite3::Exception ya es StandardError: rescatar la generica alcanza.
      rescue StandardError => e
        @db.rollback
        @logger.error("Rollback del lote (#{noticias.size} noticias): #{e.class}: #{e.message}")
        raise
      end

      { nuevas: insertadas, duplicadas: noticias.size - insertadas }
    end

    def total_noticias
      @db.get_first_value('SELECT COUNT(*) FROM noticias')
    end

    # SHA-256 de la URL ya normalizada. Misma normalizacion que usa el parser,
    # para que el hash sea estable entre corridas.
    def self.hash_de_url(url)
      Digest::SHA256.hexdigest(Parser.normalizar_url(url))
    end
  end
end
