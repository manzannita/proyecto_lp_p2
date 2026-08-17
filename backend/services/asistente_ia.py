"""Cliente del LLM para el asistente de IA generativa.

Proveedor: OpenAI (endpoint de Chat Completions). La clave sale de la
variable de entorno LLM_API_KEY y el modelo de LLM_MODELO; nunca se
hardcodean. Si faltan, el servicio falla al primer uso con un mensaje claro
en vez de romperse a medias de una peticion con un error crudo del proveedor.
"""

import os

import requests

from backend.services.prompts import PROMPT_SISTEMA, construir_prompt_usuario

TIMEOUT_SEGUNDOS = 30
INTENTOS = 2  # 1 intento + 1 reintento ante error transitorio (5xx / timeout)
URL_CHAT_COMPLETIONS = "https://api.openai.com/v1/chat/completions"


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


def preguntar(pregunta: str, contexto: list[dict]) -> tuple[str, str]:
    """Le pregunta al LLM usando UNICAMENTE el contexto entregado.

    Devuelve (respuesta, modelo). Reintenta una vez ante error transitorio
    (5xx o timeout de red); no reintenta ante 401/429, que son errores del
    cliente frente al proveedor y repetirlos no cambia el resultado.
    """
    clave, modelo = _configuracion()

    payload = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": PROMPT_SISTEMA},
            {"role": "user", "content": construir_prompt_usuario(pregunta, contexto)},
        ],
        "temperature": 0.2,
    }
    encabezados = {"Authorization": f"Bearer {clave}", "Content-Type": "application/json"}

    for intento in range(INTENTOS):
        ultimo_intento = intento == INTENTOS - 1
        try:
            respuesta = requests.post(
                URL_CHAT_COMPLETIONS, json=payload, headers=encabezados, timeout=TIMEOUT_SEGUNDOS
            )
        except requests.Timeout as error:
            if ultimo_intento:
                raise LLMTimeout("El proveedor del LLM no respondio a tiempo") from error
            continue
        except requests.RequestException as error:
            if ultimo_intento:
                raise LLMError("No se pudo contactar al proveedor del LLM") from error
            continue

        if respuesta.status_code == 429:
            raise LLMRateLimit("El proveedor del LLM aplico un limite de tasa")
        if respuesta.status_code == 401:
            raise LLMError("Credenciales invalidas para el proveedor del LLM")
        if respuesta.status_code >= 500:
            if ultimo_intento:
                raise LLMError(f"El proveedor del LLM devolvio {respuesta.status_code}")
            continue
        if respuesta.status_code >= 400:
            raise LLMError(f"El proveedor del LLM devolvio {respuesta.status_code}")

        cuerpo = respuesta.json()
        texto = cuerpo["choices"][0]["message"]["content"]
        return texto, modelo

    raise LLMError("No se pudo completar la peticion al LLM")
