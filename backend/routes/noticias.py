"""Endpoint del buscador de noticias.

STUB - lo implementa Cristian en el issue #8.
El blueprint ya esta registrado en backend/app.py, asi que basta con agregar la
ruta aqui abajo; no hay que tocar app.py.

Ruta prevista:
    GET /api/noticias?q=&tema=&medio=&desde=&hasta=&pagina=&por_pagina=
"""

from flask import Blueprint

noticias_bp = Blueprint("noticias", __name__)
