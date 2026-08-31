"""Sirve el dashboard web y abre la sesion del navegador.

Rutas:
    GET /                            -> shell del dashboard (index.html) + cookie
    GET /static-dashboard/<archivo>  -> css, js y vendor del dashboard

El dashboard se sirve desde el MISMO origen que la API a proposito: asi no hay
CORS que configurar y la cookie de sesion viaja sola en cada fetch.

Por que una cookie y no la clave en el JavaScript: ver backend/auth.py.
"""

from pathlib import Path

from flask import Blueprint, current_app, make_response, request, send_from_directory

from backend.auth import COOKIE_CSRF, COOKIE_SESION, generar_token_csrf

dashboard_bp = Blueprint("dashboard", __name__)

RAIZ_DASHBOARD = Path(__file__).resolve().parent.parent.parent / "dashboard"

# Ocho horas: cubre una jornada de trabajo sin dejar la sesion abierta para
# siempre. Al vencer, basta recargar la pagina para que el servidor la renueve.
DURACION_SESION_SEG = 8 * 60 * 60


@dashboard_bp.get("/")
def shell():
    """Entrega el HTML del dashboard y deja la clave en una cookie HttpOnly."""
    respuesta = make_response(send_from_directory(RAIZ_DASHBOARD, "index.html"))

    respuesta.set_cookie(
        COOKIE_SESION,
        current_app.config["API_KEY"],
        max_age=DURACION_SESION_SEG,
        httponly=True,       # inalcanzable desde JavaScript: un XSS no la exfiltra
        samesite="Strict",   # ningun otro sitio puede provocar peticiones autenticadas
        # Se deduce de la peticion en vez de leerse de una variable de entorno:
        # con Secure=True fijo, la cookie no se enviaria en el http://localhost
        # del desarrollo y el dashboard daria 401 sin explicacion aparente.
        secure=request.is_secure,
        path="/",
    )

    # Token CSRF del patron de doble envio (ver backend/auth.py). A diferencia
    # de la de sesion, esta cookie NO es HttpOnly: el JavaScript del dashboard
    # tiene que leerla para copiarla al header X-CSRF-Token. Que sea legible no
    # la debilita -- su valor no autentica nada por si solo, solo prueba que la
    # peticion la origino una pagina de ESTE origen, que es lo unico que puede
    # leer la cookie.
    respuesta.set_cookie(
        COOKIE_CSRF,
        generar_token_csrf(),
        max_age=DURACION_SESION_SEG,
        httponly=False,
        samesite="Strict",
        secure=request.is_secure,
        path="/",
    )

    # Sin esto el navegador puede servir el shell desde su cache sin pasar por
    # aqui, y entonces la cookie no se renueva y la sesion muere en silencio.
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@dashboard_bp.get("/static-dashboard/<path:archivo>")
def estaticos(archivo: str):
    """Sirve los archivos de dashboard/ (css, js, vendor).

    send_from_directory usa safe_join, que rechaza con 404 cualquier ruta que
    intente salir del directorio base ('../../.env'). Por eso NUNCA se arma la
    ruta concatenando strings a mano.
    """
    return send_from_directory(RAIZ_DASHBOARD, archivo)
