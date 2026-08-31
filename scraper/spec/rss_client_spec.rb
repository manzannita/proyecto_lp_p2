# frozen_string_literal: true

require 'tmpdir'

require_relative 'spec_helper'

RSpec.describe NoticiaEC::RssClient do
  let(:url) { 'https://ejemplo.test/feed.xml' }
  let(:directorio) { Dir.mktmpdir }
  let(:ruta_cache) { File.join(directorio, 'feeds.json') }
  # Reemplaza sleep: los tests no esperan de verdad, pero si registran la espera.
  let(:esperas) { [] }
  let(:cliente) do
    described_class.new(ruta_cache: ruta_cache, logger: logger_mudo,
                        pausa: ->(segundos) { esperas << segundos })
  end

  after { FileUtils.remove_entry(directorio) }

  describe 'descarga exitosa' do
    it 'devuelve el cuerpo del feed' do
      stub_request(:get, url).to_return(status: 200, body: '<rss/>')
      expect(cliente.descargar(url)).to eq({ estado: :ok, cuerpo: '<rss/>' })
    end

    it 'manda un User-Agent identificable' do
      peticion = stub_request(:get, url)
                 .with(headers: { 'User-Agent' => /NoticIA-EC/ })
                 .to_return(status: 200, body: '<rss/>')
      cliente.descargar(url)
      expect(peticion).to have_been_requested
    end
  end

  describe 'reintentos ante fallas de red' do
    it 'reintenta con backoff exponencial y termina bien' do
      stub_request(:get, url)
        .to_raise(Net::OpenTimeout).then
        .to_raise(Errno::ECONNRESET).then
        .to_return(status: 200, body: '<rss/>')

      expect(cliente.descargar(url)[:estado]).to eq(:ok)
      expect(esperas).to eq([1, 2]) # 1s y 2s antes del 2do y 3er intento
    end

    it 'lanza ErrorDeDescarga cuando se agotan los tres intentos' do
      stub_request(:get, url).to_raise(SocketError)

      expect { cliente.descargar(url) }
        .to raise_error(described_class::ErrorDeDescarga, /SocketError/)
      expect(a_request(:get, url)).to have_been_made.times(3)
    end

    it 'no reintenta ante un 404, porque no es un error transitorio' do
      stub_request(:get, url).to_return(status: 404)

      expect { cliente.descargar(url) }
        .to raise_error(described_class::ErrorDeDescarga, /404/)
      expect(a_request(:get, url)).to have_been_made.once
    end

    # Un 503 del CDN o un 429 no dicen que el feed este mal, dicen "volve en un
    # rato". Antes se trataban como definitivos y se perdia la corrida del medio.
    it 'reintenta ante un 503, porque el servidor puede volver' do
      stub_request(:get, url)
        .to_return(status: 503).then
        .to_return(status: 200, body: '<rss/>')

      expect(cliente.descargar(url)).to eq({ estado: :ok, cuerpo: '<rss/>' })
      expect(a_request(:get, url)).to have_been_made.twice
      expect(esperas).to eq([1])
    end

    it 'reintenta ante un 429 y termina en ErrorDeDescarga si no cede' do
      stub_request(:get, url).to_return(status: 429)

      expect { cliente.descargar(url) }
        .to raise_error(described_class::ErrorDeDescarga, /429/)
      expect(a_request(:get, url)).to have_been_made.times(3)
    end
  end

  describe 'GET condicional (optimizacion)' do
    it 'guarda el ETag y lo reenvia como If-None-Match en la siguiente corrida' do
      stub_request(:get, url).to_return(status: 200, body: '<rss/>', headers: { 'ETag' => 'W/"abc"' })
      cliente.descargar(url)
      cliente.guardar_cache

      segundo = described_class.new(ruta_cache: ruta_cache, logger: logger_mudo,
                                    pausa: ->(_) {})
      peticion = stub_request(:get, url)
                 .with(headers: { 'If-None-Match' => 'W/"abc"' })
                 .to_return(status: 304, body: '')

      expect(segundo.descargar(url)).to eq({ estado: :no_modificado, cuerpo: nil })
      expect(peticion).to have_been_requested
    end

    it 'reenvia Last-Modified cuando el servidor no manda ETag' do
      fecha = 'Mon, 17 Aug 2026 01:50:01 GMT'
      stub_request(:get, url).to_return(status: 200, body: '<rss/>',
                                        headers: { 'Last-Modified' => fecha })
      cliente.descargar(url)
      cliente.guardar_cache

      segundo = described_class.new(ruta_cache: ruta_cache, logger: logger_mudo, pausa: ->(_) {})
      peticion = stub_request(:get, url)
                 .with(headers: { 'If-Modified-Since' => fecha })
                 .to_return(status: 304)
      segundo.descargar(url)
      expect(peticion).to have_been_requested
    end

    it 'funciona igual con un feed que no manda validadores (caso Primicias)' do
      stub_request(:get, url).to_return(status: 200, body: '<rss>a</rss>')
      cliente.descargar(url)
      cliente.guardar_cache

      segundo = described_class.new(ruta_cache: ruta_cache, logger: logger_mudo, pausa: ->(_) {})
      stub_request(:get, url).to_return(status: 200, body: '<rss>b</rss>')
      expect(segundo.descargar(url)[:estado]).to eq(:ok)

      # Sin ETag ni Last-Modified no hay nada que cachear: se descarga de nuevo
      # y no se mandan cabeceras condicionales inventadas.
      expect(a_request(:get, url)).to have_been_made.twice
      expect(a_request(:get, url).with(headers: { 'If-None-Match' => /.*/ })).not_to have_been_made
      expect(a_request(:get, url).with(headers: { 'If-Modified-Since' => /.*/ })).not_to have_been_made
    end

    it 'omite el parseo si el cuerpo es identico aunque el servidor responda 200' do
      # Caso real de El Universo: manda ETag pero su CDN no honra If-None-Match.
      stub_request(:get, url).to_return(status: 200, body: '<rss>igual</rss>')
      cliente.descargar(url)
      cliente.guardar_cache

      segundo = described_class.new(ruta_cache: ruta_cache, logger: logger_mudo, pausa: ->(_) {})
      expect(segundo.descargar(url)).to eq({ estado: :no_modificado, cuerpo: nil })
    end

    it 'devuelve el cuerpo cuando el feed si cambio' do
      stub_request(:get, url).to_return(status: 200, body: '<rss>viejo</rss>')
      cliente.descargar(url)
      cliente.guardar_cache

      segundo = described_class.new(ruta_cache: ruta_cache, logger: logger_mudo, pausa: ->(_) {})
      stub_request(:get, url).to_return(status: 200, body: '<rss>nuevo</rss>')
      expect(segundo.descargar(url)).to eq({ estado: :ok, cuerpo: '<rss>nuevo</rss>' })
    end

    it 'no revienta si el archivo de cache esta corrupto' do
      File.write(ruta_cache, 'esto no es json {{{')
      stub_request(:get, url).to_return(status: 200, body: '<rss/>')
      expect(cliente.descargar(url)[:estado]).to eq(:ok)
    end

    # Cubre una perdida de datos silenciosa: el hash del cuerpo se guarda al
    # descargar, asi que si despues falla el parseo o la escritura en la base,
    # la corrida siguiente creeria que el feed "no cambio" y lo saltearia
    # entero. olvidar() es como el orquestador desarma eso.
    it 'olvidar(url) hace que la proxima corrida vuelva a procesar el feed' do
      stub_request(:get, url).to_return(status: 200, body: '<rss>mismo</rss>')
      cliente.descargar(url)
      cliente.olvidar(url)
      cliente.guardar_cache

      segundo = described_class.new(ruta_cache: ruta_cache, logger: logger_mudo, pausa: ->(_) {})
      stub_request(:get, url).to_return(status: 200, body: '<rss>mismo</rss>')

      expect(segundo.descargar(url)).to eq({ estado: :ok, cuerpo: '<rss>mismo</rss>' })
    end
  end
end
