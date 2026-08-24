"""Endpoint del buscador de noticias (issue #8).

    GET /api/noticias?q=&tema=&medio=&desde=&hasta=&pagina=&por_pagina=

Es el respaldo verificable del grafico de series-semanales: permite pasar de
un pico en la serie a las noticias concretas que lo produjeron.
"""

import unicodedata
from datetime import date, datetime

from flask import Blueprint, jsonify, request

from backend.auth import requiere_api_key
from backend.db import consultar, consultar_uno, obtener_conexion

noticias_bp = Blueprint("noticias", __name__)

POR_PAGINA_POR_DEFECTO = 20
POR_PAGINA_MAXIMO = 50


class ParametroInvalido(ValueError):
    """El cliente mando un parametro que no se puede procesar -> 400."""


def _normalizar_texto(texto: str | None) -> str | None:
    """Minusculas y sin tildes, para comparar sin importar acentos.

    SQLite no trae un equivalente a unaccent() de fabrica, asi que se resuelve
    registrando esta funcion Python como funcion SQL (ver _registrar_normalizador).
    """
    if texto is None:
        return texto
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(caracter for caracter in descompuesto if not unicodedata.combining(caracter))
    return sin_tildes.lower()


def _registrar_normalizador() -> None:
    """Expone _normalizar_texto como funcion SQL en la conexion de la peticion."""
    obtener_conexion().create_function("normalizar_busqueda", 1, _normalizar_texto, deterministic=True)


def _escapar_comodines(valor: str) -> str:
    """Escapa \\, % y _ para que la entrada del usuario nunca actue como
    comodin silencioso dentro del LIKE."""
    return valor.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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


def _leer_q() -> str | None:
    crudo = request.args.get("q", "").strip()
    if not crudo:
        return None
    if len(crudo) < 2:
        raise ParametroInvalido("El parametro 'q' debe tener al menos 2 caracteres")
    return crudo


def _leer_tema() -> dict | None:
    slug = request.args.get("tema", "").strip()
    if not slug:
        return None
    tema = consultar_uno("SELECT id, nombre, slug FROM temas WHERE slug = ?", (slug,))
    if tema is None:
        raise ParametroInvalido(f"No existe el tema '{slug}'")
    return tema


def _leer_medio() -> dict | None:
    slug = request.args.get("medio", "").strip()
    if not slug:
        return None
    medio = consultar_uno("SELECT id, nombre, slug FROM medios WHERE slug = ?", (slug,))
    if medio is None:
        raise ParametroInvalido(f"No existe el medio '{slug}'")
    return medio


def _leer_pagina() -> int:
    crudo = request.args.get("pagina", "").strip()
    if not crudo:
        return 1
    try:
        pagina = int(crudo)
    except ValueError:
        raise ParametroInvalido(f"El parametro 'pagina' debe ser un entero (recibido: '{crudo}')") from None
    if pagina < 1:
        raise ParametroInvalido(f"El parametro 'pagina' debe ser mayor o igual a 1 (recibido: {pagina})")
    return pagina


def _leer_por_pagina() -> int:
    crudo = request.args.get("por_pagina", "").strip()
    if not crudo:
        return POR_PAGINA_POR_DEFECTO
    try:
        por_pagina = int(crudo)
    except ValueError:
        raise ParametroInvalido(
            f"El parametro 'por_pagina' debe ser un entero (recibido: '{crudo}')"
        ) from None
    if not 1 <= por_pagina <= POR_PAGINA_MAXIMO:
        raise ParametroInvalido(
            f"El parametro 'por_pagina' debe estar entre 1 y {POR_PAGINA_MAXIMO} (recibido: {por_pagina})"
        )
    return por_pagina


@noticias_bp.get("")
@requiere_api_key
def buscar_noticias():
    """Busca noticias por palabra clave y/o filtros de catalogo.

    Query params:
        q          texto   opcional, al menos 2 caracteres
        tema       slug    opcional, debe existir en el catalogo
        medio      slug    opcional, debe existir en el catalogo
        desde      YYYY-MM-DD  opcional
        hasta      YYYY-MM-DD  opcional
        pagina     int     >= 1, por defecto 1
        por_pagina int     1..50, por defecto 20
    """
    try:
        q = _leer_q()
        tema = _leer_tema()
        medio = _leer_medio()
        desde = _leer_fecha("desde")
        hasta = _leer_fecha("hasta")
        pagina = _leer_pagina()
        por_pagina = _leer_por_pagina()
    except ParametroInvalido as error:
        return jsonify({"error": str(error)}), 400

    if desde and hasta and desde > hasta:
        return jsonify({"error": "'desde' no puede ser posterior a 'hasta'"}), 400

    # Filtros compartidos por el COUNT(*) y la consulta paginada: si no usaran
    # las mismas condiciones, "paginas" podria no coincidir con "total".
    condiciones: list[str] = []
    parametros: list[object] = []

    if q:
        _registrar_normalizador()
        patron = f"%{_escapar_comodines(_normalizar_texto(q))}%"
        condiciones.append(
            "(normalizar_busqueda(n.titular) LIKE ? ESCAPE '\\' OR "
            "normalizar_busqueda(n.resumen) LIKE ? ESCAPE '\\')"
        )
        parametros.extend([patron, patron])
    if tema:
        condiciones.append("n.tema_id = ?")
        parametros.append(tema["id"])
    if medio:
        condiciones.append("n.medio_id = ?")
        parametros.append(medio["id"])
    if desde:
        condiciones.append("n.fecha_publicacion >= ?")
        parametros.append(f"{desde.isoformat()} 00:00:00")
    if hasta:
        condiciones.append("n.fecha_publicacion <= ?")
        parametros.append(f"{hasta.isoformat()} 23:59:59")

    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

    total_fila = consultar_uno(f"SELECT COUNT(*) AS total FROM noticias n {where}", tuple(parametros))
    total = (total_fila or {}).get("total") or 0
    paginas = (total + por_pagina - 1) // por_pagina if total else 0

    filas = consultar(
        f"""
        SELECT n.id, n.titular, n.resumen, n.url, n.fecha_publicacion,
               m.nombre AS medio, m.slug AS medio_slug,
               t.nombre AS tema, t.slug AS tema_slug
        FROM noticias n
        JOIN medios m ON m.id = n.medio_id
        LEFT JOIN temas t ON t.id = n.tema_id
        {where}
        ORDER BY n.fecha_publicacion DESC, n.id DESC
        LIMIT ? OFFSET ?
        """,
        tuple(parametros) + (por_pagina, (pagina - 1) * por_pagina),
    )

    return jsonify(
        {
            "total": total,
            "pagina": pagina,
            "por_pagina": por_pagina,
            "paginas": paginas,
            "noticias": filas,
        }
    )
