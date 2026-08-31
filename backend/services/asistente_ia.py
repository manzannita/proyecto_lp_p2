"""Cliente del LLM para el asistente de IA generativa.

Proveedor: Anthropic (Messages API), via el SDK oficial `anthropic`. La clave
sale de la variable de entorno LLM_API_KEY y el modelo de LLM_MODELO; nunca se
hardcodean. Si faltan, el servicio falla al primer uso con un mensaje claro en
vez de romperse a medias de una peticion con un error crudo del proveedor.

Este modulo es la UNICA pieza que habla con el proveedor. Su contrato con el
resto del backend es una sola funcion:

    preguntar(pregunta, contexto) -> (texto_de_la_respuesta, nombre_del_modelo)

y tres excepciones (LLMError, LLMTimeout, LLMRateLimit) que backend/routes/
asistente.py mapea a 503 y 429. Cambiar de proveedor solo toca este archivo:
ya paso una vez, de OpenAI a Anthropic, y ninguna capa de arriba se enteró.

Por que el SDK y no requests
----------------------------
Trae los reintentos con espera exponencial, el timeout y las excepciones
tipadas ya resueltos. La version anterior hacia todo eso a mano.

Que NO se le manda al modelo
----------------------------
Ni parametros de sampling (temperature, top_p) ni de razonamiento (thinking,
effort). No es olvido: el modelo se elige por variable de entorno, y esos
parametros no estan disponibles en toda la familia -- `temperature` lo rechazan
con 400 los modelos Opus 5 y Sonnet 5, y `effort` lo rechaza Haiku 4.5. Al no
mandarlos, el mismo codigo funciona con claude-haiku-4-5, claude-sonnet-5 o
claude-opus-5 sin tocar una linea. La fidelidad al contexto se consigue con el
prompt (ver backend/services/prompts.py), que es donde corresponde.
"""

import logging
import os

import anthropic

from backend.services.prompts import PROMPT_SISTEMA, construir_prompt_usuario

# El cliente NUNCA ve el motivo real de un fallo del proveedor: la ruta le
# responde 503 con un texto propio. Pero alguien tiene que poder diagnosticarlo,
# asi que el detalle se registra aca. Sin esto, un error de configuracion (una
# clave que exige workspace, un modelo mal escrito) es indistinguible de una
# caida del proveedor: los dos se ven como "no esta disponible".
_log = logging.getLogger(__name__)

TIMEOUT_SEGUNDOS = 30
REINTENTOS = 1  # 1 reintento ante error transitorio (5xx / 429 / red)

# Techo de la respuesta. Es obligatorio en la Messages API, y va bajo a
# proposito: la respuesta que se busca es un resumen de pocos parrafos sobre
# titulares, no un ensayo. Si el modelo llegara al techo, el texto se cortaria
# a mitad de frase -- 1024 tokens son ~750 palabras, de sobra.
MAXIMO_TOKENS_RESPUESTA = 1024


class LLMError(RuntimeError):
    """Error generico del proveedor del LLM (la capa de rutas lo mapea a 503)."""


class LLMTimeout(LLMError):
    """El proveedor no respondio dentro del timeout configurado."""


class LLMRateLimit(LLMError):
    """El proveedor rechazo la peticion por limite de tasa (429). Sin reintento."""


def _configuracion() -> tuple[str, str]:
    clave = os.environ.get("LLM_API_KEY", "").strip()
    modelo = os.environ.get("LLM_MODELO", "").strip()
    if not clave or not modelo:
        raise LLMError(
            "Faltan LLM_API_KEY y/o LLM_MODELO. Copia .env.example a .env y completalas."
        )
    return clave, modelo


def _workspace() -> str:
    """Workspace del que actua la peticion, si la clave lo exige.

    Una clave de Anthropic ligada a una identidad no basta por si sola: la API
    responde 400 pidiendo el encabezado anthropic-workspace-id. Con una clave
    normal esto queda vacio y no se manda ningun encabezado extra.

    Se acepta LLM_WORKSPACE_ID (la convencion LLM_* de este proyecto) y tambien
    ANTHROPIC_WORKSPACE_ID, que es la que usa el propio SDK.
    """
    return (
        os.environ.get("LLM_WORKSPACE_ID", "").strip()
        or os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    )


