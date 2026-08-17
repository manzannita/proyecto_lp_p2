"""Seguridad basica de la API: header X-API-Key.

Todas las rutas /api/* del proyecto llevan @requiere_api_key. La clave sale de
la variable de entorno API_KEY y nunca del codigo.
"""

import hmac
from functools import wraps

from flask import current_app, jsonify, request

HEADER = "X-API-Key"


def requiere_api_key(vista):
    """Rechaza con 401 cualquier peticion sin un X-API-Key valido."""

    @wraps(vista)
    def envoltorio(*args, **kwargs):
        enviada = request.headers.get(HEADER, "")
        esperada = current_app.config["API_KEY"]

        # compare_digest evita filtrar la clave por diferencias de tiempo de
        # respuesta al comparar caracter por caracter.
        if not enviada or not hmac.compare_digest(enviada, esperada):
            return jsonify({"error": "API key invalida o ausente"}), 401

        return vista(*args, **kwargs)

    return envoltorio
