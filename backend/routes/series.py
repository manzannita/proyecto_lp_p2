"""Endpoint de evolucion temporal por tema.

STUB - lo implementa Cristian en el issue #3.
El blueprint ya esta registrado en backend/app.py; no hay que tocar app.py.

Comparte el prefijo /api/tendencias con tendencias_bp pero expone una ruta
distinta, por eso no chocan.

Ruta prevista:
    GET /api/tendencias/series-semanales?tema=<slug>
"""

from flask import Blueprint

series_bp = Blueprint("series", __name__)
