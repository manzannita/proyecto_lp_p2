"""Recuperacion de contexto para el asistente de IA (patron RAG minimo).

Antes de llamar al LLM armamos el contexto SOLO con noticias que existen en la
base de datos. Nunca se concatena la entrada del usuario al SQL: cada termino
extraido de la pregunta viaja como placeholder.

Dos criterios, y NO son lo mismo
--------------------------------
Una pregunta acota el contexto de dos maneras distintas, y confundirlas era el
defecto que hacia que casi toda pregunta natural devolviera cero:

  FILTROS   el tema del catalogo y el rango de fechas que menciona la pregunta.
            Definen QUE noticias son elegibles.
  TERMINOS  las palabras con contenido. Solo REORDENAN dentro de lo elegible.

De ahi las dos reglas que gobiernan este modulo:

1. Un filtro alcanza por si solo. "resumime las noticias de deportes" no tiene
   ningun termino util --ningun titular contiene la palabra "deportes"-- pero si
   un filtro clarisimo, y la respuesta correcta son las noticias de deportes
   mas recientes, no un "no tengo datos suficientes".

2. Un termino que no calza con nada no puede vaciar el resultado. Si la
   pregunta trae un filtro y ademas palabras que no aparecen en ningun titular,
   se devuelve lo elegible por recencia. Antes se exigia el calce ADEMAS del
   filtro, asi que una palabra de relleno --"cada", en "que publico cada medio
   sobre seguridad"-- bastaba para dejar la respuesta en cero.

El cortocircuito se conserva donde importa: sin filtro Y sin ningun calce, la
lista sale vacia y el llamador no gasta la llamada al LLM.

Acentos
-------
Se comparan las formas normalizadas en los tres lugares donde hace falta:

  - las palabras vacias, para que "que" y "mas" acentuados no sobrevivan como
    terminos de busqueda y generen calces por casualidad;
  - los nombres del catalogo de temas, que se guardan sin acentos, asi que
    escribir "economia" con acento --la ortografia correcta-- impedia detectar
    el tema;
  - el texto de las noticias contra el termino buscado, mediante la funcion SQL
    sin_acentos() que registra backend/db.py. Sin ella, LIKE compara byte a
    byte y "diesel" no encuentra "diesel" acentuado ni al reves.
"""

import re
import unicodedata
from datetime import date, timedelta

from backend.db import consultar

LIMITE_POR_DEFECTO = 20
LIMITE_MAXIMO = 50

# Lista corta de palabras vacias en espanol: alcanza para descartar conectores
# comunes de una pregunta y no depende de backend/pipeline (que es de otro issue).
# Se escriben SIN acentos porque la comparacion se hace sobre la forma
# normalizada: asi "que", "que" acentuado, "mas" y "mas" acentuado caen todas.
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
    "hola", "habla", "hablo", "cuanto", "cuantos", "cada", "cuyo", "vez",
    "ademas", "asi", "aun", "aunque", "hacia", "segun", "solo",
    # Verbos y sustantivos con los que se FORMULA una pregunta. No describen
    # contenido, y como terminos de busqueda solo producen calces por
    # casualidad: "dijo" calza dentro de cualquier resumen que lo use.
    "noticia", "noticias", "resume", "resumen", "resumime", "resumeme",
    "cuentame", "cuentanos", "dime", "dice", "dijo", "paso", "pasa", "pasado",
    "explicame", "sabes",
}

# Lo que NO entra en la lista aunque podria parecer que si: "medio", "medios",
# "tema", "temas". Son palabras del dominio y pueden ser contenido legitimo de
# un titular. Que en una pregunta resulten ruido lo resuelve la regla 2 --el
# respaldo de los filtros-- y no una lista negra cada vez mas larga.

_PATRON_PALABRA = re.compile(r"[a-záéíóúüñ]{3,}")


def _sin_acentos(texto: str) -> str:
    """Minusculas y sin diacriticos, para comparar en Python.

    Su gemela para SQL es backend.db.sin_acentos, registrada en cada conexion.
    """
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def _extraer_terminos(pregunta: str, excluir: set[str] | None = None) -> list[str]:
    """Palabras con contenido de la pregunta, sin vacias ni duplicados.

    `excluir` recibe las palabras que ya actuan como FILTRO (nombre y slug del
    tema detectado). Si el tema ya restringe la busqueda, exigir su palabra
    como termino ademas es lo que vaciaba el resultado.
    """
    excluidas = excluir or set()
    terminos: list[str] = []
    vistos: set[str] = set()

    for palabra in _PATRON_PALABRA.findall(pregunta.lower()):
        normalizada = _sin_acentos(palabra)
        if normalizada in _STOPWORDS or normalizada in excluidas or normalizada in vistos:
            continue
        vistos.add(normalizada)
        terminos.append(normalizada)

    return terminos


def _detectar_tema(pregunta: str) -> dict | None:
    """Si la pregunta menciona un tema del catalogo, lo devuelve para filtrar.

    La comparacion es sin acentos en los dos lados: el catalogo guarda
    "Economia" y la persona escribe "economia" acentuado, que es la ortografia
    correcta. Sin normalizar, el tema no se detectaba nunca.
    """
    texto = _sin_acentos(pregunta)
    for tema in consultar("SELECT id, nombre, slug FROM temas"):
        if _sin_acentos(tema["slug"]) in texto or _sin_acentos(tema["nombre"]) in texto:
            return tema
    return None


