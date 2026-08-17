"""Endpoint del ranking de temas (issue #1, Annabella).

Responde la pregunta de analisis:
    Cuales son los 5 temas mas cubiertos por los medios ecuatorianos
    analizados durante el periodo de recoleccion?

    GET /api/tendencias/top-temas
"""

from datetime import date, datetime

from flask import Blueprint, jsonify, request

from backend.auth import requiere_api_key
from backend.db import consultar, consultar_uno

tendencias_bp = Blueprint("tendencias", __name__)

LIMITE_POR_DEFECTO = 5
LIMITE_MAXIMO = 50


class ParametroInvalido(ValueError):
    """El cliente mando un parametro que no se puede procesar -> 400."""


def _leer_fecha(nombre: str) -> date | None:
    """Valida un parametro de fecha en formato YYYY-MM-DD."""
    crudo = request.args.get(nombre, "").strip()
    if not crudo:
        return None
    try:
        return datetime.strptime(crudo, "%Y-%m-%d").date()
    except ValueError:
        raise ParametroInvalido(
            f"El parametro '{nombre}' debe tener formato YYYY-MM-DD (recibido: '{crudo}')"
        ) from None


def _leer_limite() -> int:
    crudo = request.args.get("limite", "").strip()
    if not crudo:
        return LIMITE_POR_DEFECTO
    try:
        limite = int(crudo)
    except ValueError:
        raise ParametroInvalido(
            f"El parametro 'limite' debe ser un entero (recibido: '{crudo}')"
        ) from None
    if not 1 <= limite <= LIMITE_MAXIMO:
        raise ParametroInvalido(
            f"El parametro 'limite' debe estar entre 1 y {LIMITE_MAXIMO} (recibido: {limite})"
        )
    return limite


def _leer_medio() -> dict | None:
    """Resuelve el slug del medio contra la tabla, o falla con 400."""
    slug = request.args.get("medio", "").strip()
    if not slug:
        return None
    medio = consultar_uno("SELECT id, nombre, slug FROM medios WHERE slug = ?", (slug,))
    if medio is None:
        raise ParametroInvalido(f"No existe el medio '{slug}'")
    return medio


@tendencias_bp.get("/top-temas")
@requiere_api_key
def top_temas():
    """Ranking de temas por cantidad de noticias.

    Query params:
        limite  int          1..50, por defecto 5
        desde   YYYY-MM-DD   opcional
        hasta   YYYY-MM-DD   opcional
        medio   slug         opcional (el-universo | primicias)
    """
    try:
        limite = _leer_limite()
        desde = _leer_fecha("desde")
        hasta = _leer_fecha("hasta")
        medio = _leer_medio()
    except ParametroInvalido as error:
        return jsonify({"error": str(error)}), 400

    if desde and hasta and desde > hasta:
        return jsonify({"error": "'desde' no puede ser posterior a 'hasta'"}), 400

    # Filtros compartidos por las tres consultas. Siempre parametrizados: la
    # entrada del usuario nunca se concatena al SQL.
    condiciones: list[str] = []
    parametros: list[object] = []

    if desde:
        condiciones.append("n.fecha_publicacion >= ?")
        parametros.append(f"{desde.isoformat()} 00:00:00")
    if hasta:
        condiciones.append("n.fecha_publicacion <= ?")
        parametros.append(f"{hasta.isoformat()} 23:59:59")
    if medio:
        condiciones.append("n.medio_id = ?")
        parametros.append(medio["id"])

    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

    totales = consultar_uno(
        f"""
        SELECT COUNT(*)                                      AS total,
               SUM(CASE WHEN n.tema_id IS NULL THEN 1 ELSE 0 END) AS sin_clasificar,
               MIN(n.fecha_publicacion)                      AS primera,
               MAX(n.fecha_publicacion)                      AS ultima
        FROM noticias n
        {where}
        """,
        tuple(parametros),
    ) or {}

    total = totales.get("total") or 0
    sin_clasificar = totales.get("sin_clasificar") or 0
    clasificadas = total - sin_clasificar

    # El ranking solo considera noticias ya clasificadas; las pendientes se
    # reportan aparte para que el dashboard pueda advertir si el pipeline de
    # clasificacion (issue #2) esta atrasado.
    condiciones_ranking = condiciones + ["n.tema_id IS NOT NULL"]
    filas = consultar(
        f"""
        SELECT t.nombre AS tema, t.slug AS slug, COUNT(*) AS total
        FROM noticias n
        JOIN temas t ON t.id = n.tema_id
        WHERE {' AND '.join(condiciones_ranking)}
        GROUP BY t.id, t.nombre, t.slug
        ORDER BY total DESC, t.nombre ASC
        LIMIT ?
        """,
        tuple(parametros) + (limite,),
    )

    temas = [
        {
            "tema": fila["tema"],
            "slug": fila["slug"],
            "total": fila["total"],
            # Porcentaje sobre las clasificadas: incluir las pendientes
            # subestimaria a todos los temas por igual y confundiria la lectura.
            "porcentaje": round(fila["total"] * 100 / clasificadas, 1) if clasificadas else 0.0,
        }
        for fila in filas
    ]

    return jsonify(
        {
            "periodo": {
                "desde": desde.isoformat() if desde else (totales.get("primera") or None),
                "hasta": hasta.isoformat() if hasta else (totales.get("ultima") or None),
            },
            "medio": medio["slug"] if medio else "todos",
            "total_noticias": total,
            "clasificadas": clasificadas,
            "sin_clasificar": sin_clasificar,
            "limite": limite,
            "temas": temas,
        }
    )
