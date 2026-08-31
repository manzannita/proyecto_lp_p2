"""Seguridad basica de la API: header X-API-Key o cookie de sesion.

Todas las rutas /api/* del proyecto llevan @requiere_api_key. La clave sale de
la variable de entorno API_KEY y nunca del codigo.

Se aceptan DOS formas de presentar la clave, y no una sola, porque hay dos
clases de cliente con necesidades opuestas:

  1. Header X-API-Key  -> clientes programaticos (curl, tests, otro backend).
  2. Cookie de sesion  -> el dashboard en el navegador.

El navegador NO puede usar el header: para armarlo, el JavaScript tendria que
conocer la clave, y todo lo que conoce el JavaScript es visible en DevTools y en
el codigo fuente de la pagina. La cookie la escribe el servidor al entregar el
dashboard (ver backend/routes/dashboard.py) con HttpOnly y SameSite=Strict, asi
que el JS nunca la lee y ningun otro sitio puede provocar peticiones
autenticadas. El fetch del dashboard solo manda credentials: "same-origin".

CSRF (avance 3)
---------------
Mientras todos los endpoints fueron GET, la cookie de sesion no abria ningun
riesgo de falsificacion: un GET no cambia estado. POST /api/asistente/preguntar
si consume cuota de un proveedor pago, asi que ahora lleva ademas
@requiere_csrf con el patron de doble envio:

  - Al entregar el dashboard, el servidor emite un token aleatorio en la cookie
    noticia_ec_csrf. Esa cookie NO es HttpOnly a proposito: el JavaScript del
    dashboard tiene que poder leerla para reenviarla.
  - El fetch la copia en el header X-CSRF-Token.
  - El servidor exige que cookie y header coincidan.

Funciona porque un sitio de terceros puede provocar una peticion que arrastre
las cookies del usuario, pero no puede LEER esas cookies (lo impide la
same-origin policy) y por lo tanto no puede construir el header. Es la segunda
linea: la primera sigue siendo SameSite=Strict, que ya impide que la cookie de
sesion viaje en una peticion originada en otro sitio.

Un cliente programatico que se autentica con el header X-API-Key queda exento:
no depende de cookies, asi que no hay nada que falsificar, y exigirle un token
que solo existe en el navegador romperia curl y los tests sin ganar seguridad.
"""

import hmac
import secrets
from functools import wraps

from flask import current_app, jsonify, request

HEADER = "X-API-Key"
COOKIE_SESION = "noticia_ec_sesion"

HEADER_CSRF = "X-CSRF-Token"
COOKIE_CSRF = "noticia_ec_csrf"


def generar_token_csrf() -> str:
    """Token aleatorio de un solo uso por sesion del dashboard."""
    return secrets.token_urlsafe(32)


def _clave_presentada() -> str:
    """Clave que trae la peticion: primero el header, si no la cookie."""
    return request.headers.get(HEADER, "") or request.cookies.get(COOKIE_SESION, "")


def requiere_api_key(vista):
    """Rechaza con 401 cualquier peticion sin una clave valida."""

    @wraps(vista)
    def envoltorio(*args, **kwargs):
        enviada = _clave_presentada()
        esperada = current_app.config["API_KEY"]

        # compare_digest evita filtrar la clave por diferencias de tiempo de
        # respuesta al comparar caracter por caracter. Se comparan BYTES y no
        # str a proposito: con str, compare_digest exige ASCII y una cookie o un
        # header con un caracter acentuado (cosa que controla el cliente) haria
        # estallar un TypeError -> 500 en vez del 401 que corresponde.
        if not enviada or not hmac.compare_digest(
            enviada.encode("utf-8"), esperada.encode("utf-8")
        ):
            return jsonify({"error": "API key invalida o ausente"}), 401

        return vista(*args, **kwargs)

    return envoltorio


def requiere_csrf(vista):
    """Exige el token de doble envio a las peticiones autenticadas por cookie.

    Va SIEMPRE por dentro de @requiere_api_key: primero se decide si el cliente
    tiene permiso, despues si la peticion la origino de verdad el dashboard.
    """

    @wraps(vista)
    def envoltorio(*args, **kwargs):
        # Cliente programatico: se identifico con el header, no con la cookie.
        # Otro sitio no puede fabricar este header sin conocer la API key.
        if request.headers.get(HEADER, ""):
            return vista(*args, **kwargs)

        en_cookie = request.cookies.get(COOKIE_CSRF, "")
        en_header = request.headers.get(HEADER_CSRF, "")

        if not en_cookie or not en_header or not hmac.compare_digest(
            en_cookie.encode("utf-8"), en_header.encode("utf-8")
        ):
            return (
                jsonify(
                    {
                        "error": (
                            "Token CSRF ausente o invalido. Recarga el dashboard "
                            "para renovar la sesion."
                        )
                    }
                ),
                403,
            )

        return vista(*args, **kwargs)

    return envoltorio