def _palabras_del_tema(tema: dict | None) -> set[str]:
    """Formas normalizadas del tema, para no volver a usarlas como terminos."""
    if not tema:
        return set()
    palabras = {_sin_acentos(tema["slug"]), _sin_acentos(tema["nombre"])}
    # Un nombre compuesto ("Medio ambiente") aporta tambien sus partes.
    palabras.update(_sin_acentos(tema["nombre"]).split())
    return palabras


def _detectar_rango_fechas(pregunta: str) -> tuple[date | None, date | None]:
    """Reconoce expresiones temporales comunes en la pregunta."""
    texto = _sin_acentos(pregunta)
    hoy = date.today()
    if "hoy" in texto:
        return hoy, hoy
    if "ayer" in texto:
        ayer = hoy - timedelta(days=1)
        return ayer, ayer
    if "esta semana" in texto or "ultima semana" in texto:
        return hoy - timedelta(days=hoy.weekday()), hoy
    if "este mes" in texto:
        return hoy.replace(day=1), hoy
    return None, None


def recuperar_contexto(pregunta: str, limite: int = LIMITE_POR_DEFECTO) -> list[dict]:
    """Busca noticias reales relacionadas con la pregunta para fundamentar al LLM.

    Devuelve las noticias ordenadas por relevancia y recencia. Una lista vacia
    significa que la pregunta no se puede responder con lo recolectado, y el
    llamador debe cortocircuitar antes de gastar cuota del LLM.

    Las dos reglas estan explicadas en el docstring del modulo: los filtros
    definen lo elegible y alcanzan por si solos; los terminos solo reordenan y
    no pueden vaciar un resultado que un filtro ya delimito.
    """
    limite = max(1, min(limite, LIMITE_MAXIMO))

    tema = _detectar_tema(pregunta)
    desde, hasta = _detectar_rango_fechas(pregunta)
    terminos = _extraer_terminos(pregunta, excluir=_palabras_del_tema(tema))

    hay_filtro = bool(tema or desde or hasta)
    if not terminos and not hay_filtro:
        return []

    # --- Relevancia: 2 puntos por calce en el titular, 1 en el resumen -------
    # Con terminos es una suma de CASE; sin terminos es 0 para todas y manda la
    # fecha, que es el orden correcto para "las noticias de este tema".
    parametros_relevancia: list[object] = []
    if terminos:
        piezas = []
        for termino in terminos:
            piezas.append(
                "(CASE WHEN sin_acentos(n.titular) LIKE ? THEN 2 ELSE 0 END) + "
                "(CASE WHEN sin_acentos(COALESCE(n.resumen, '')) LIKE ? THEN 1 ELSE 0 END)"
            )
            parametros_relevancia.extend([f"%{termino}%", f"%{termino}%"])
        relevancia = " + ".join(piezas)
    else:
        relevancia = "0"

    # --- Elegibilidad: los filtros -------------------------------------------
    condiciones: list[str] = []
    parametros_filtro: list[object] = []

    if tema:
        condiciones.append("n.tema_id = ?")
        parametros_filtro.append(tema["id"])
    if desde:
        condiciones.append("n.fecha_publicacion >= ?")
        parametros_filtro.append(f"{desde.isoformat()} 00:00:00")
    if hasta:
        condiciones.append("n.fecha_publicacion <= ?")
        parametros_filtro.append(f"{hasta.isoformat()} 23:59:59")

    # Sin ningun filtro, el calce SI es obligatorio en el WHERE: es lo que evita
    # traerse la base entera cuando la pregunta no acota nada.
    if not hay_filtro:
        calces = []
        for termino in terminos:
            calces.append(
                "(sin_acentos(n.titular) LIKE ? OR sin_acentos(COALESCE(n.resumen, '')) LIKE ?)"
            )
            parametros_filtro.extend([f"%{termino}%", f"%{termino}%"])
        condiciones.append(f"({' OR '.join(calces)})")

    filas = consultar(
        f"""
        SELECT n.titular, n.resumen, n.url, n.fecha_publicacion,
               m.nombre AS medio, t.slug AS tema,
               ({relevancia}) AS relevancia
        FROM noticias n
        JOIN medios m ON m.id = n.medio_id
        LEFT JOIN temas t ON t.id = n.tema_id
        WHERE {' AND '.join(condiciones)}
        ORDER BY relevancia DESC, n.fecha_publicacion DESC
        LIMIT ?
        """,
        tuple(parametros_relevancia + parametros_filtro + [limite]),
    )

    # Lo que calza con la pregunta va primero y es lo que se prefiere. El
    # ORDER BY ya puso esas filas arriba, asi que el LIMIT no las pierde.
    con_calce = [fila for fila in filas if fila["relevancia"] > 0]
    if con_calce:
        return con_calce

    # Nada calzo. Si habia un filtro, lo elegible sigue siendo una respuesta
    # legitima: las mas recientes de ese tema o de ese periodo (regla 2).
    return filas if hay_filtro else []
