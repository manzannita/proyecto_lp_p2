"""Tests de POST /api/asistente/preguntar (issue #3).

Ningun test llama al proveedor real: backend.services.asistente_ia.preguntar
se reemplaza con monkeypatch, asi que no se gasta cuota ni se requiere red.
"""

from backend.services import asistente_ia

RUTA = "/api/asistente/preguntar"


# --------------------------------------------------------------------------
# Seguridad
# --------------------------------------------------------------------------

def test_sin_api_key_devuelve_401(cliente):
    respuesta = cliente.post(RUTA, json={"pregunta": "algo"})
    assert respuesta.status_code == 401


def test_intento_de_inyeccion_sql_no_rompe_la_base(cliente_auth, app):
    respuesta = cliente_auth.post(RUTA, json={"pregunta": "'; DROP TABLE noticias;--"})
    assert respuesta.status_code == 200

    with app.app_context():
        from backend.db import consultar_uno

        assert consultar_uno("SELECT COUNT(*) AS n FROM noticias")["n"] > 0


# --------------------------------------------------------------------------
# Validacion de parametros
# --------------------------------------------------------------------------

def test_body_sin_pregunta_devuelve_400(cliente_auth):
    respuesta = cliente_auth.post(RUTA, json={})
    assert respuesta.status_code == 400


def test_pregunta_vacia_devuelve_400(cliente_auth):
    respuesta = cliente_auth.post(RUTA, json={"pregunta": "   "})
    assert respuesta.status_code == 400


def test_pregunta_demasiado_larga_devuelve_400(cliente_auth):
    respuesta = cliente_auth.post(RUTA, json={"pregunta": "a" * 501})
    assert respuesta.status_code == 400


def test_limite_contexto_no_numerico_devuelve_400(cliente_auth):
    respuesta = cliente_auth.post(
        RUTA, json={"pregunta": "algo", "limite_contexto": "cinco"}
    )
    assert respuesta.status_code == 400


def test_limite_contexto_fuera_de_rango_devuelve_400(cliente_auth):
    assert cliente_auth.post(
        RUTA, json={"pregunta": "algo", "limite_contexto": 0}
    ).status_code == 400
    assert cliente_auth.post(
        RUTA, json={"pregunta": "algo", "limite_contexto": 999}
    ).status_code == 400


# --------------------------------------------------------------------------
# Cortocircuito sin contexto
# --------------------------------------------------------------------------

def test_sin_noticias_relacionadas_no_llama_al_llm(cliente_auth, monkeypatch):
    llamadas = []

    def falso_preguntar(pregunta, contexto):
        llamadas.append((pregunta, contexto))
        return "no deberia llegar aqui", "modelo-x"

    monkeypatch.setattr(asistente_ia, "preguntar", falso_preguntar)

    respuesta = cliente_auth.post(
        RUTA, json={"pregunta": "zxqwvbnmzxqwvbnm inexistente qwertyzxqw"}
    )
    assert respuesta.status_code == 200
    datos = respuesta.get_json()
    assert "no tengo datos suficientes" in datos["respuesta"].lower()
    assert datos["fuentes"] == []
    assert datos["noticias_consultadas"] == 0
    assert datos["modelo"] is None
    assert llamadas == []


# --------------------------------------------------------------------------
# Respuesta exitosa fundamentada en noticias reales
# --------------------------------------------------------------------------

def test_responde_citando_fuentes_que_existen_en_la_base(cliente_auth, app, monkeypatch):
    def falso_preguntar(pregunta, contexto):
        assert contexto, "el contexto no deberia estar vacio para esta pregunta"
        return "Segun El Universo, hubo un operativo policial en Duran.", "modelo-de-prueba"

    monkeypatch.setattr(asistente_ia, "preguntar", falso_preguntar)

    respuesta = cliente_auth.post(
        RUTA, json={"pregunta": "Cuentame sobre el operativo policial en Duran"}
    )
    assert respuesta.status_code == 200
    datos = respuesta.get_json()

    assert datos["respuesta"] == "Segun El Universo, hubo un operativo policial en Duran."
    assert datos["modelo"] == "modelo-de-prueba"
    assert datos["noticias_consultadas"] == len(datos["fuentes"])
    assert len(datos["fuentes"]) > 0

    with app.app_context():
        from backend.db import consultar_uno

        for fuente in datos["fuentes"]:
            fila = consultar_uno(
                "SELECT id FROM noticias WHERE url = ? AND titular = ?",
                (fuente["url"], fuente["titular"]),
            )
            assert fila is not None, f"la fuente citada no existe en la base: {fuente}"


def test_respeta_el_limite_de_contexto_solicitado(cliente_auth, monkeypatch):
    def falso_preguntar(pregunta, contexto):
        return "ok", "modelo-x"

    monkeypatch.setattr(asistente_ia, "preguntar", falso_preguntar)

    respuesta = cliente_auth.post(
        RUTA,
        json={
            "pregunta": "Cuentame sobre el operativo policial en Duran",
            "limite_contexto": 1,
        },
    )
    assert respuesta.status_code == 200
    assert respuesta.get_json()["noticias_consultadas"] <= 1


# --------------------------------------------------------------------------
# Errores del proveedor: nunca se filtra el mensaje crudo
# --------------------------------------------------------------------------

def test_timeout_del_proveedor_devuelve_503(cliente_auth, monkeypatch):
    def falso_preguntar(pregunta, contexto):
        raise asistente_ia.LLMTimeout("detalle interno sensible del proveedor")

    monkeypatch.setattr(asistente_ia, "preguntar", falso_preguntar)

    respuesta = cliente_auth.post(
        RUTA, json={"pregunta": "Cuentame sobre el operativo policial en Duran"}
    )
    assert respuesta.status_code == 503
    cuerpo = respuesta.get_data(as_text=True)
    assert respuesta.get_json()["error"] == "El asistente no esta disponible en este momento"
    assert "detalle interno sensible" not in cuerpo


def test_error_generico_del_proveedor_devuelve_503(cliente_auth, monkeypatch):
    def falso_preguntar(pregunta, contexto):
        raise asistente_ia.LLMError("500 Internal Server Error del proveedor")

    monkeypatch.setattr(asistente_ia, "preguntar", falso_preguntar)

    respuesta = cliente_auth.post(
        RUTA, json={"pregunta": "Cuentame sobre el operativo policial en Duran"}
    )
    assert respuesta.status_code == 503
    assert "Internal Server Error" not in respuesta.get_data(as_text=True)


def test_rate_limit_del_proveedor_devuelve_429(cliente_auth, monkeypatch):
    def falso_preguntar(pregunta, contexto):
        raise asistente_ia.LLMRateLimit("rate limited")

    monkeypatch.setattr(asistente_ia, "preguntar", falso_preguntar)

    respuesta = cliente_auth.post(
        RUTA, json={"pregunta": "Cuentame sobre el operativo policial en Duran"}
    )
    assert respuesta.status_code == 429
    assert respuesta.get_json()["error"]


def test_la_app_sigue_en_pie_despues_de_un_error_del_llm(cliente_auth, monkeypatch):
    def falso_preguntar(pregunta, contexto):
        raise asistente_ia.LLMTimeout("boom")

    monkeypatch.setattr(asistente_ia, "preguntar", falso_preguntar)
    cliente_auth.post(RUTA, json={"pregunta": "Cuentame sobre el operativo policial en Duran"})

    # La app sigue respondiendo con normalidad tras el fallo del proveedor.
    respuesta = cliente_auth.get("/health")
    assert respuesta.status_code == 200
