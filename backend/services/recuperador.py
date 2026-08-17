"""Recuperacion de contexto para el asistente de IA (patron RAG minimo).

Antes de llamar al LLM armamos el contexto SOLO con noticias que existen en la
base de datos. Nunca se concatena la entrada del usuario al SQL: cada termino
extraido de la pregunta viaja como placeholder.
"""

import re
from datetime import date, timedelta

from backend.db import consultar

LIMITE_POR_DEFECTO = 20
LIMITE_MAXIMO = 50

# Lista corta de palabras vacias en espanol: alcanza para descartar conectores
# comunes de una pregunta y no depende de backend/pipeline (que es de otro issue).
_STOPWORDS = {
    "de", "la", "que", "el", "en", "y", "a", "los", "del", "se", "las", "por",
    "un", "para", "con", "no", "una", "su", "al", "es", "lo", "como", "mas",
    "pero", "sus", "le", "ya", "o", "este", "si", "porque", "esta", "entre",
    "cuando", "muy", "sin", "sobre", "tambien", "me", "hasta", "hay", "donde",
    "quien", "desde", "todo", "nos", "durante", "todos", "uno", "les", "ni",
    "contra", "otros", "ese", "eso", "ante", "ellos", "esto", "mi", "antes",
    "algunos", "unos", "yo", "otro", "otras", "otra", "tanto", "esa", "estos",
    "mucho", "quienes", "nada", "muchos", "cual", "cuales", "poco", "ella",
    "estar", "estas", "algunas", "algo", "nosotros", "mis", "tu", "tus",
    "hola", "habla", "hablo", "cuanto", "cuantos", "que", "las", "los",
}

_PATRON_PALABRA = re.compile(r"[a-zA-Záéíóúñ]{3,}")


def _extraer_terminos(pregunta: str) -> list[str]:
    """Tokeniza la pregunta y descarta palabras vacias y duplicados."""
    palabras = _PATRON_PALABRA.findall(pregunta.lower())
    terminos: list[str] = []
    for palabra in palabras:
        if palabra in _STOPWORDS or palabra in terminos:
            continue
        terminos.append(palabra)
    return terminos


def _detectar_tema(pregunta: str) -> dict | None:
    """Si la pregunta menciona un tema del catalogo, lo devuelve para filtrar."""
    texto = pregunta.lower()
    for tema in consultar("SELECT id, nombre, slug FROM temas"):
        if tema["slug"] in texto or tema["nombre"].lower() in texto:
            return tema
    return None


def _detectar_rango_fechas(pregunta: str) -> tuple[date | None, date | None]:
    """Reconoce expresiones temporales comunes en la pregunta."""
    texto = pregunta.lower()
    hoy = date.today()
    if "hoy" in texto:
        return hoy, hoy
    if "ayer" in texto:
        ayer = hoy - timedelta(days=1)
        return ayer, ayer
    if "esta semana" in texto or "ultima semana" in texto or "última semana" in texto:
        return hoy - timedelta(days=hoy.weekday()), hoy
    if "este mes" in texto:
        return hoy.replace(day=1), hoy
    return None, None


def recuperar_contexto(pregunta: str, limite: int = LIMITE_POR_DEFECTO) -> list[dict]:
    """Busca noticias reales relacionadas con la pregunta para fundamentar al LLM.

    Extrae terminos de la pregunta, busca coincidencias parametrizadas en
    titular y resumen, aplica los filtros de tema/fecha detectados y ordena
    por relevancia (cuantos terminos matchea, con mas peso al titular) y
    recencia. Si no hay coincidencias devuelve lista vacia: el llamador debe
    cortocircuitar antes de gastar cuota del LLM.
    """
    limite = max(1, min(limite, LIMITE_MAXIMO))
    terminos = _extraer_terminos(pregunta)
    if not terminos:
        return []

    tema = _detectar_tema(pregunta)
    desde, hasta = _detectar_rango_fechas(pregunta)

    comodines = [f"%{termino}%" for termino in terminos]

    relevancia_expr = " + ".join(
        "(CASE WHEN n.titular LIKE ? THEN 2 ELSE 0 END) + "
        "(CASE WHEN n.resumen LIKE ? THEN 1 ELSE 0 END)"
        for _ in terminos
    )
    parametros_relevancia: list[object] = []
    for comodin in comodines:
        parametros_relevancia.extend([comodin, comodin])

    condiciones_match = " OR ".join("(n.titular LIKE ? OR n.resumen LIKE ?)" for _ in terminos)
    parametros_match: list[object] = []
    for comodin in comodines:
        parametros_match.extend([comodin, comodin])

    condiciones = [f"({condiciones_match})"]
    parametros_filtro: list[object] = list(parametros_match)
    if tema:
        condiciones.append("n.tema_id = ?")
        parametros_filtro.append(tema["id"])
    if desde:
        condiciones.append("n.fecha_publicacion >= ?")
        parametros_filtro.append(f"{desde.isoformat()} 00:00:00")
    if hasta:
        condiciones.append("n.fecha_publicacion <= ?")
        parametros_filtro.append(f"{hasta.isoformat()} 23:59:59")

    filas = consultar(
        f"""
        SELECT n.titular, n.resumen, n.url, n.fecha_publicacion,
               m.nombre AS medio, t.slug AS tema,
               ({relevancia_expr}) AS relevancia
        FROM noticias n
        JOIN medios m ON m.id = n.medio_id
        LEFT JOIN temas t ON t.id = n.tema_id
        WHERE {' AND '.join(condiciones)}
        ORDER BY relevancia DESC, n.fecha_publicacion DESC
        LIMIT ?
        """,
        tuple(parametros_relevancia + parametros_filtro + [limite]),
    )

    return [fila for fila in filas if fila["relevancia"] > 0]
