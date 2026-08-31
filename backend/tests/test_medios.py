def test_catalogo_devuelve_medios_y_totales(cliente_auth):
    respuesta = cliente_auth.get("/api/medios")
    assert respuesta.status_code == 200
    assert respuesta.get_json() == [
        {"id": 1, "nombre": "El Universo", "slug": "el-universo", "total_noticias": 14},
        {"id": 2, "nombre": "Primicias", "slug": "primicias", "total_noticias": 14},
    ]


def test_catalogo_requiere_api_key(cliente):
    respuesta = cliente.get("/api/medios")
    assert respuesta.status_code == 401
    assert respuesta.get_json() == {"error": "API key invalida o ausente"}


def test_comparativa_porcentajes_suman_cien(cliente_auth):
    respuesta = cliente_auth.get("/api/medios/comparativa")
    assert respuesta.status_code == 200
    for medio in respuesta.get_json()["medios"]:
        assert abs(sum(tema["porcentaje"] for tema in medio["temas"]) - 100) <= 0.2


def test_comparativa_calcula_brecha_conocida(cliente_auth):
    """El porcentaje es sobre la AGENDA COMPLETA del medio, no sobre el recorte.

    Con la semilla, cada medio tiene 13 noticias clasificadas: El Universo con 4
    de seguridad y Primicias con 2.

        el-universo  4 / 13 = 30,8 %
        primicias    2 / 13 = 15,4 %
        brecha                15,4 puntos

    Este test afirmaba 38,1, que era el numero que salia de renormalizar sobre
    los temas SELECCIONADOS (4/6 contra 2/7). Ese denominador no correspondia a
    la etiqueta que ve el usuario --"% dentro de la agenda de cada medio"-- y en
    el caso extremo de un solo tema daba 100 %; ver el test de abajo.
    """
    datos = cliente_auth.get(
        "/api/medios/comparativa?temas=seguridad,economia"
    ).get_json()
    brechas = {fila["tema"]: fila for fila in datos["brechas"]}
    assert brechas["seguridad"] == {
        "tema": "seguridad",
        "diferencia_pp": 15.4,
        "prioriza": "el-universo",
    }


def test_un_solo_tema_no_da_cien_por_ciento(cliente_auth):
    """El caso patologico del denominador renormalizado.

    Pidiendo un unico tema, el porcentaje de ese tema era 100 % para cualquier
    medio que tuviera al menos una noticia, porque el denominador era la suma
    del recorte. El frontend lo redactaba como "dedica 100,0 puntos mas a X".
    """
    datos = cliente_auth.get("/api/medios/comparativa?temas=clima").get_json()

    for medio in datos["medios"]:
        for tema in medio["temas"]:
            assert tema["porcentaje"] < 100.0, (
                f"{medio['slug']} informa {tema['porcentaje']}% de su agenda en "
                f"un solo tema"
            )

    for brecha in datos["brechas"]:
        assert brecha["diferencia_pp"] < 100.0


def test_el_periodo_no_inventa_la_fecha_de_hoy(cliente_auth, app):
    """periodo.hasta sale de los datos, no del reloj.

    Antes caia en date.today() cuando no habia filtro, asi que el cabezote del
    dashboard afirmaba que los datos llegaban hasta hoy aunque la ultima
    noticia recolectada fuera de dias antes.
    """
    datos = cliente_auth.get("/api/medios/comparativa").get_json()

    with app.app_context():
        from backend.db import consultar_uno

        ultima = consultar_uno("SELECT MAX(fecha_publicacion) AS f FROM noticias")["f"]

    assert datos["periodo"]["hasta"] == ultima[:10]


def test_comparativa_requiere_api_key(cliente):
    assert cliente.get("/api/medios/comparativa").status_code == 401


def test_comparativa_rechaza_fecha_malformada(cliente_auth):
    assert cliente_auth.get("/api/medios/comparativa?desde=16-08-2026").status_code == 400


def test_comparativa_rechaza_rango_invertido(cliente_auth):
    assert cliente_auth.get(
        "/api/medios/comparativa?desde=2026-08-16&hasta=2026-08-01"
    ).status_code == 400


def test_slug_malicioso_no_ejecuta_sql(cliente_auth, bd_temporal):
    import sqlite3

    ataque = "x%27%3B%20DROP%20TABLE%20noticias%3B--"
    assert cliente_auth.get(f"/api/medios/comparativa?temas={ataque}").status_code == 400
    conexion = sqlite3.connect(bd_temporal)
    try:
        assert conexion.execute("SELECT COUNT(*) FROM noticias").fetchone()[0] == 28
    finally:
        conexion.close()


def test_periodo_sin_datos_devuelve_listas_vacias(cliente_auth):
    respuesta = cliente_auth.get(
        "/api/medios/comparativa?desde=1900-01-01&hasta=1900-01-02"
    )
    assert respuesta.status_code == 200
    assert respuesta.get_json()["medios"] == []
    assert respuesta.get_json()["brechas"] == []
