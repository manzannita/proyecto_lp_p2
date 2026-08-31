"""Tests de la proteccion CSRF del POST del asistente.

El resto de la API es GET y no la necesita: un GET no cambia estado. El POST
del asistente si consume cuota del proveedor del LLM, asi que exige el token de
doble envio cuando el cliente se autentica por cookie. Ver backend/auth.py.
"""

from unittest.mock import patch

from backend.auth import COOKIE_CSRF, COOKIE_SESION

from .conftest import API_KEY

PREGUNTA = {"pregunta": "que paso con la seguridad"}


def _con_cookies(cliente, csrf: str | None = "token-de-prueba"):
    """Simula al dashboard: sesion en cookie, sin header X-API-Key."""
    cliente.set_cookie(COOKIE_SESION, API_KEY)
    if csrf is not None:
        cliente.set_cookie(COOKIE_CSRF, csrf)
    return cliente


def test_el_shell_emite_las_dos_cookies(cliente):
    respuesta = cliente.get("/")
    galletas = respuesta.headers.get_all("Set-Cookie")

    sesion = next(c for c in galletas if c.startswith(f"{COOKIE_SESION}="))
    csrf = next(c for c in galletas if c.startswith(f"{COOKIE_CSRF}="))

    # La de sesion lleva la clave y es inalcanzable desde JavaScript.
    assert "HttpOnly" in sesion
    # La de CSRF tiene que ser legible por el JS para poder reenviarla.
    assert "HttpOnly" not in csrf
    # Ninguna de las dos viaja en peticiones originadas en otro sitio.
    assert "SameSite=Strict" in sesion and "SameSite=Strict" in csrf


def test_el_token_csrf_es_distinto_en_cada_sesion(cliente):
    def token(respuesta):
        galleta = next(
            c for c in respuesta.headers.get_all("Set-Cookie") if c.startswith(COOKIE_CSRF)
        )
        return galleta.split(";")[0].split("=", 1)[1]

    assert token(cliente.get("/")) != token(cliente.get("/"))


def test_el_cliente_programatico_no_necesita_token(cliente_auth):
    """Se autentico con el header X-API-Key: no depende de cookies."""
    with patch("backend.routes.asistente.recuperar_contexto", return_value=[]):
        respuesta = cliente_auth.post("/api/asistente/preguntar", json=PREGUNTA)
    assert respuesta.status_code == 200


def test_el_dashboard_con_token_valido_pasa(cliente):
    _con_cookies(cliente)
    with patch("backend.routes.asistente.recuperar_contexto", return_value=[]):
        respuesta = cliente.post(
            "/api/asistente/preguntar",
            json=PREGUNTA,
            headers={"X-CSRF-Token": "token-de-prueba"},
        )
    assert respuesta.status_code == 200


def test_sin_header_el_post_se_rechaza(cliente):
    """El caso real del ataque: otro sitio arrastra la cookie pero no la puede leer."""
    _con_cookies(cliente)
    respuesta = cliente.post("/api/asistente/preguntar", json=PREGUNTA)

    assert respuesta.status_code == 403
    assert "CSRF" in respuesta.get_json()["error"]


def test_un_token_que_no_coincide_se_rechaza(cliente):
    _con_cookies(cliente, csrf="el-token-de-la-cookie")
    respuesta = cliente.post(
        "/api/asistente/preguntar",
        json=PREGUNTA,
        headers={"X-CSRF-Token": "un-token-inventado"},
    )
    assert respuesta.status_code == 403


def test_sin_cookie_csrf_el_header_solo_no_alcanza(cliente):
    _con_cookies(cliente, csrf=None)
    respuesta = cliente.post(
        "/api/asistente/preguntar",
        json=PREGUNTA,
        headers={"X-CSRF-Token": "un-token-inventado"},
    )
    assert respuesta.status_code == 403


def test_la_api_key_se_valida_antes_que_el_csrf(cliente):
    """Sin credenciales el resultado es 401, no un 403 que revele el mecanismo."""
    cliente.set_cookie(COOKIE_CSRF, "token-de-prueba")
    respuesta = cliente.post(
        "/api/asistente/preguntar",
        json=PREGUNTA,
        headers={"X-CSRF-Token": "token-de-prueba"},
    )
    assert respuesta.status_code == 401


def test_los_get_no_piden_token(cliente):
    """La proteccion es solo del POST: agregarla a los GET no aportaria nada."""
    _con_cookies(cliente, csrf=None)
    assert cliente.get("/api/tendencias/top-temas").status_code == 200
    assert cliente.get("/api/noticias").status_code == 200
