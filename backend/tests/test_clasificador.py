from backend.pipeline.normalizador import normalizar, tokenizar
from backend.pipeline.clasificador import clasificar


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


def test_clasifica_titulares_de_varios_temas():
    casos = {
        "Policia investiga un asesinato": "seguridad",
        "Asamblea debate reforma electoral": "politica",
        "Banco analiza la inflacion": "economia",
        "Hospital inicia vacunacion": "salud",
        "La seleccion gana el partido": "deportes",
        "Alerta por lluvia e inundacion": "clima",
        "ONU convoca cumbre internacional": "internacional",
    }
    for titular, esperado in casos.items():
        assert clasificar(titular, "")[0] == esperado


def test_sin_palabras_clave_es_otros():
    assert clasificar("Festival de arte abre sus puertas", "")[0] == "otros"


def test_titular_pesa_doble():
    slug, score = clasificar("Policia realiza operativo", "Gobierno anuncia cambios")
    assert slug == "seguridad"
    assert score == 2.0


def test_empate_se_resuelve_por_prioridad():
    slug, score = clasificar("Policia informa al gobierno", "")
    assert slug == "seguridad"
    assert score == 2.0
