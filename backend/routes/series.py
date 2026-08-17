"""Endpoint de evolucion temporal por tema.

Responde la pregunta de analisis:
    Como varia semana a semana la cantidad de noticias publicadas sobre un
    tema especifico (por ejemplo clima o seguridad)?

    GET /api/tendencias/series-semanales?tema=<slug>

Comparte el prefijo /api/tendencias con tendencias_bp pero expone una ruta
distinta, por eso no chocan.
"""

from datetime import date, datetime

import pandas as pd
from flask import Blueprint, jsonify, request

from backend.auth import requiere_api_key
from backend.db import consultar, consultar_uno

series_bp = Blueprint("series", __name__)


class ParametroInvalido(ValueError):
    """El cliente mando un parametro que no se puede procesar -> 400."""


def _leer_fecha(nombre: str) -> date | None:
    crudo = request.args.get(nombre, "").strip()
    if not crudo:
        return None
    try:
        return datetime.strptime(crudo, "%Y-%m-%d").date()
    except ValueError:
        raise ParametroInvalido(
            f"El parametro '{nombre}' debe tener formato YYYY-MM-DD (recibido: '{crudo}')"
        ) from None


def _leer_tema() -> dict:
    """Resuelve el slug obligatorio del tema, o falla con ParametroInvalido / None."""
    slug = request.args.get("tema", "").strip()
    if not slug:
        raise ParametroInvalido("El parametro 'tema' es obligatorio")
    return slug


def _leer_medio() -> dict | None:
    slug = request.args.get("medio", "").strip()
    if not slug:
        return None
    medio = consultar_uno("SELECT id, nombre, slug FROM medios WHERE slug = ?", (slug,))
    if medio is None:
        raise ParametroInvalido(f"No existe el medio '{slug}'")
    return medio


def _semana_vacia() -> dict:
    return {
        "total_periodo": 0,
        "promedio_semanal": 0.0,
        "semana_pico": None,
        "variacion_ultima_semana_pct": None,
    }


@series_bp.get("/series-semanales")
@requiere_api_key
def series_semanales():
    """Serie temporal semanal de noticias para un tema.

    Query params:
        tema    slug         obligatorio
        desde   YYYY-MM-DD   opcional, por defecto la primera noticia del tema
        hasta   YYYY-MM-DD   opcional, por defecto hoy
        medio   slug         opcional, filtra por medio
    """
    try:
        slug_tema = _leer_tema()
        desde = _leer_fecha("desde")
        hasta = _leer_fecha("hasta")
        medio = _leer_medio()
    except ParametroInvalido as error:
        return jsonify({"error": str(error)}), 400

    if desde and hasta and desde > hasta:
        return jsonify({"error": "'desde' no puede ser posterior a 'hasta'"}), 400

    tema = consultar_uno("SELECT id, nombre, slug FROM temas WHERE slug = ?", (slug_tema,))
    if tema is None:
        return jsonify({"error": f"No existe el tema '{slug_tema}'"}), 404

    condiciones = ["n.tema_id = ?"]
    parametros: list[object] = [tema["id"]]
    if medio:
        condiciones.append("n.medio_id = ?")
        parametros.append(medio["id"])

    if desde is None:
        primera = consultar_uno(
            f"SELECT MIN(n.fecha_publicacion) AS fecha FROM noticias n WHERE {' AND '.join(condiciones)}",
            tuple(parametros),
        )
        fecha_primera = (primera or {}).get("fecha")
        desde = datetime.strptime(fecha_primera[:10], "%Y-%m-%d").date() if fecha_primera else None
    if hasta is None:
        hasta = date.today()
    if desde is None:
        desde = hasta

    condiciones_rango = condiciones + ["n.fecha_publicacion >= ?", "n.fecha_publicacion <= ?"]
    parametros_rango = parametros + [f"{desde.isoformat()} 00:00:00", f"{hasta.isoformat()} 23:59:59"]

    filas = consultar(
        f"""
        SELECT substr(n.fecha_publicacion, 1, 10) AS fecha, COUNT(*) AS total
        FROM noticias n
        WHERE {' AND '.join(condiciones_rango)}
        GROUP BY fecha
        ORDER BY fecha
        """,
        tuple(parametros_rango),
    )

    periodo = {"desde": desde.isoformat(), "hasta": hasta.isoformat()}
    total_en_rango = sum(fila["total"] for fila in filas)

    if total_en_rango == 0:
        return jsonify(
            {
                "tema": tema["slug"],
                "granularidad": "semana",
                "periodo": periodo,
                "serie": [],
                "resumen": _semana_vacia(),
            }
        )

    # Serie diaria completa (con los huecos en 0) y luego resample semanal
    # ISO (lunes como inicio) con pandas: el dashboard necesita semanas
    # continuas, no solo las que tuvieron noticias.
    rango_dias = pd.date_range(desde, hasta, freq="D")
    serie_diaria = pd.Series(0, index=rango_dias, dtype="int64")
    for fila in filas:
        serie_diaria[pd.Timestamp(fila["fecha"])] = fila["total"]

    serie_semanal = serie_diaria.resample("W-MON", label="left", closed="left").sum()

    serie = []
    for inicio, total in serie_semanal.items():
        iso = inicio.isocalendar()
        serie.append(
            {
                "semana_inicio": inicio.date().isoformat(),
                "semana_iso": f"{iso.year}-W{iso.week:02d}",
                "total": int(total),
            }
        )

    total_periodo = int(serie_semanal.sum())
    promedio_semanal = round(total_periodo / len(serie), 1) if serie else 0.0
    semana_pico = serie[int(serie_semanal.to_numpy().argmax())]["semana_iso"]

    variacion_ultima_semana_pct = None
    if len(serie) >= 2:
        penultima, ultima = serie[-2]["total"], serie[-1]["total"]
        if penultima:
            variacion_ultima_semana_pct = round((ultima - penultima) * 100 / penultima, 1)

    return jsonify(
        {
            "tema": tema["slug"],
            "granularidad": "semana",
            "periodo": periodo,
            "serie": serie,
            "resumen": {
                "total_periodo": total_periodo,
                "promedio_semanal": promedio_semanal,
                "semana_pico": semana_pico,
                "variacion_ultima_semana_pct": variacion_ultima_semana_pct,
            },
        }
    )
