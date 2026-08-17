from backend.pipeline.normalizador import normalizar, tokenizar


def test_normalizar_quita_tildes_puntuacion_y_espacios():
    assert normalizar("  ¡Policía, ECONOMÍA!  ") == "policia economia"


def test_normalizar_acepta_nulo():
    assert normalizar(None) == ""


def test_tokenizar_elimina_stopwords():
    assert tokenizar("La policia en el norte") == ["policia", "norte"]


def test_tokenizar_no_modifica_el_archivo_de_stopwords():
    primero = tokenizar("El banco y la inversion")
    segundo = tokenizar("El banco y la inversion")
    assert primero == segundo == ["banco", "inversion"]
