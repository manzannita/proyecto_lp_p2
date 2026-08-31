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

    # Sin temas en el catalogo, "t.slug IN ()" no es SQL valido y SQLite lanza
    # OperationalError -> 500. Pasa en una base recien creada, antes de sembrar
    # el catalogo, y la respuesta correcta es un 200 vacio.
    if not slugs:
        return jsonify({"periodo": {"desde": None, "hasta": None}, "medios": [], "brechas": []})

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

    # El periodo se deduce de los DATOS y no del reloj. Antes "hasta" caia en
    # date.today() cuando no habia filtro, asi que el cabezote del dashboard
    # afirmaba que los datos llegaban hasta hoy aunque la ultima noticia
    # recolectada fuera de dos semanas antes. tendencias.py ya lo hacia bien.
    limites = consultar(
        "SELECT MIN(fecha_publicacion) AS primera, MAX(fecha_publicacion) AS ultima FROM noticias"
    )[0]
    periodo = {
        "desde": desde.isoformat() if desde else (limites["primera"] or "")[:10] or None,
        "hasta": hasta.isoformat() if hasta else (limites["ultima"] or "")[:10] or None,
    }
    if not filas:
        return jsonify({"periodo": periodo, "medios": [], "brechas": []})

    medios = consultar("SELECT nombre, slug FROM medios WHERE activo = 1 ORDER BY id")
    frame = pd.DataFrame(filas)
    pivote = frame.pivot_table(
        index="medio_slug", columns="tema", values="total", aggfunc="sum", fill_value=0
    ).reindex(index=[medio["slug"] for medio in medios], columns=slugs, fill_value=0)

    # DENOMINADORES SIN EL FILTRO DE TEMAS.
    #
    # Antes se sumaba el pivote, que ya viene recortado a los temas pedidos, asi
    # que el porcentaje se renormalizaba sobre la seleccion. Con ?temas=clima y
    # una sola noticia de clima en El Universo, el endpoint informaba 100,0 %
    # --lo real es 1/101, o sea ~1 %-- y el frontend lo redactaba como
    # "El Universo dedica 100,0 puntos mas a Clima". Dos ordenes de magnitud de
    # error presentados como conclusion editorial.
    #
    # La etiqueta que ve el usuario dice "% dentro de la agenda de cada medio",
    # asi que el denominador tiene que ser la agenda COMPLETA del medio en el
    # periodo, no el recorte tematico. Misma consulta, mismos filtros de fecha,
    # sin la clausula de temas.
    condiciones_sin_tema = [c for c in condiciones if not c.startswith("t.slug IN")]
    parametros_sin_tema = tuple(parametros[: len(parametros) - len(slugs)])
    totales_por_medio = {
        fila["medio_slug"]: int(fila["total"])
        for fila in consultar(
            f"""
            SELECT m.slug AS medio_slug, COUNT(*) AS total
            FROM noticias n
            JOIN medios m ON m.id = n.medio_id
            JOIN temas t ON t.id = n.tema_id
            WHERE {' AND '.join(condiciones_sin_tema)}
            GROUP BY m.slug
            """,
            parametros_sin_tema,
        )
    }
    total_global = sum(totales_por_medio.values())
    porcentajes: dict[tuple[str, str], float] = {}
    respuesta_medios = []
    for medio in medios:
        totales = pivote.loc[medio["slug"]]
        # Agenda completa del medio en el periodo, no la suma del recorte.
        total_medio = totales_por_medio.get(medio["slug"], 0)
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
