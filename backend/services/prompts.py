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


def construir_prompt_usuario(pregunta: str, contexto: list[dict]) -> str:
    """Arma el mensaje de usuario: la pregunta seguida del contexto numerado."""
    if not contexto:
        lineas = ["(No hay noticias en el contexto.)"]
    else:
        lineas = [
            f"{indice}. [{noticia['medio']}, {noticia['fecha_publicacion'][:10]}] "
            f"{noticia['titular']} ({noticia['url']})"
            for indice, noticia in enumerate(contexto, start=1)
        ]
    return (
        f"Pregunta: {pregunta}\n\n"
        "Contexto (noticias recolectadas, la unica fuente permitida):\n" + "\n".join(lineas)
    )
