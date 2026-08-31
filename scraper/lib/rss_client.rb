# frozen_string_literal: true

require 'httparty'
require 'json'
require 'fileutils'
require 'digest'

module NoticiaEC
  # Descarga feeds RSS con HTTParty.
  #
  # Dos cosas que hace y conviene no perder al tocar esta clase:
  #
  #   1. Reintentos con backoff exponencial (1s, 2s, 4s) ante fallas de red.
  #      Cada excepcion se rescata de forma explicita: nada de `rescue => e`.
  #
  #   2. Evitar trabajo cuando el feed no cambio, en dos niveles:
  #
  #      a) GET condicional. Guarda el ETag / Last-Modified de cada feed en
  #         .cache/feeds.json y los reenvia como If-None-Match /
  #         If-Modified-Since. Si el servidor responde 304 nos ahorramos hasta
  #         la descarga.
  #
  #      b) Hash del cuerpo (fallback). Verificado el 2026-08-16: Primicias no
  #         manda validadores, y El Universo los manda pero su CDN NO honra el
  #         If-None-Match (responde 200 con el mismo ETag). O sea que en la
  #         practica hoy ningun feed devuelve 304. Por eso se guarda tambien el
  #         SHA-256 del cuerpo: si el XML descargado es identico al de la
  #         corrida anterior, se omite el parseo y la escritura en la base, que
  #         es donde esta el costo real.
  #
  #      El nivel (a) se mantiene porque es correcto y gratis: el dia que el
  #      CDN empiece a honrarlo, nos ahorramos ademas la transferencia.
  class RssClient
    # Excepcion propia: agrupa cualquier falla de red ya agotados los reintentos.
    class ErrorDeDescarga < StandardError; end

    # Respuesta HTTP que si vale la pena reintentar: un 503 del CDN o un 429 no
    # dicen que el feed este mal, dicen "volve en un rato". Se distingue de
    # ErrorDeDescarga --que es definitivo-- para que entre en el backoff.
    class ErrorTransitorio < StandardError; end

    # Errores transitorios que justifican reintentar.
    ERRORES_REINTENTABLES = [
      ErrorTransitorio,
      HTTParty::Error,
      Net::OpenTimeout,
      Net::ReadTimeout,
      SocketError,
      Errno::ECONNREFUSED,
      Errno::ECONNRESET,
      Errno::EHOSTUNREACH,
      OpenSSL::SSL::SSLError,
      Zlib::BufError
    ].freeze

    USER_AGENT = 'NoticIA-EC/1.0 (proyecto academico ESPOL; +https://github.com/manzannita/proyecto_lp_p2)'
    TIMEOUT_SEGUNDOS = 10
    INTENTOS_MAXIMOS = 3

    def initialize(ruta_cache:, logger:, intentos: INTENTOS_MAXIMOS, pausa: method(:sleep))
      @ruta_cache = ruta_cache
      @logger = logger
      @intentos = intentos
      @pausa = pausa # inyectable para que los tests no duerman de verdad
      @cache = cargar_cache
    end

    # Devuelve:
    #   { estado: :ok,             cuerpo: "<xml...>" }
    #   { estado: :no_modificado,  cuerpo: nil }
    # o lanza ErrorDeDescarga si se agotaron los intentos.
    def descargar(url)
      ultimo_error = nil

      1.upto(@intentos) do |intento|
        begin
          respuesta = HTTParty.get(url, headers: cabeceras(url), timeout: TIMEOUT_SEGUNDOS,
                                        follow_redirects: true)
          return interpretar(url, respuesta)
        rescue *ERRORES_REINTENTABLES => e
          ultimo_error = e
          if intento < @intentos
            espera = 2**(intento - 1) # 1s, 2s, 4s
            @logger.warn("Intento #{intento}/#{@intentos} fallo (#{e.class}: #{e.message}). " \
                         "Reintentando en #{espera}s...")
            @pausa.call(espera)
          else
            @logger.error("Agotados los #{@intentos} intentos para #{url} (#{e.class}: #{e.message})")
          end
        end
      end

      raise ErrorDeDescarga, "No se pudo descargar #{url}: #{ultimo_error.class}: #{ultimo_error.message}"
    end

    # Descarta lo recordado de un feed cuyo procesamiento fallo despues de la
    # descarga.
    #
    # Sin esto habia perdida de datos silenciosa: el hash del cuerpo se guardaba
    # al descargar, asi que si despues fallaba el parseo o la escritura en la
    # base, la corrida siguiente veia el mismo XML, calculaba el mismo hash,
    # creia que "no cambio" y se salteaba el feed entero. Esas noticias no se
    # recuperaban nunca, hasta que el medio publicara algo nuevo.
    def olvidar(url)
      @cache.delete(url)
    end

    # Persiste el cache de validadores. Se llama una vez al final de la corrida.
    def guardar_cache
      FileUtils.mkdir_p(File.dirname(@ruta_cache))
      File.write(@ruta_cache, JSON.pretty_generate(@cache))
    rescue SystemCallError => e
      # Que no se pueda escribir el cache no es motivo para tumbar la corrida:
      # solo significa que la proxima vez no habra 304.
      @logger.warn("No se pudo guardar el cache de feeds: #{e.message}")
    end

    private

    def cabeceras(url)
      cabeceras = { 'User-Agent' => USER_AGENT, 'Accept' => 'application/rss+xml, application/xml, text/xml' }
      validadores = @cache[url]
      return cabeceras unless validadores

      cabeceras['If-None-Match'] = validadores['etag'] if validadores['etag']
      cabeceras['If-Modified-Since'] = validadores['last_modified'] if validadores['last_modified']
      cabeceras
    end

    def interpretar(url, respuesta)
      case respuesta.code
      when 304
        @logger.info('304 Not Modified: el feed no cambio, se omite el parseo')
        { estado: :no_modificado, cuerpo: nil }
      when 200
        cuerpo = respuesta.body.to_s
        hash_nuevo = Digest::SHA256.hexdigest(cuerpo)
        sin_cambios = @cache.dig(url, 'hash_cuerpo') == hash_nuevo

        recordar_validadores(url, respuesta, hash_nuevo)

        if sin_cambios
          @logger.info('El servidor respondio 200 pero el XML es identico al de la ' \
                       'corrida anterior: se omite el parseo')
          { estado: :no_modificado, cuerpo: nil }
        else
          { estado: :ok, cuerpo: cuerpo }
        end
      when 429, 500..599
        # El servidor esta caido o nos esta frenando: se reintenta con backoff.
        raise ErrorTransitorio, "#{url} respondio HTTP #{respuesta.code}"
      when 400..499
        # Un 404 o un 403 no se reintentan: el feed se movio o nos bloquearon,
        # y repetir la misma peticion no lo va a cambiar.
        raise ErrorDeDescarga, "#{url} respondio HTTP #{respuesta.code}"
      else
        raise ErrorDeDescarga, "#{url} respondio un codigo inesperado: #{respuesta.code}"
      end
    end

    def recordar_validadores(url, respuesta, hash_cuerpo)
      @cache[url] = {
        'etag' => respuesta.headers['etag'],
        'last_modified' => respuesta.headers['last-modified'],
        'hash_cuerpo' => hash_cuerpo
      }.compact
    end

    def cargar_cache
      return {} unless File.exist?(@ruta_cache)

      JSON.parse(File.read(@ruta_cache))
    rescue JSON::ParserError, SystemCallError => e
      @logger.warn("Cache de feeds ilegible (#{e.message}), se empieza de cero")
      {}
    end
  end
end
