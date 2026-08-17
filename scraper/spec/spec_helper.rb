# frozen_string_literal: true

require 'logger'
require 'webmock/rspec'

require_relative '../lib/rss_client'
require_relative '../lib/parser'
require_relative '../lib/repositorio'

# Ningun test toca la red de verdad.
WebMock.disable_net_connect!(allow_localhost: false)

RSpec.configure do |config|
  config.expect_with(:rspec) { |c| c.syntax = :expect }
  config.disable_monkey_patching!
  config.order = :random
end

# Logger silencioso: los tests no deben ensuciar la salida.
def logger_mudo
  Logger.new(File::NULL)
end

def fixture(nombre)
  File.read(File.join(__dir__, 'fixtures', nombre))
end
