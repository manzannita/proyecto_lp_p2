# frozen_string_literal: true

# Orquestador de la recoleccion de noticias (issue #1, Annabella).
#
#   ruby scraper/scraper.rb
#
# Recorre los medios activos de config/medios.yml, descarga su feed, lo parsea
# y guarda las noticias nuevas. Las inserta con tema_id = NULL: clasificarlas
# es tarea del pipeline de Python (issue #2).
#
# Regla clave: si un medio falla, se registra y se continua con el siguiente.
# Un diario caido nunca puede abortar la corrida completa.
#
# Codigos de salida:
#   0 -> al menos un medio se proceso bien
#   1 -> fallaron todos los medios, o no habia ninguno activo

require 'logger'
require 'yaml'
require 'dotenv'

require_relative 'lib/rss_client'
require_relative 'lib/parser'
require_relative 'lib/repositorio'

module NoticiaEC
  class Scraper
    RAIZ = File.expand_path('..', __dir__)
    CONFIG_MEDIOS = File.join(__dir__, 'config', 'medios.yml')
    CACHE_FEEDS = File.join(__dir__, '.cache', 'feeds.json')

    def initialize(logger: nil, ruta_bd: nil, ruta_config: CONFIG_MEDIOS)
      @logger = logger || construir_logger
      @ruta_bd = ruta_bd || self.class.ruta_bd_por_defecto
      @ruta_config = ruta_config
    end

    # Las rutas relativas de DATABASE_URL se resuelven contra la RAIZ del repo y
    # no contra el directorio actual: si no, `cd scraper && ruby scraper.rb`
    # buscaria la base dentro de scraper/ y no la encontraria.
    def self.ruta_bd_por_defecto
      Dotenv.load(File.join(RAIZ, '.env'))
      configurada = ENV.fetch('DATABASE_URL', '').strip
      return File.join(RAIZ, 'noticia_ec.db') if configurada.empty?

      File.absolute_path?(configurada) ? configurada : File.join(RAIZ, configurada)
    end

    def ejecutar
      unless File.exist?(@ruta_bd)
        @logger.error("No existe la base #{@ruta_bd}. Crea la base primero:  python -m backend.init_db")
        return 1
      end

      medios = medios_activos
      if medios.empty?
        @logger.error('No hay medios activos en config/medios.yml')
        return 1
      end

      cliente = RssClient.new(ruta_cache: CACHE_FEEDS, logger: @logger)
      parser = Parser.new(logger: @logger)
      repositorio = Repositorio.new(ruta_bd: @ruta_bd, logger: @logger)

      begin
        resultados = medios.map { |medio| procesar_medio(medio, cliente, parser, repositorio) }
        imprimir_resumen(resultados, repositorio.total_noticias)
        resultados.any? { |r| r[:estado] != :error } ? 0 : 1
      ensure
        # En ensure y no al final del cuerpo: si algo inesperado aborta la
        # corrida, el cache igual se persiste y la conexion se cierra. Antes se
        # perdian los validadores de los medios que SI habian andado.
        cliente.guardar_cache
        repositorio.cerrar
      end
    end

    private

    def construir_logger
      logger = Logger.new($stdout)
      logger.level = Logger::INFO
      logger.formatter = proc do |severidad, hora, _prog, mensaje|
        "[#{hora.strftime('%H:%M:%S')}] #{severidad.ljust(5)} #{mensaje}\n"
      end
      logger
    end

    def medios_activos
      configuracion = YAML.safe_load_file(@ruta_config)
      (configuracion['medios'] || []).select { |medio| medio['activo'] }
    rescue Errno::ENOENT
      @logger.error("No se encontro #{@ruta_config}")
      []
    rescue Psych::SyntaxError => e
      @logger.error("config/medios.yml tiene un error de sintaxis: #{e.message}")
      []
    end

    # Aisla cada medio: cualquier falla aqui se convierte en un resultado
    # :error y la corrida sigue con el siguiente diario.
    def procesar_medio(medio, cliente, parser, repositorio)
      slug = medio['slug']
      @logger.info("=== #{medio['nombre']} (#{slug})")

      respuesta = cliente.descargar(medio['url_feed'])

      if respuesta[:estado] == :no_modificado
        @logger.info("#{slug}: sin cambios desde la ultima corrida")
        return { slug: slug, estado: :no_modificado, leidas: 0, nuevas: 0, duplicadas: 0 }
      end

      noticias = parser.parsear(respuesta[:cuerpo])
      @logger.info("#{slug}: #{noticias.size} noticias leidas del feed")

      medio_id = repositorio.id_de_medio(
        slug: slug, nombre: medio['nombre'], url_feed: medio['url_feed']
      )
      conteo = repositorio.guardar_lote(medio_id, noticias)
      @logger.info("#{slug}: #{conteo[:nuevas]} nuevas, #{conteo[:duplicadas]} duplicadas")

      { slug: slug, estado: :ok, leidas: noticias.size, **conteo }
    rescue RssClient::ErrorDeDescarga => e
      @logger.error("#{slug}: fallo la descarga -> #{e.message}")
      { slug: slug, estado: :error, motivo: 'descarga', leidas: 0, nuevas: 0, duplicadas: 0 }
    rescue Nokogiri::XML::SyntaxError => e
      @logger.error("#{slug}: XML invalido -> #{e.message}")
      cliente.olvidar(medio['url_feed'])
      { slug: slug, estado: :error, motivo: 'xml', leidas: 0, nuevas: 0, duplicadas: 0 }
    rescue SQLite3::Exception => e
      @logger.error("#{slug}: fallo la escritura en la base -> #{e.message}")
      cliente.olvidar(medio['url_feed'])
      { slug: slug, estado: :error, motivo: 'base de datos', leidas: 0, nuevas: 0, duplicadas: 0 }
    rescue StandardError => e
      # Ultimo recurso. El encabezado de este archivo promete que un diario
      # caido nunca aborta la corrida completa, y con tres clases rescatadas esa
      # promesa no se cumplia: cualquier otra excepcion se llevaba todo.
      @logger.error("#{slug}: error inesperado (#{e.class}) -> #{e.message}")
      cliente.olvidar(medio['url_feed'])
      { slug: slug, estado: :error, motivo: e.class.name, leidas: 0, nuevas: 0, duplicadas: 0 }
    end

    def imprimir_resumen(resultados, total)
      puts
      puts 'RESUMEN DE LA RECOLECCION'
      puts '-' * 62
      printf("%-14s %-15s %8s %8s %11s\n", 'MEDIO', 'ESTADO', 'LEIDAS', 'NUEVAS', 'DUPLICADAS')
      resultados.each do |r|
        printf("%-14s %-15s %8d %8d %11d\n",
               r[:slug], r[:estado], r[:leidas], r[:nuevas], r[:duplicadas])
      end
      puts '-' * 62
      printf("%-14s %-15s %8d %8d %11d\n", 'TOTAL', '',
             resultados.sum { |r| r[:leidas] },
             resultados.sum { |r| r[:nuevas] },
             resultados.sum { |r| r[:duplicadas] })
      puts
      puts "Noticias en la base: #{total}"
      pendientes = resultados.sum { |r| r[:nuevas] }
      puts 'Siguiente paso: python -m backend.pipeline.procesar  (issue #2)' if pendientes.positive?
    end
  end
end

exit(NoticiaEC::Scraper.new.ejecutar) if $PROGRAM_NAME == __FILE__
