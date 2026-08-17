"""Fixtures compartidas por los tests de los tres issues.

Los issues #2 y #3 REUTILIZAN estas fixtures y no las modifican. Asi nadie
necesita esperar a que el scraper traiga datos reales para poder testear.

Fixtures disponibles:
    bd_temporal  -> ruta a una BD SQLite recien creada y sembrada
    app          -> app Flask en modo testing apuntando a esa BD
    cliente      -> test client SIN el header de API key
    cliente_auth -> test client CON el header X-API-Key ya puesto
    API_KEY      -> la clave usada en los tests
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.app import crear_app
from backend.db import inicializar_bd

RAIZ = Path(__file__).resolve().parent.parent.parent
SCHEMA = RAIZ / "schema.sql"

API_KEY = "clave-de-pruebas"

# Datos sembrados: (slug_medio, slug_tema | None, titular, dias_atras)
# Cubren dos medios, varios temas y ~4 semanas, para que sirvan tanto al
# ranking de temas (#1) como a la comparativa (#2) y a las series (#3).
SEMILLA = [
    # --- El Universo ---
    ("el-universo", "seguridad", "Operativo policial deja seis detenidos en Duran", 1),
    ("el-universo", "seguridad", "Fiscalia investiga caso de extorsion en el norte", 3),
    ("el-universo", "seguridad", "Decomisan armas en un allanamiento", 9),
    ("el-universo", "seguridad", "Nueva banda desarticulada en Manabi", 16),
    ("el-universo", "politica", "Asamblea aprueba en primer debate la reforma", 2),
    ("el-universo", "politica", "Consejo electoral define calendario", 8),
    ("el-universo", "politica", "Ministro comparece ante la comision", 15),
    ("el-universo", "economia", "El precio del combustible sube este mes", 4),
    ("el-universo", "economia", "Exportaciones de banano crecen 5%", 11),
    ("el-universo", "deportes", "Barcelona SC empata en el Monumental", 5),
    ("el-universo", "clima", "Lluvias intensas se esperan en la Sierra", 6),
    ("el-universo", "salud", "Campana de vacunacion llega a Los Rios", 12),
    ("el-universo", "internacional", "Cumbre regional cierra con acuerdos", 18),
    ("el-universo", None, "Titular todavia sin clasificar del universo", 2),
    # --- Primicias ---
    ("primicias", "economia", "El Banco Central revisa la proyeccion de crecimiento", 1),
    ("primicias", "economia", "Inversion extranjera cae en el primer semestre", 3),
    ("primicias", "economia", "Nuevo impuesto entra en vigencia", 7),
    ("primicias", "economia", "Inflacion anual se ubica en 1,8%", 14),
    ("primicias", "economia", "Deuda externa alcanza cifra record", 20),
    ("primicias", "politica", "Gobierno anuncia cambios en el gabinete", 2),
    ("primicias", "politica", "Oposicion pide juicio politico", 10),
    ("primicias", "seguridad", "Incendio estructural moviliza a bomberos", 1),
    ("primicias", "seguridad", "Refuerzan controles en la frontera norte", 13),
    ("primicias", "clima", "Alerta por oleaje en la costa", 5),
    ("primicias", "clima", "Incendios forestales afectan Pululahua", 6),
    ("primicias", "salud", "Hospital publico amplia su capacidad", 17),
    ("primicias", "deportes", "Seleccion define su nomina", 21),
    ("primicias", None, "Titular todavia sin clasificar de primicias", 4),
]


def _sembrar(ruta: str) -> None:
    ahora = datetime.now(timezone.utc)
    conexion = sqlite3.connect(ruta)
    conexion.execute("PRAGMA foreign_keys = ON")
    try:
        medios = dict(conexion.execute("SELECT slug, id FROM medios").fetchall())
        temas = dict(conexion.execute("SELECT slug, id FROM temas").fetchall())

        filas = []
        for indice, (medio, tema, titular, dias) in enumerate(SEMILLA):
            publicada = (ahora - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
            filas.append(
                (
                    medios[medio],
                    temas[tema] if tema else None,
                    titular,
                    f"Resumen de prueba para: {titular}",
                    f"https://ejemplo.test/{medio}/nota-{indice}",
                    f"hash-de-prueba-{indice:03d}",
                    None,
                    publicada,
                    ahora.strftime("%Y-%m-%d %H:%M:%S"),
                    publicada if tema else None,
                )
            )

        conexion.executemany(
            """
            INSERT INTO noticias (
                medio_id, tema_id, titular, resumen, url, url_hash,
                categoria_origen, fecha_publicacion, fecha_recoleccion,
                clasificado_en
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            filas,
        )
        conexion.commit()
    finally:
        conexion.close()


@pytest.fixture
def bd_temporal(tmp_path) -> str:
    """BD SQLite nueva por test, creada desde schema.sql y sembrada."""
    ruta = str(tmp_path / "prueba.db")
    inicializar_bd(ruta, SCHEMA)
    _sembrar(ruta)
    return ruta


@pytest.fixture
def app(bd_temporal, monkeypatch):
    monkeypatch.setenv("API_KEY", API_KEY)
    return crear_app(testing=True, database_url=bd_temporal)


@pytest.fixture
def cliente(app):
    """Cliente sin credenciales: sirve para probar los 401."""
    return app.test_client()


@pytest.fixture
def cliente_auth(app):
    """Cliente con el header X-API-Key ya configurado."""
    cliente = app.test_client()
    cliente.environ_base["HTTP_X_API_KEY"] = API_KEY
    return cliente
