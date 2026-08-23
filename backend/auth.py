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

Nota para el avance 3: los endpoints de hoy son todos GET. Cuando se conecte
POST /api/asistente/preguntar desde el navegador habra que agregarle un token
CSRF o dejar ese POST solo con el header.
"""

import hmac
from functools import wraps

from flask import current_app, jsonify, request

HEADER = "X-API-Key"
COOKIE_SESION = "noticia_ec_sesion"


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
