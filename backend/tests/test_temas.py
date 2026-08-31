"""Tests del catalogo de temas (GET /api/temas)."""


def test_exige_api_key(cliente):
    assert cliente.get("/api/temas").status_code == 401


def test_devuelve_el_catalogo_completo(cliente_auth):
    respuesta = cliente_auth.get("/api/temas")
    assert respuesta.status_code == 200

    temas = respuesta.get_json()
    slugs = [tema["slug"] for tema in temas]
    assert slugs == [
        "politica",
        "economia",
        "seguridad",
        "salud",
        "deportes",
        "clima",
        "internacional",
        "otros",
    ]


def test_conserva_el_orden_del_catalogo_y_no_el_del_volumen(cliente_auth):
    """El dashboard asigna color por posicion: el orden no puede depender de los datos."""
    temas = cliente_auth.get("/api/temas").get_json()

    assert [tema["id"] for tema in temas] == sorted(tema["id"] for tema in temas)
    # En la semilla 'economia' tiene mas noticias que 'politica' y aun asi va despues.
    posicion = {tema["slug"]: indice for indice, tema in enumerate(temas)}
    assert posicion["politica"] < posicion["economia"]


def test_incluye_el_volumen_de_cada_tema(cliente_auth):
    temas = {tema["slug"]: tema for tema in cliente_auth.get("/api/temas").get_json()}

    # La semilla tiene 6 de seguridad y 7 de economia (ver conftest.SEMILLA).
    assert temas["seguridad"]["total_noticias"] == 6
    assert temas["economia"]["total_noticias"] == 7


def test_un_tema_sin_noticias_aparece_en_cero(cliente_auth):
    """LEFT JOIN y no JOIN: el selector tiene que listar el catalogo entero."""
    temas = {tema["slug"]: tema for tema in cliente_auth.get("/api/temas").get_json()}
    assert temas["otros"]["total_noticias"] == 0
