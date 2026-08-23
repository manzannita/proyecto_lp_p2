"""Pruebas del dashboard web y de la sesion por cookie (issue #6).

Lo que se protege aqui es la decision de seguridad del avance 2: el navegador
se autentica con una cookie HttpOnly que pone el servidor, y la API key NO
aparece en ninguna parte del frontend. Si alguien "simplifica" eso metiendo la
clave en el HTML o en el JavaScript, estos tests fallan.
"""

from backend.auth import COOKIE_SESION
from backend.tests.conftest import API_KEY

RUTA_PROTEGIDA = "/api/tendencias/top-temas"


def _cookies_de(respuesta) -> str:
    """Todas las cabeceras Set-Cookie de la respuesta, concatenadas."""
    return " | ".join(respuesta.headers.getlist("Set-Cookie"))


# ---------------------------------------------------------------------------
# El shell del dashboard
# ---------------------------------------------------------------------------


def test_raiz_entrega_el_html_del_dashboard(cliente):
    respuesta = cliente.get("/")

    assert respuesta.status_code == 200
    assert "text/html" in respuesta.headers["Content-Type"]
    assert b"NoticIA EC" in respuesta.data
    # Las cuatro secciones del contrato de vistas tienen que estar presentes:
    # los issues #7 y #8 montan sus vistas dentro de ellas.
    for identificador in (
        b'id="vista-tendencias"',
        b'id="vista-comparativa"',
        b'id="vista-series"',
        b'id="vista-buscador"',
    ):
        assert identificador in respuesta.data


def test_la_api_key_no_viaja_en_el_html(cliente):
    """La clave no se inyecta en la pagina: para eso existe la cookie."""
    respuesta = cliente.get("/")

    assert API_KEY.encode() not in respuesta.data


def test_la_raiz_no_se_cachea(cliente):
    """Si el navegador cachea el shell, no vuelve a pasar por aqui y la cookie
    nunca se renueva: la sesion moriria sin explicacion."""
    respuesta = cliente.get("/")

    assert respuesta.headers["Cache-Control"] == "no-store"


# ---------------------------------------------------------------------------
# La cookie de sesion
# ---------------------------------------------------------------------------


def test_la_raiz_setea_la_cookie_httponly_y_samesite_strict(cliente):
    respuesta = cliente.get("/")
    cookies = _cookies_de(respuesta)

    assert COOKIE_SESION in cookies
    # HttpOnly: inalcanzable desde JavaScript, asi que un XSS no la exfiltra.
    assert "HttpOnly" in cookies
    # SameSite=Strict: ningun otro sitio puede provocar peticiones autenticadas.
    assert "SameSite=Strict" in cookies


def test_la_cookie_sola_autentica_la_api(cliente):
    """El navegador nunca manda el header: solo tiene la cookie."""
    cliente.get("/")  # el servidor deja la cookie en el cliente de prueba

    respuesta = cliente.get(RUTA_PROTEGIDA)

    assert respuesta.status_code == 200
    assert "temas" in respuesta.get_json()


def test_sin_cookie_ni_header_la_api_responde_401(cliente):
    respuesta = cliente.get(RUTA_PROTEGIDA)

    assert respuesta.status_code == 401
    assert respuesta.get_json() == {"error": "API key invalida o ausente"}


def test_una_cookie_invalida_no_autentica(cliente):
    cliente.set_cookie(COOKIE_SESION, "clave-que-no-es")

    respuesta = cliente.get(RUTA_PROTEGIDA)

    assert respuesta.status_code == 401


def test_el_header_sigue_funcionando_para_clientes_programaticos(cliente_auth):
    """curl, los tests y cualquier otro backend siguen usando X-API-Key."""
    respuesta = cliente_auth.get(RUTA_PROTEGIDA)

    assert respuesta.status_code == 200


def test_una_clave_con_acentos_da_401_y_no_500(cliente):
    """hmac.compare_digest sobre str exige ASCII y explotaria con un TypeError.
    La clave la controla el cliente, asi que un caracter raro tiene que dar
    401, no un error interno."""
    respuesta = cliente.get(RUTA_PROTEGIDA, headers={"X-API-Key": "clavé-con-acento"})

    assert respuesta.status_code == 401


# ---------------------------------------------------------------------------
# Archivos estaticos
# ---------------------------------------------------------------------------


def test_sirve_los_estaticos_del_dashboard(cliente):
    respuesta = cliente.get("/static-dashboard/js/api.js")

    assert respuesta.status_code == 200
    assert b"obtenerTopTemas" in respuesta.data


def test_los_estaticos_no_dejan_salir_del_directorio_del_dashboard(cliente):
    """safe_join tiene que bloquear cualquier intento de leer el .env u otro
    archivo del repositorio a traves de la ruta de estaticos."""
    for intento in (
        "/static-dashboard/../../.env",
        "/static-dashboard/..%2f..%2f.env",
        "/static-dashboard/....//....//.env",
    ):
        respuesta = cliente.get(intento)

        assert respuesta.status_code != 200, intento
        assert API_KEY.encode() not in respuesta.data, intento


# ---------------------------------------------------------------------------
# Regresion: la sonda sigue abierta
# ---------------------------------------------------------------------------


def test_health_sigue_sin_autenticacion(cliente):
    respuesta = cliente.get("/health")

    assert respuesta.status_code == 200
    assert respuesta.get_json() == {"estado": "ok"}
