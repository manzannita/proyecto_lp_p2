"""Endpoint del asistente de IA generativa.

Ruta:
    POST /api/asistente/preguntar
"""

from flask import Blueprint, jsonify, request

from backend.auth import requiere_api_key
from backend.services import asistente_ia
from backend.services.recuperador import recuperar_contexto

asistente_bp = Blueprint("asistente", __name__)

LIMITE_CONTEXTO_POR_DEFECTO = 20
LIMITE_CONTEXTO_MAXIMO = 50
LARGO_MAXIMO_PREGUNTA = 500

MENSAJE_SIN_DATOS = "No tengo datos suficientes: no encontre noticias recolectadas sobre eso."
MENSAJE_NO_DISPONIBLE = "El asistente no esta disponible en este momento"


@asistente_bp.post("/preguntar")
@requiere_api_key
def preguntar():
    """Responde una pregunta en lenguaje natural fundamentada en noticias reales.

    Body JSON:
        pregunta          str  obligatoria, 1..500 caracteres
        limite_contexto    int  opcional, 1..50 (por defecto 20)
    """
    cuerpo = request.get_json(silent=True) or {}
    pregunta = str(cuerpo.get("pregunta", "")).strip()

    if not pregunta:
        return jsonify({"error": "El campo 'pregunta' es obligatorio"}), 400
    if len(pregunta) > LARGO_MAXIMO_PREGUNTA:
        return (
            jsonify({"error": f"'pregunta' no puede superar los {LARGO_MAXIMO_PREGUNTA} caracteres"}),
            400,
        )

    limite_contexto = cuerpo.get("limite_contexto", LIMITE_CONTEXTO_POR_DEFECTO)
    try:
        limite_contexto = int(limite_contexto)
    except (TypeError, ValueError):
        return jsonify({"error": "'limite_contexto' debe ser un entero"}), 400
    if not 1 <= limite_contexto <= LIMITE_CONTEXTO_MAXIMO:
        return (
            jsonify({"error": f"'limite_contexto' debe estar entre 1 y {LIMITE_CONTEXTO_MAXIMO}"}),
            400,
        )

    contexto = recuperar_contexto(pregunta, limite=limite_contexto)

    if not contexto:
        # Cortocircuito: sin noticias que citar no se llama al LLM. Ahorra
        # cuota y evita que el modelo alucine una respuesta sin fundamento.
        return jsonify(
            {
                "respuesta": MENSAJE_SIN_DATOS,
                "fuentes": [],
                "noticias_consultadas": 0,
                "modelo": None,
            }
        )

    try:
        respuesta, modelo = asistente_ia.preguntar(pregunta, contexto)
    except asistente_ia.LLMRateLimit:
        return jsonify({"error": "El proveedor del asistente aplico un limite de tasa"}), 429
    except asistente_ia.LLMError:
        # Nunca se filtra el mensaje crudo del proveedor ni un stack trace.
        return jsonify({"error": MENSAJE_NO_DISPONIBLE}), 503

    fuentes = [
        {
            "titular": noticia["titular"],
            "medio": noticia["medio"],
            "url": noticia["url"],
            "fecha": noticia["fecha_publicacion"][:10],
        }
        for noticia in contexto
    ]

    return jsonify(
        {
            "respuesta": respuesta,
            "fuentes": fuentes,
            "noticias_consultadas": len(contexto),
            "modelo": modelo,
        }
    )
