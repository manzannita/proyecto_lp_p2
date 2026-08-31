"""Verifica la configuracion del asistente de IA contra el proveedor real.

    python -m backend.verificar_llm

Existe porque un fallo del asistente se ve SIEMPRE igual desde el dashboard:
"El asistente no esta disponible en este momento". Eso es correcto de cara al
usuario -- no se le filtra el detalle del proveedor -- pero deja a quien
desarrolla sin nada con lo que trabajar. Este script hace el diagnostico:
distingue una variable que falta, de una clave rechazada, de un modelo mal
escrito, de una organizacion que exige workspace, de un problema de red.

Nunca imprime la clave. De ella solo muestra el prefijo, el largo y una huella
sha256 recortada, que sirve para confirmar que el .env cambio de verdad sin
revelar el secreto.

No consume cuota salvo en el ultimo paso, que manda un mensaje de 8 tokens.
"""

import hashlib
import os
import sys

import anthropic

from backend.config import obtener_config


def _huella(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()[:8]


def _titulo(texto: str) -> None:
    print(f"\n{texto}")
    print("-" * len(texto))


def main() -> int:
    obtener_config()  # carga el .env

    clave = os.environ.get("LLM_API_KEY", "").strip()
    modelo = os.environ.get("LLM_MODELO", "").strip()
    workspace = (
        os.environ.get("LLM_WORKSPACE_ID", "").strip()
        or os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    )

    _titulo("1. Configuracion leida del .env")
    if clave:
        print(f"   LLM_API_KEY       {clave[:11]}... ({len(clave)} caracteres, huella {_huella(clave)})")
    else:
        print("   LLM_API_KEY       FALTA")
    print(f"   LLM_MODELO        {modelo or 'FALTA'}")
    print(f"   LLM_WORKSPACE_ID  {workspace or '(vacio - solo hace falta si la clave lo exige)'}")

    if not clave or not modelo:
        print("\n   -> Completa las dos variables en .env (ver .env.example) y volve a correr.")
        return 1

    cliente = anthropic.Anthropic(
        api_key=clave,
        max_retries=0,
        default_headers={"anthropic-workspace-id": workspace} if workspace else None,
    )

    _titulo("2. Autenticacion (GET /v1/models, no consume tokens)")
    try:
        modelos = cliente.models.list(limit=40)
    except anthropic.AuthenticationError:
        print("   FALLA: el proveedor rechazo la clave (401).")
        print("   -> La clave no es valida o fue revocada. Genera una nueva en")
        print("      console.anthropic.com > Settings > API keys.")
        return 1
    except anthropic.BadRequestError as error:
        print(f"   FALLA (400): {error}")
        if "workspace" in str(error).lower():
            print("\n   -> Tu clave esta ligada a una identidad dentro de una organizacion")
            print("      que usa workspaces, y hay que decirle en cual actua.")
            print("      Pone el id en LLM_WORKSPACE_ID (empieza con wrkspc_).")
            print("      Esta en console.anthropic.com > Settings > Workspaces:")
            print("      al abrir uno, el id aparece en la URL. Si la organizacion es")
            print("      de otra persona, pedile el id o que te genere una clave")
            print("      creada DENTRO de un workspace.")
        return 1
    except anthropic.PermissionDeniedError as error:
        print(f"   FALLA (403): {error}")
        print("   -> La clave existe pero no tiene permiso para este recurso.")
        return 1
    except anthropic.APIConnectionError as error:
        print(f"   FALLA de red: {error}")
        print("   -> Revisa la conexion o el proxy.")
        return 1

    disponibles = [m.id for m in modelos.data]
    print(f"   OK. {len(disponibles)} modelos visibles para esta clave.")
    for identificador in disponibles:
        marca = "  <-- el configurado" if identificador == modelo else ""
        print(f"      {identificador}{marca}")

    if modelo not in disponibles:
        # OJO: no figurar en el listado NO prueba que el id sea invalido. Los
        # alias estables (claude-haiku-4-5) resuelven a una version concreta
        # sin aparecer en la lista, que devuelve las instantaneas fechadas
        # (claude-haiku-4-5-20251001). Es una pista, no un veredicto: el que
        # lo decide de verdad es el paso 3.
        print(f"\n   Nota: '{modelo}' no figura en el listado.")
        print("   -> Puede ser un alias, que no siempre aparece; el paso 3 decide.")
        parecidos = [d for d in disponibles if d.startswith(modelo)]
        if parecidos:
            print(f"   -> Si el paso 3 falla por el modelo, usa: {parecidos[0]}")

    _titulo("3. Mensaje de prueba (consume ~10 tokens)")
    try:
        respuesta = cliente.messages.create(
            model=modelo,
            max_tokens=16,
            messages=[{"role": "user", "content": "Responde solamente: listo"}],
        )
    except anthropic.RateLimitError:
        print("   FALLA (429): limite de tasa o saldo agotado.")
        print("   -> Revisa el saldo en console.anthropic.com > Billing. Una")
        print("      suscripcion a Claude NO es credito de API: se cargan aparte.")
        return 1
    except anthropic.NotFoundError as error:
        print(f"   FALLA (404): {error}")
        print(f"   -> El modelo '{modelo}' no existe para esta cuenta. Usa uno")
        print("      de los que listo el paso 2, tal cual aparece ahi.")
        return 1
    except anthropic.APIStatusError as error:
        print(f"   FALLA ({error.status_code}): {error}")
        if "credit balance" in str(error).lower():
            # Anthropic manda esto como 400, NO como 429: sin este caso
            # aparte, la falta de saldo se confunde con un error de formato.
            print("\n   -> La cuenta no tiene saldo de API.")
            print("      Se carga en console.anthropic.com > Plans & Billing.")
            print("      Una suscripcion a Claude no es credito de API.")
        return 1

    texto = " ".join(b.text.strip() for b in respuesta.content if b.type == "text")
    print(f"   OK. El modelo {respuesta.model} respondio: {texto!r}")
    print(f"   Tokens: {respuesta.usage.input_tokens} de entrada, "
          f"{respuesta.usage.output_tokens} de salida.")

    print("\nTODO EN ORDEN: el asistente puede responder.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
