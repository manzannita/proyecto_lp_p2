# frozen_string_literal: true

require_relative 'spec_helper'

RSpec.describe NoticiaEC::Parser do
  subject(:parser) { described_class.new(logger: logger_mudo) }

  describe 'feed de El Universo' do
    let(:noticias) { parser.parsear(fixture('el_universo.xml')) }

    it 'extrae solo los items validos' do
      # 4 items en el fixture: 2 validos, 1 sin fecha, 1 sin titular.
      expect(noticias.size).to eq(2)
    end

    it 'resuelve el CDATA del titular' do
      expect(noticias.first[:titular]).to eq('Operativo policial deja seis detenidos en Duran')
    end

    it 'convierte pubDate a UTC en el formato de la base' do
      expect(noticias.first[:fecha_publicacion]).to eq('2026-08-17 01:17:49')
    end

    it 'convierte una fecha con offset -0500 a UTC' do
      expect(noticias.last[:fecha_publicacion]).to eq('2026-08-17 01:05:00')
    end

    it 'deja categoria_origen en nil cuando el feed no trae <category>' do
      expect(noticias.first[:categoria_origen]).to be_nil
    end

    it 'descarta los items sin fecha o sin titular en vez de reventar' do
      titulares = noticias.map { |n| n[:titular] }
      expect(titulares).not_to include('Item sin fecha que debe descartarse')
    end
  end

  describe 'feed de Primicias' do
    let(:noticias) { parser.parsear(fixture('primicias.xml')) }

    it 'descarta el item "Directorio de secciones" que apunta a la portada' do
      expect(noticias.size).to eq(2)
      expect(noticias.map { |n| n[:titular] }).not_to include('Directorio de secciones')
    end

    it 'limpia la sangria y los saltos de linea del titular' do
      expect(noticias.first[:titular]).to eq('Incendio en Riobamba consumio 2.000 metros cuadrados')
    end

    it 'desescapa las entidades HTML del resumen' do
      expect(noticias.first[:resumen]).to start_with('"Un vehiculo que bloquea el paso')
    end

    it 'aprovecha el <category> cuando el feed lo trae' do
      expect(noticias.map { |n| n[:categoria_origen] }).to eq(%w[Sucesos Economia])
    end
  end

  describe '.normalizar_url' do
    it 'elimina los parametros de tracking' do
      url = 'https://eluniverso.com/nota/?utm_source=twitter&utm_medium=social&id=5'
      expect(described_class.normalizar_url(url)).to eq('https://eluniverso.com/nota/?id=5')
    end

    it 'elimina el fragmento' do
      expect(described_class.normalizar_url('https://primicias.ec/nota/#comentarios'))
        .to eq('https://primicias.ec/nota/')
    end

    it 'quita el www para que las dos formas de la misma nota colisionen' do
      expect(described_class.normalizar_url('https://www.primicias.ec/nota/'))
        .to eq(described_class.normalizar_url('https://primicias.ec/nota/'))
    end

    it 'deja intacta una URL que ya esta limpia' do
      url = 'https://www.primicias.ec/sucesos/incendio-130421/'
      expect(described_class.normalizar_url(url)).to eq('https://primicias.ec/sucesos/incendio-130421/')
    end
  end

  describe 'XML invalido' do
    it 'lanza Nokogiri::XML::SyntaxError para que el orquestador lo aisle' do
      expect { parser.parsear('<rss><channel><item>roto') }
        .to raise_error(Nokogiri::XML::SyntaxError)
    end
  end
end
