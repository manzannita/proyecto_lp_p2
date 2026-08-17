"""Endpoints de comparativa entre medios.

STUB - lo implementa Valentina en el issue #2.
El blueprint ya esta registrado en backend/app.py, asi que basta con agregar
las rutas aqui abajo; no hay que tocar app.py.

Rutas previstas:
    GET /api/medios              -> catalogo de medios
    GET /api/medios/comparativa  -> distribucion tematica por medio
"""

from flask import Blueprint

medios_bp = Blueprint("medios", __name__)
