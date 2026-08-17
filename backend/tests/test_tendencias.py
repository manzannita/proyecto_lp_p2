"""Tests de GET /api/tendencias/top-temas (issue #1)."""

RUTA = "/api/tendencias/top-temas"


# --------------------------------------------------------------------------
# Seguridad
# --------------------------------------------------------------------------

def test_sin_api_key_devuelve_401(cliente):
    respuesta = cliente.get(RUTA)
    assert respuesta.status_code == 401
    assert respuesta.get_json()["error"]


def test_con_api_key_incorrecta_devuelve_401(cliente):
    respuesta = cliente.get(RUTA, headers={"X-API-Key": "clave-equivocada"})
    assert respuesta.status_code == 401


def test_con_api_key_correcta_devuelve_200(cliente_auth):
    assert cliente_auth.get(RUTA).status_code == 200


# --------------------------------------------------------------------------
# Comportamiento
# --------------------------------------------------------------------------

def test_devuelve_cinco_temas_por_defecto(cliente_auth):
    datos = cliente_auth.get(RUTA).get_json()
    assert datos["limite"] == 5
    assert len(datos["temas"]) == 5


def test_ranking_ordenado_de_mayor_a_menor(cliente_auth):
    temas = cliente_auth.get(RUTA).get_json()["temas"]
    totales = [tema["total"] for tema in temas]
    assert totales == sorted(totales, reverse=True)


def test_top_temas_es_el_esperado_sobre_los_datos_sembrados(cliente_auth):
    """Con la semilla de conftest: seguridad=6, economia=7, politica=5."""
    datos = cliente_auth.get(f"{RUTA}?limite=3").get_json()
    ranking = {tema["slug"]: tema["total"] for tema in datos["temas"]}
    assert ranking["economia"] == 7
    assert ranking["seguridad"] == 6
    assert ranking["politica"] == 5


def test_excluye_las_no_clasificadas_pero_las_reporta(cliente_auth):
    datos = cliente_auth.get(f"{RUTA}?limite=50").get_json()
    assert datos["sin_clasificar"] == 2
    assert datos["total_noticias"] == datos["clasificadas"] + datos["sin_clasificar"]
    # Ningun tema del ranking puede venir de una noticia sin clasificar.
    assert sum(t["total"] for t in datos["temas"]) == datos["clasificadas"]


def test_porcentajes_suman_aproximadamente_cien(cliente_auth):
    temas = cliente_auth.get(f"{RUTA}?limite=50").get_json()["temas"]
    assert abs(sum(tema["porcentaje"] for tema in temas) - 100) < 0.5


def test_filtro_por_medio(cliente_auth):
    universo = cliente_auth.get(f"{RUTA}?medio=el-universo&limite=50").get_json()
    primicias = cliente_auth.get(f"{RUTA}?medio=primicias&limite=50").get_json()
    todos = cliente_auth.get(f"{RUTA}?limite=50").get_json()

    assert universo["medio"] == "el-universo"
    assert universo["total_noticias"] + primicias["total_noticias"] == todos["total_noticias"]
    # El Universo tiene mas seguridad; Primicias mas economia.
    assert universo["temas"][0]["slug"] == "seguridad"
    assert primicias["temas"][0]["slug"] == "economia"


def test_filtro_por_rango_de_fechas_reduce_el_total(cliente_auth):
    todos = cliente_auth.get(RUTA).get_json()["total_noticias"]
    recientes = cliente_auth.get(f"{RUTA}?desde=1900-01-01&hasta=1900-12-31").get_json()
    assert recientes["total_noticias"] == 0
    assert recientes["temas"] == []
    assert todos > 0


def test_periodo_vacio_devuelve_200_no_404(cliente_auth):
    """Sin datos en el rango la respuesta es 200 con lista vacia."""
    respuesta = cliente_auth.get(f"{RUTA}?desde=1900-01-01&hasta=1900-12-31")
    assert respuesta.status_code == 200
    assert respuesta.get_json()["temas"] == []


# --------------------------------------------------------------------------
# Validacion de parametros
# --------------------------------------------------------------------------

def test_fecha_malformada_devuelve_400(cliente_auth):
    respuesta = cliente_auth.get(f"{RUTA}?desde=16-08-2026")
    assert respuesta.status_code == 400
    assert "desde" in respuesta.get_json()["error"]


def test_desde_posterior_a_hasta_devuelve_400(cliente_auth):
    respuesta = cliente_auth.get(f"{RUTA}?desde=2026-08-10&hasta=2026-08-01")
    assert respuesta.status_code == 400


def test_limite_no_numerico_devuelve_400(cliente_auth):
    assert cliente_auth.get(f"{RUTA}?limite=cinco").status_code == 400


def test_limite_fuera_de_rango_devuelve_400(cliente_auth):
    assert cliente_auth.get(f"{RUTA}?limite=0").status_code == 400
    assert cliente_auth.get(f"{RUTA}?limite=999").status_code == 400


def test_medio_inexistente_devuelve_400(cliente_auth):
    respuesta = cliente_auth.get(f"{RUTA}?medio=diario-que-no-existe")
    assert respuesta.status_code == 400


def test_intento_de_inyeccion_sql_no_rompe_la_base(cliente_auth, app):
    """El parametro va como placeholder, no concatenado."""
    respuesta = cliente_auth.get(f"{RUTA}?medio=x'; DROP TABLE noticias;--")
    assert respuesta.status_code == 400

    # La tabla sigue existiendo y con datos.
    with app.app_context():
        from backend.db import consultar_uno

        assert consultar_uno("SELECT COUNT(*) AS n FROM noticias")["n"] > 0


# --------------------------------------------------------------------------
# Sonda
# --------------------------------------------------------------------------

def test_health_no_requiere_api_key(cliente):
    respuesta = cliente.get("/health")
    assert respuesta.status_code == 200
    assert respuesta.get_json()["estado"] == "ok"
