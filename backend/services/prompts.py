"""Prompts del asistente de IA generativa."""

PROMPT_SISTEMA = (
    "Sos un asistente que resume noticias ecuatorianas para NoticIA EC. "
    "Respondes UNICAMENTE con base en los titulares y resumenes que se te "
    "entregan como contexto: nunca inventes datos, cifras ni hechos que no "
    "esten en ese contexto. Cita el medio de cada dato que uses (por ejemplo "
    "'segun Primicias...'). Si el contexto no alcanza para responder con "
    "certeza, decilo explicitamente con la frase 'no tengo datos suficientes' "
    "en vez de completar con conocimiento general o suposiciones."
)


# Tope del resumen de cada noticia dentro del prompt. Los resumenes de RSS son
# de una a tres frases, asi que 240 caracteres casi nunca cortan; el tope esta
# para que una noticia con un resumen anomalo no se lleve el contexto entero.
LARGO_MAXIMO_RESUMEN = 240


def _lineas_de_noticia(indice: int, noticia: dict) -> list[str]:
    """Una noticia del contexto: titular en una linea, resumen en la siguiente.

    El resumen va aparte y no pegado al titular a proposito: el titular lleva
    la referencia citable (medio, fecha, URL) y tiene que quedar legible de un
    renglon, tanto para el modelo como para quien lea el prompt depurando.
    """
    lineas = [
        f"{indice}. [{noticia['medio']}, {noticia['fecha_publicacion'][:10]}] "
        f"{noticia['titular']} ({noticia['url']})"
    ]

    resumen = (noticia.get("resumen") or "").strip()
    if resumen:
        # En una sola linea: los saltos del resumen romperian la numeracion.
        resumen = " ".join(resumen.split())
        if len(resumen) > LARGO_MAXIMO_RESUMEN:
            resumen = resumen[:LARGO_MAXIMO_RESUMEN].rstrip() + "..."
        lineas.append(f"   Resumen: {resumen}")

    return lineas


def construir_prompt_usuario(pregunta: str, contexto: list[dict]) -> str:
    """Arma el mensaje de usuario: la pregunta seguida del contexto numerado.

    Se incluye el RESUMEN de cada noticia y no solo el titular. PROMPT_SISTEMA
    le promete al modelo "titulares y resumenes", y el recuperador ya trae el
    resumen de la base --lo usa incluso para calcular la relevancia-- pero
    antes nunca llegaba al prompt. El efecto se veia en las respuestas reales:
    el modelo cerraba diciendo "no tengo datos suficientes sobre los detalles
    especificos, ya que el contexto solo incluye los titulares". Prometerle un
    contexto que no se le entrega es la peor de las dos opciones.
    """
    if not contexto:
        lineas = ["(No hay noticias en el contexto.)"]
    else:
        lineas = [
            linea
            for indice, noticia in enumerate(contexto, start=1)
            for linea in _lineas_de_noticia(indice, noticia)
        ]
    return (
        f"Pregunta: {pregunta}\n\n"
        "Contexto (noticias recolectadas, la unica fuente permitida):\n" + "\n".join(lineas)
    )
