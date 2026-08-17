def test_catalogo_devuelve_medios_y_totales(cliente_auth):
    respuesta = cliente_auth.get("/api/medios")
    assert respuesta.status_code == 200
    assert respuesta.get_json() == [
        {"id": 1, "nombre": "El Universo", "slug": "el-universo", "total_noticias": 14},
        {"id": 2, "nombre": "Primicias", "slug": "primicias", "total_noticias": 14},
    ]


def test_catalogo_requiere_api_key(cliente):
    respuesta = cliente.get("/api/medios")
    assert respuesta.status_code == 401
    assert respuesta.get_json() == {"error": "API key invalida o ausente"}
