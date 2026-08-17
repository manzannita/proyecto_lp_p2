"""Endpoints de catalogo y comparativa entre medios.

Rutas:
    GET /api/medios              -> catalogo de medios
    GET /api/medios/comparativa  -> distribucion tematica por medio
"""

from datetime import date, datetime

import pandas as pd
from flask import Blueprint, jsonify, request

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


class ParametroInvalido(ValueError):
    """Un query parameter no cumple el contrato publico del endpoint."""


def _leer_fecha(nombre: str) -> date | None:
    valor = request.args.get(nombre, "").strip()
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError:
        raise ParametroInvalido(
            f"El parametro '{nombre}' debe tener formato YYYY-MM-DD (recibido: '{valor}')"
        ) from None


def _leer_booleano(nombre: str, defecto: bool = True) -> bool:
    valor = request.args.get(nombre, "").strip().lower()
    if not valor:
        return defecto
    if valor in {"true", "1", "si"}:
        return True
    if valor in {"false", "0", "no"}:
        return False
    raise ParametroInvalido(f"El parametro '{nombre}' debe ser true o false")


@medios_bp.get("/comparativa")
@requiere_api_key
def comparativa():
    """Compara la distribucion tematica de los dos medios analizados."""
    try:
        desde = _leer_fecha("desde")
        hasta = _leer_fecha("hasta")
        normalizar = _leer_booleano("normalizar")
    except ParametroInvalido as error:
        return jsonify({"error": str(error)}), 400
    if desde and hasta and desde > hasta:
        return jsonify({"error": "'desde' no puede ser posterior a 'hasta'"}), 400

    catalogo_temas = consultar("SELECT slug FROM temas ORDER BY id")
    slugs_validos = [fila["slug"] for fila in catalogo_temas]
    solicitados = [
        slug.strip()
        for slug in request.args.get("temas", "").split(",")
        if slug.strip()
    ]
    invalidos = [slug for slug in solicitados if slug not in slugs_validos]
    if invalidos:
        return jsonify({"error": f"No existe el tema '{invalidos[0]}'"}), 400
    slugs = list(dict.fromkeys(solicitados)) if solicitados else slugs_validos

    condiciones = ["n.tema_id IS NOT NULL"]
    parametros: list[object] = []
    if desde:
        condiciones.append("n.fecha_publicacion >= ?")
        parametros.append(f"{desde.isoformat()} 00:00:00")
    if hasta:
        condiciones.append("n.fecha_publicacion <= ?")
        parametros.append(f"{hasta.isoformat()} 23:59:59")
    condiciones.append(f"t.slug IN ({','.join('?' for _ in slugs)})")
    parametros.extend(slugs)

    # Una sola consulta agregada. El pivote y las brechas se calculan en pandas.
    filas = consultar(
        f"""
        SELECT m.nombre AS medio, m.slug AS medio_slug,
               t.slug AS tema, COUNT(*) AS total
        FROM noticias n
        JOIN medios m ON m.id = n.medio_id
        JOIN temas t ON t.id = n.tema_id
        WHERE {' AND '.join(condiciones)}
        GROUP BY m.id, m.nombre, m.slug, t.id, t.slug
        """,
        tuple(parametros),
    )

    primera = consultar("SELECT MIN(fecha_publicacion) AS fecha FROM noticias")[0]["fecha"]
    periodo = {
        "desde": desde.isoformat() if desde else (primera[:10] if primera else None),
        "hasta": hasta.isoformat() if hasta else date.today().isoformat(),
    }
    if not filas:
        return jsonify({"periodo": periodo, "medios": [], "brechas": []})

    medios = consultar("SELECT nombre, slug FROM medios WHERE activo = 1 ORDER BY id")
    frame = pd.DataFrame(filas)
    pivote = frame.pivot_table(
        index="medio_slug", columns="tema", values="total", aggfunc="sum", fill_value=0
    ).reindex(index=[medio["slug"] for medio in medios], columns=slugs, fill_value=0)

    total_global = int(pivote.to_numpy().sum())
    porcentajes: dict[tuple[str, str], float] = {}
    respuesta_medios = []
    for medio in medios:
        totales = pivote.loc[medio["slug"]]
        total_medio = int(totales.sum())
        denominador = total_medio if normalizar else total_global
        temas_medio = []
        for slug in slugs:
            total = int(totales[slug])
            porcentaje = round(total * 100 / denominador, 1) if denominador else 0.0
            porcentajes[(medio["slug"], slug)] = porcentaje
            temas_medio.append({"tema": slug, "total": total, "porcentaje": porcentaje})
        respuesta_medios.append(
            {"medio": medio["nombre"], "slug": medio["slug"], "total": total_medio, "temas": temas_medio}
        )

    brechas = []
    if len(medios) == 2:
        izquierda, derecha = medios
        for slug in slugs:
            p_izq = porcentajes[(izquierda["slug"], slug)]
            p_der = porcentajes[(derecha["slug"], slug)]
            brechas.append(
                {
                    "tema": slug,
                    "diferencia_pp": round(abs(p_izq - p_der), 1),
                    "prioriza": (
                        izquierda["slug"]
                        if p_izq > p_der
                        else derecha["slug"] if p_der > p_izq else None
                    ),
                }
            )
        brechas.sort(key=lambda fila: (-fila["diferencia_pp"], fila["tema"]))

    return jsonify({"periodo": periodo, "medios": respuesta_medios, "brechas": brechas})
