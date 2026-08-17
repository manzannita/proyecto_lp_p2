# frozen_string_literal: true

require 'nokogiri'
require 'time'
require 'uri'

module NoticiaEC
  # Convierte el XML de un feed RSS en hashes listos para guardar.
  #
  # Los dos feeds del proyecto no son iguales y el parser tiene que absorber
  # esas diferencias (verificadas contra los feeds reales el 2026-08-16):
  #
  #   El Universo  -> <title> en CDATA, sin <category>, seccion en la ruta URL.
  #   Primicias    -> <title> en texto plano con saltos de linea y sangria
  #                   (hay que hacer strip), con <category>, y el PRIMER item
  #                   es un "Directorio de secciones" cuyo link es la portada:
  #                   no es una noticia y hay que descartarlo.
  #
  # Nokogiri ya resuelve CDATA y entidades HTML con #text, asi que eso no hay
  # que hacerlo a mano.
  class Parser
    # Parametros de tracking que se eliminan antes de calcular el hash, para que
    # la misma nota compartida por dos vias no entre dos veces.
    PARAMETROS_DE_TRACKING = %w[
      utm_source utm_medium utm_campaign utm_term utm_content
      fbclid gclid mc_cid mc_eid ref
    ].freeze

    def initialize(logger:)
      @logger = logger
    end

    # Devuelve un array de hashes:
    #   { titular:, resumen:, url:, categoria_origen:, fecha_publicacion: }
    #
    # Un item malformado se descarta con una advertencia; nunca tumba el feed
    # completo. Un XML invalido si lanza Nokogiri::XML::SyntaxError, que el
    # orquestador rescata para pasar al siguiente medio.
    def parsear(xml)
      documento = Nokogiri::XML(xml) { |config| config.strict.nonet }

      documento.xpath('//item').filter_map do |item|
        begin
          construir(item)
        rescue ItemInvalido => e
          @logger.warn("Item descartado: #{e.message}")
          nil
        end
      end
    end

    # Se expone porque el repositorio necesita la misma normalizacion para
    # calcular el hash de deduplicacion.
    def self.normalizar_url(url)
      uri = URI.parse(url.to_s.strip)
      uri.fragment = nil

      if uri.query
        pares = URI.decode_www_form(uri.query).reject { |clave, _| PARAMETROS_DE_TRACKING.include?(clave) }
        uri.query = pares.empty? ? nil : URI.encode_www_form(pares)
      end

      uri.host = uri.host.downcase.sub(/\Awww\./, '') if uri.host
      uri.to_s
    rescue URI::InvalidURIError
      url.to_s.strip
    end

    private

    class ItemInvalido < StandardError; end

    def construir(item)
      titular = texto(item, 'title')
      url = texto(item, 'link')
      url = texto(item, 'guid') if url.empty?

      raise ItemInvalido, 'sin titular' if titular.empty?
      raise ItemInvalido, 'sin URL' if url.empty?

      url_normalizada = self.class.normalizar_url(url)
      raise ItemInvalido, "no apunta a una nota (#{url})" unless nota?(url_normalizada)

      {
        titular: titular,
        resumen: texto(item, 'description'),
        url: url_normalizada,
        categoria_origen: presencia(texto(item, 'category')),
        fecha_publicacion: fecha(item)
      }
    end

    # Descarta los items de navegacion (el "Directorio de secciones" de
    # Primicias apunta a la portada, sin ruta de articulo).
    def nota?(url)
      uri = URI.parse(url)
      ruta = uri.path.to_s.delete_suffix('/')
      !ruta.empty?
    rescue URI::InvalidURIError
      false
    end

    def texto(item, nombre)
      nodo = item.at_xpath("./#{nombre}")
      # squeeze(' ') colapsa la sangria del XML de Primicias.
      nodo ? nodo.text.to_s.gsub(/\s+/, ' ').strip : ''
    end

    def presencia(valor)
      valor.nil? || valor.empty? ? nil : valor
    end

    # Normaliza pubDate (RFC-822, con zona propia de cada medio) a
    # 'YYYY-MM-DD HH:MM:SS' en UTC, que es el formato que guarda la BD.
    def fecha(item)
      crudo = texto(item, 'pubDate')
      crudo = texto(item, 'dc:date') if crudo.empty?
      raise ItemInvalido, 'sin fecha de publicacion' if crudo.empty?

      begin
        Time.rfc2822(crudo).utc.strftime('%Y-%m-%d %H:%M:%S')
      rescue ArgumentError
        begin
          Time.parse(crudo).utc.strftime('%Y-%m-%d %H:%M:%S')
        rescue ArgumentError
          raise ItemInvalido, "fecha ilegible: '#{crudo}'"
        end
      end
    end
  end
end
