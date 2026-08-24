"""Tests de GET /api/noticias (issue #8)."""

RUTA = "/api/noticias"


# --------------------------------------------------------------------------
# Seguridad
# --------------------------------------------------------------------------

def test_sin_api_key_devuelve_401(cliente):
    respuesta = cliente.get(RUTA)
    assert respuesta.status_code == 401
    assert respuesta.get_json()["error"]


def test_con_api_key_correcta_devuelve_200(cliente_auth):
    respuesta = cliente_auth.get(RUTA)
    assert respuesta.status_code == 200
    datos = respuesta.get_json()
    assert set(datos.keys()) == {"total", "pagina", "por_pagina", "paginas", "noticias"}


def test_intento_de_inyeccion_en_q_no_rompe_la_base(cliente_auth, app):
    respuesta = cliente_auth.get(f"{RUTA}?q=x%' OR 1=1--")
    assert respuesta.status_code in (200, 400)
    if respuesta.status_code == 200:
        assert respuesta.get_json()["noticias"] == []

    with app.app_context():
        from backend.db import consultar_uno

        assert consultar_uno("SELECT COUNT(*) AS n FROM noticias")["n"] > 0


def test_intento_de_inyeccion_en_tema_no_rompe_la_base(cliente_auth, app):
    respuesta = cliente_auth.get(f"{RUTA}?tema=x'; DROP TABLE noticias;--")
    assert respuesta.status_code in (200, 400)
    if respuesta.status_code == 200:
        assert respuesta.get_json()["noticias"] == []

    with app.app_context():
        from backend.db import consultar_uno

        assert consultar_uno("SELECT COUNT(*) AS n FROM noticias")["n"] > 0


# --------------------------------------------------------------------------
# Validacion de parametros
# --------------------------------------------------------------------------

def test_q_muy_corto_devuelve_400(cliente_auth):
    respuesta = cliente_auth.get(f"{RUTA}?q=a")
    assert respuesta.status_code == 400
    assert "q" in respuesta.get_json()["error"]


def test_por_pagina_fuera_de_rango_devuelve_400(cliente_auth):
    respuesta = cliente_auth.get(f"{RUTA}?por_pagina=999")
    assert respuesta.status_code == 400
    assert "por_pagina" in respuesta.get_json()["error"]


def test_pagina_menor_a_uno_devuelve_400(cliente_auth):
    respuesta = cliente_auth.get(f"{RUTA}?pagina=0")
    assert respuesta.status_code == 400
    assert "pagina" in respuesta.get_json()["error"]


def test_fecha_malformada_devuelve_400(cliente_auth):
    respuesta = cliente_auth.get(f"{RUTA}?desde=16-08-2026")
    assert respuesta.status_code == 400


def test_desde_posterior_a_hasta_devuelve_400(cliente_auth):
    respuesta = cliente_auth.get(f"{RUTA}?desde=2026-08-10&hasta=2026-08-01")
    assert respuesta.status_code == 400


def test_tema_inexistente_devuelve_400_con_el_slug(cliente_auth):
    respuesta = cliente_auth.get(f"{RUTA}?tema=tema-que-no-existe")
    assert respuesta.status_code == 400
    assert "tema-que-no-existe" in respuesta.get_json()["error"]


def test_medio_inexistente_devuelve_400_con_el_slug(cliente_auth):
    respuesta = cliente_auth.get(f"{RUTA}?medio=diario-que-no-existe")
    assert respuesta.status_code == 400
    assert "diario-que-no-existe" in respuesta.get_json()["error"]


# --------------------------------------------------------------------------
# Comportamiento
# --------------------------------------------------------------------------

def test_sin_filtros_devuelve_todas_las_noticias_sembradas(cliente_auth):
    datos = cliente_auth.get(RUTA).get_json()
    assert datos["total"] == 28  # 14 de El Universo + 14 de Primicias en la SEMILLA
    assert len(datos["noticias"]) == min(20, datos["total"])


def test_busqueda_sin_coincidencias_devuelve_200_con_lista_vacia(cliente_auth):
    respuesta = cliente_auth.get(f"{RUTA}?q=xilofonoinexistente")
    assert respuesta.status_code == 200
    datos = respuesta.get_json()
    assert datos["total"] == 0
    assert datos["noticias"] == []
    assert datos["paginas"] == 0


def test_busqueda_case_insensitive(cliente_auth):
    minuscula = cliente_auth.get(f"{RUTA}?q=barcelona").get_json()
    mayuscula = cliente_auth.get(f"{RUTA}?q=BARCELONA").get_json()
    assert minuscula["total"] == mayuscula["total"] == 1


def test_busqueda_sin_tildes_en_ambos_sentidos(cliente_auth):
    # El titular sembrado dice "extorsion" (sin tilde); buscar con tilde debe
    # encontrarlo igual, y viceversa.
    sin_tilde = cliente_auth.get(f"{RUTA}?q=extorsion").get_json()
    con_tilde = cliente_auth.get(f"{RUTA}?q=extorsi%C3%B3n").get_json()
    assert sin_tilde["total"] > 0
    assert sin_tilde["total"] == con_tilde["total"]


def test_filtro_por_tema(cliente_auth):
    datos = cliente_auth.get(f"{RUTA}?tema=seguridad").get_json()
    assert datos["total"] == 6
    assert all(fila["tema_slug"] == "seguridad" for fila in datos["noticias"])


def test_filtro_por_medio(cliente_auth):
    datos = cliente_auth.get(f"{RUTA}?medio=primicias").get_json()
    assert all(fila["medio_slug"] == "primicias" for fila in datos["noticias"])


def test_forma_de_una_noticia(cliente_auth):
    datos = cliente_auth.get(f"{RUTA}?tema=seguridad&por_pagina=1").get_json()
    noticia = datos["noticias"][0]
    assert set(noticia.keys()) == {
        "id", "titular", "resumen", "url", "medio", "medio_slug",
        "tema", "tema_slug", "fecha_publicacion",
    }


def test_orden_por_fecha_descendente(cliente_auth):
    datos = cliente_auth.get(f"{RUTA}?por_pagina=50").get_json()
    fechas = [fila["fecha_publicacion"] for fila in datos["noticias"]]
    assert fechas == sorted(fechas, reverse=True)


def test_paginacion_sin_solapamientos_y_paginas_correcto(cliente_auth):
    pagina1 = cliente_auth.get(f"{RUTA}?por_pagina=5&pagina=1").get_json()
    pagina2 = cliente_auth.get(f"{RUTA}?por_pagina=5&pagina=2").get_json()

    ids1 = {fila["id"] for fila in pagina1["noticias"]}
    ids2 = {fila["id"] for fila in pagina2["noticias"]}
    assert ids1.isdisjoint(ids2)

    import math

    assert pagina1["paginas"] == math.ceil(pagina1["total"] / 5)
