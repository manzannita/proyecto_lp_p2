# frozen_string_literal: true

require 'tmpdir'

require_relative 'spec_helper'

RSpec.describe NoticiaEC::Repositorio do
  let(:directorio) { Dir.mktmpdir }
  let(:ruta_bd) { File.join(directorio, 'prueba.db') }
  let(:schema) { File.read(File.expand_path('../../schema.sql', __dir__)) }
  let(:repositorio) { described_class.new(ruta_bd: ruta_bd, logger: logger_mudo) }

  let(:noticia) do
    {
      titular: 'Operativo policial deja seis detenidos',
      resumen: 'Resumen de la nota',
      url: 'https://primicias.ec/sucesos/operativo-130421/',
      categoria_origen: 'Sucesos',
      fecha_publicacion: '2026-08-16 21:50:37'
    }
  end

  before do
    db = SQLite3::Database.new(ruta_bd)
    db.execute_batch(schema)
    db.close
  end

  after do
    repositorio.cerrar
    FileUtils.remove_entry(directorio)
  end

  def medio_id
    repositorio.id_de_medio(slug: 'primicias', nombre: 'Primicias',
                            url_feed: 'https://www.primicias.ec/rss/home.xml')
  end

  describe '#id_de_medio' do
    it 'resuelve el id de un medio ya sembrado por schema.sql' do
      expect(medio_id).to be_a(Integer)
    end

    it 'es idempotente: no duplica el medio al llamarlo dos veces' do
      primero = medio_id
      expect(medio_id).to eq(primero)

      db = SQLite3::Database.new(ruta_bd)
      total = db.get_first_value("SELECT COUNT(*) FROM medios WHERE slug = 'primicias'")
      db.close
      expect(total).to eq(1)
    end
  end

  describe '#guardar_lote' do
    it 'inserta las noticias nuevas' do
      expect(repositorio.guardar_lote(medio_id, [noticia])).to eq({ nuevas: 1, duplicadas: 0 })
      expect(repositorio.total_noticias).to eq(1)
    end

    it 'inserta con tema_id NULL: clasificar es tarea del pipeline de Python' do
      repositorio.guardar_lote(medio_id, [noticia])

      db = SQLite3::Database.new(ruta_bd)
      tema = db.get_first_value('SELECT tema_id FROM noticias LIMIT 1')
      db.close
      expect(tema).to be_nil
    end

    it 'no crea una segunda fila al reinsertar la misma URL' do
      repositorio.guardar_lote(medio_id, [noticia])
      segundo = repositorio.guardar_lote(medio_id, [noticia])

      expect(segundo).to eq({ nuevas: 0, duplicadas: 1 })
      expect(repositorio.total_noticias).to eq(1)
    end

    it 'trata como duplicada la misma nota con parametros de tracking distintos' do
      repositorio.guardar_lote(medio_id, [noticia])

      con_tracking = noticia.merge(url: "#{noticia[:url]}?utm_source=facebook")
      expect(repositorio.guardar_lote(medio_id, [con_tracking])[:nuevas]).to eq(0)
      expect(repositorio.total_noticias).to eq(1)
    end

    it 'deduplica dentro del mismo lote' do
      resultado = repositorio.guardar_lote(medio_id, [noticia, noticia.dup])
      expect(resultado).to eq({ nuevas: 1, duplicadas: 1 })
    end

    it 'devuelve ceros con un lote vacio sin tocar la base' do
      expect(repositorio.guardar_lote(medio_id, [])).to eq({ nuevas: 0, duplicadas: 0 })
    end

    it 'hace ROLLBACK del lote completo si una fila falla a mitad' do
      buena = noticia
      # titular NOT NULL: esta fila viola la restriccion y aborta la transaccion.
      mala = noticia.merge(url: 'https://primicias.ec/otra/', titular: nil)

      expect { repositorio.guardar_lote(medio_id, [buena, mala]) }.to raise_error(SQLite3::Exception)

      # Ni siquiera la fila buena quedo: la transaccion es todo o nada.
      expect(repositorio.total_noticias).to eq(0)
    end
  end

  describe '.hash_de_url' do
    it 'produce el mismo hash para variantes equivalentes de la misma URL' do
      a = described_class.hash_de_url('https://www.primicias.ec/nota/#foto')
      b = described_class.hash_de_url('https://primicias.ec/nota/?utm_campaign=x')
      expect(a).to eq(b)
    end

    it 'produce hashes distintos para notas distintas' do
      a = described_class.hash_de_url('https://primicias.ec/nota-1/')
      b = described_class.hash_de_url('https://primicias.ec/nota-2/')
      expect(a).not_to eq(b)
    end
  end
end
