"""Endpoints de catalogo y comparativa entre medios.

Rutas:
    GET /api/medios              -> catalogo de medios
    GET /api/medios/comparativa  -> distribucion tematica por medio
"""

from flask import Blueprint, jsonify

from backend.auth import requiere_api_key
from backend.db import consultar

medios_bp = Blueprint("medios", __name__)


@medios_bp.get("")
@requiere_api_key
def catalogo_medios():
    """Lista medios activos y el volumen total recolectado de cada uno."""
    return jsonify(
        consultar(
            """
            SELECT m.id, m.nombre, m.slug, COUNT(n.id) AS total_noticias
            FROM medios m
            LEFT JOIN noticias n ON n.medio_id = m.id
            WHERE m.activo = 1
            GROUP BY m.id, m.nombre, m.slug
            ORDER BY m.id
            """
        )
    )
