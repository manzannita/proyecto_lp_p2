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
    datos = cliente_auth.get(
        "/api/medios/comparativa?temas=seguridad,economia"
    ).get_json()
    brechas = {fila["tema"]: fila for fila in datos["brechas"]}
    assert brechas["seguridad"] == {
        "tema": "seguridad",
        "diferencia_pp": 38.1,
        "prioriza": "el-universo",
    }


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
