"""Tests de GET /api/tendencias/series-semanales (issue #3)."""

from datetime import date, timedelta

RUTA = "/api/tendencias/series-semanales"


# --------------------------------------------------------------------------
# Seguridad
# --------------------------------------------------------------------------

def test_sin_api_key_devuelve_401(cliente):
    respuesta = cliente.get(f"{RUTA}?tema=seguridad")
    assert respuesta.status_code == 401
    assert respuesta.get_json()["error"]


def test_con_api_key_correcta_devuelve_200(cliente_auth):
    assert cliente_auth.get(f"{RUTA}?tema=seguridad").status_code == 200


# --------------------------------------------------------------------------
# Validacion de parametros
# --------------------------------------------------------------------------

def test_falta_tema_devuelve_400(cliente_auth):
    respuesta = cliente_auth.get(RUTA)
    assert respuesta.status_code == 400
    assert "tema" in respuesta.get_json()["error"]


def test_tema_inexistente_devuelve_404(cliente_auth):
    respuesta = cliente_auth.get(f"{RUTA}?tema=tema-que-no-existe")
    assert respuesta.status_code == 404


def test_fecha_malformada_devuelve_400(cliente_auth):
    respuesta = cliente_auth.get(f"{RUTA}?tema=seguridad&desde=16-08-2026")
    assert respuesta.status_code == 400


def test_desde_posterior_a_hasta_devuelve_400(cliente_auth):
    respuesta = cliente_auth.get(
        f"{RUTA}?tema=seguridad&desde=2026-08-10&hasta=2026-08-01"
    )
    assert respuesta.status_code == 400


def test_medio_inexistente_devuelve_400(cliente_auth):
    respuesta = cliente_auth.get(f"{RUTA}?tema=seguridad&medio=diario-que-no-existe")
    assert respuesta.status_code == 400


def test_intento_de_inyeccion_sql_no_rompe_la_base(cliente_auth, app):
    respuesta = cliente_auth.get(f"{RUTA}?tema=x'; DROP TABLE noticias;--")
    assert respuesta.status_code == 404

    with app.app_context():
        from backend.db import consultar_uno

        assert consultar_uno("SELECT COUNT(*) AS n FROM noticias")["n"] > 0


# --------------------------------------------------------------------------
# Comportamiento
# --------------------------------------------------------------------------

def test_tema_sin_ninguna_noticia_devuelve_serie_vacia(cliente_auth):
    """'otros' esta en el catalogo de temas pero no tiene noticias sembradas."""
    datos = cliente_auth.get(f"{RUTA}?tema=otros").get_json()
    assert datos["serie"] == []
    assert datos["resumen"]["total_periodo"] == 0
    assert datos["resumen"]["promedio_semanal"] == 0.0
    assert datos["resumen"]["semana_pico"] is None
    assert datos["resumen"]["variacion_ultima_semana_pct"] is None


def test_periodo_sin_noticias_en_el_rango_devuelve_serie_vacia(cliente_auth):
    respuesta = cliente_auth.get(
        f"{RUTA}?tema=seguridad&desde=1900-01-01&hasta=1900-12-31"
    )
    assert respuesta.status_code == 200
    assert respuesta.get_json()["serie"] == []


def test_total_periodo_por_defecto_coincide_con_los_datos_sembrados(cliente_auth):
    """El Universo (1,3,9,16 dias) + Primicias (1,13 dias) = 6 noticias de seguridad."""
    datos = cliente_auth.get(f"{RUTA}?tema=seguridad").get_json()
    assert datos["tema"] == "seguridad"
    assert datos["granularidad"] == "semana"
    assert datos["resumen"]["total_periodo"] == 6
    assert sum(semana["total"] for semana in datos["serie"]) == 6


def test_filtro_por_medio(cliente_auth):
    universo = cliente_auth.get(f"{RUTA}?tema=seguridad&medio=el-universo").get_json()
    primicias = cliente_auth.get(f"{RUTA}?tema=seguridad&medio=primicias").get_json()
    assert universo["resumen"]["total_periodo"] == 4
    assert primicias["resumen"]["total_periodo"] == 2


def test_serie_continua_con_semanas_en_cero(cliente_auth):
    """Con un rango amplio deben aparecer semanas sin noticias en 0, no huecos."""
    desde = (date.today() - timedelta(days=27)).isoformat()
    datos = cliente_auth.get(f"{RUTA}?tema=seguridad&desde={desde}").get_json()
    serie = datos["serie"]

    totales = [semana["total"] for semana in serie]
    assert any(total == 0 for total in totales)

    fechas = [date.fromisoformat(semana["semana_inicio"]) for semana in serie]
    for anterior, siguiente in zip(fechas, fechas[1:]):
        assert (siguiente - anterior).days == 7

    for semana in serie:
        assert date.fromisoformat(semana["semana_inicio"]).weekday() == 0  # lunes


def test_semana_iso_tiene_el_formato_esperado(cliente_auth):
    datos = cliente_auth.get(f"{RUTA}?tema=seguridad").get_json()
    for semana in datos["serie"]:
        anio, numero_semana = semana["semana_iso"].split("-W")
        assert len(anio) == 4
        assert 1 <= int(numero_semana) <= 53


def test_semana_pico_es_la_de_mayor_total(cliente_auth):
    datos = cliente_auth.get(f"{RUTA}?tema=seguridad").get_json()
    serie = datos["serie"]
    pico_esperado = max(serie, key=lambda semana: semana["total"])["semana_iso"]
    assert datos["resumen"]["semana_pico"] == pico_esperado


def test_promedio_semanal_es_total_entre_numero_de_semanas(cliente_auth):
    datos = cliente_auth.get(f"{RUTA}?tema=seguridad").get_json()
    resumen = datos["resumen"]
    esperado = round(resumen["total_periodo"] / len(datos["serie"]), 1)
    assert resumen["promedio_semanal"] == esperado
