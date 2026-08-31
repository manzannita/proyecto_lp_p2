"""Catalogo de temas de la taxonomia.

Ruta:
    GET /api/temas  -> catalogo cerrado de temas con su volumen recolectado

Existe para que el dashboard NO escriba los slugs a mano. Los selectores de
tema de la vista de series y del buscador se arman con esta respuesta, asi que
si manana se agrega un tema a schema.sql y a pipeline/temas.yml, la interfaz lo
muestra sola.

El ORDEN es el del catalogo (por id) y no por volumen: el dashboard le asigna
a cada tema un color por su posicion en esta lista, y un orden que dependiera
de los datos repintaria los graficos cada vez que cambia el periodo.
"""

from flask import Blueprint, jsonify

from backend.auth import requiere_api_key
from backend.db import consultar

temas_bp = Blueprint("temas", __name__)


@temas_bp.get("")
@requiere_api_key
def catalogo_temas():
    """Lista los temas con cuantas noticias tiene clasificadas cada uno."""
    return jsonify(
        consultar(
            """
            SELECT t.id, t.nombre, t.slug, COUNT(n.id) AS total_noticias
            FROM temas t
            LEFT JOIN noticias n ON n.tema_id = t.id
            GROUP BY t.id, t.nombre, t.slug
            ORDER BY t.id
            """
        )
    )