def _cliente(clave: str) -> anthropic.Anthropic:
    """Cliente del SDK con el timeout y los reintentos del proyecto.

    Se construye por llamada y no a nivel de modulo: asi los tests pueden
    cambiar las variables de entorno sin arrastrar un cliente ya configurado
    con la clave anterior.
    """
    workspace = _workspace()
    return anthropic.Anthropic(
        api_key=clave,
        timeout=TIMEOUT_SEGUNDOS,
        max_retries=REINTENTOS,
        # El SDK no tiene un parametro para esto en el cliente directo, pero si
        # expone default_headers, que es donde vive el encabezado.
        default_headers={"anthropic-workspace-id": workspace} if workspace else None,
    )


def _texto_de(respuesta) -> str:
    """Extrae el texto de la respuesta.

    `content` es una LISTA de bloques, no un string: segun el modelo y la
    configuracion puede traer bloques de razonamiento antes del texto. Se
    concatenan solo los de tipo "text" en vez de asumir que content[0] es el
    que interesa.
    """
    partes = [bloque.text for bloque in respuesta.content if bloque.type == "text"]
    texto = "\n\n".join(parte.strip() for parte in partes if parte.strip())
    if not texto:
        raise LLMError("El proveedor devolvio una respuesta sin texto")
    return texto


def preguntar(pregunta: str, contexto: list[dict]) -> tuple[str, str]:
    """Le pregunta al LLM usando UNICAMENTE el contexto entregado.

    Devuelve (respuesta, modelo). El SDK reintenta solo ante errores
    transitorios (429, 5xx, fallo de red) y no ante 401 o 400, que son errores
    del cliente frente al proveedor y repetirlos no cambia el resultado.

    El prompt de sistema viaja en el parametro `system` y no como un mensaje
    mas: en la Messages API las instrucciones del operador son un campo aparte
    de la conversacion, asi que lo que escriba el usuario no puede hacerse
    pasar por una instruccion del sistema.
    """
    clave, modelo = _configuracion()

    try:
        respuesta = _cliente(clave).messages.create(
            model=modelo,
            max_tokens=MAXIMO_TOKENS_RESPUESTA,
            system=PROMPT_SISTEMA,
            messages=[{"role": "user", "content": construir_prompt_usuario(pregunta, contexto)}],
        )
    except anthropic.APITimeoutError as error:
        _log.warning("El proveedor del LLM no respondio en %ss", TIMEOUT_SEGUNDOS)
        raise LLMTimeout("El proveedor del LLM no respondio a tiempo") from error
    except anthropic.RateLimitError as error:
        _log.warning("El proveedor del LLM aplico un limite de tasa")
        raise LLMRateLimit("El proveedor del LLM aplico un limite de tasa") from error
    except anthropic.AuthenticationError as error:
        _log.error("Credenciales del LLM rechazadas: %s", error)
        raise LLMError("Credenciales invalidas para el proveedor del LLM") from error
    except anthropic.APIStatusError as error:
        # No se propaga el mensaje del proveedor al cliente: la ruta responde
        # 503 con un texto propio. Pero SI se registra, porque un 400 casi
        # siempre es configuracion nuestra (modelo mal escrito, falta el
        # workspace) y sin el mensaje no hay forma de saberlo.
        _log.error("El proveedor del LLM devolvio %s: %s", error.status_code, error)
        raise LLMError(f"El proveedor del LLM devolvio {error.status_code}") from error
    except anthropic.APIConnectionError as error:
        _log.error("No se pudo contactar al proveedor del LLM: %s", error)
        raise LLMError("No se pudo contactar al proveedor del LLM") from error

    # El modelo puede declinar la peticion por politica de contenido: llega un
    # 200 con stop_reason "refusal" y sin texto util. Se trata como falla del
    # proveedor (503) en vez de devolverle al usuario una respuesta vacia.
    if getattr(respuesta, "stop_reason", None) == "refusal":
        raise LLMError("El proveedor del LLM declino responder la peticion")

    # Se devuelve el modelo que informa la RESPUESTA y no el que se pidio: si
    # el proveedor resolvio un alias, en el dashboard queda el que de verdad
    # contesto.
    return _texto_de(respuesta), getattr(respuesta, "model", modelo)
