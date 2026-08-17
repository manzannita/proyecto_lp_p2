"""Acceso a la base de datos compartido por todo el backend.

Todo el equipo usa estos helpers; nadie abre conexiones por su cuenta. Asi la
politica de transacciones y de row factory es una sola en todo el proyecto.

Reglas del proyecto:
  - Toda escritura pasa por transaccion(): commit al salir bien, ROLLBACK ante
    cualquier excepcion.
  - Toda consulta usa placeholders (?), nunca interpolacion de strings.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from flask import current_app, g


def _ruta_bd() -> str:
    return current_app.config["DATABASE_URL"]


def _conectar(ruta: str) -> sqlite3.Connection:
    conexion = sqlite3.connect(ruta, timeout=10, isolation_level=None)
    # Devolver dicts en vez de tuplas: los endpoints serializan a JSON directo.
    conexion.row_factory = sqlite3.Row
    # Las FK no se aplican por defecto en SQLite; sin esto ON DELETE es letra muerta.
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


def obtener_conexion() -> sqlite3.Connection:
    """Conexion reutilizada durante toda la peticion actual de Flask."""
    if "conexion_bd" not in g:
        g.conexion_bd = _conectar(_ruta_bd())
    return g.conexion_bd


def cerrar_conexion(_excepcion: BaseException | None = None) -> None:
    """Registrado como teardown_appcontext en la factory."""
    conexion = g.pop("conexion_bd", None)
    if conexion is not None:
        conexion.close()


@contextmanager
def transaccion() -> Iterator[sqlite3.Connection]:
    """Agrupa varias escrituras en una unidad atomica.

    Uso:
        with transaccion() as conexion:
            conexion.execute("UPDATE ...", (valor, id_))

    Si el bloque lanza cualquier excepcion se hace ROLLBACK y la excepcion se
    vuelve a lanzar: la base nunca queda con escrituras a medias.
    """
    conexion = obtener_conexion()
    conexion.execute("BEGIN")
    try:
        yield conexion
    except BaseException:
        conexion.execute("ROLLBACK")
        raise
    else:
        conexion.execute("COMMIT")


def consultar(sql: str, parametros: tuple[Any, ...] = ()) -> list[dict]:
    """Ejecuta un SELECT parametrizado y devuelve una lista de dicts."""
    filas = obtener_conexion().execute(sql, parametros).fetchall()
    return [dict(fila) for fila in filas]


def consultar_uno(sql: str, parametros: tuple[Any, ...] = ()) -> dict | None:
    fila = obtener_conexion().execute(sql, parametros).fetchone()
    return dict(fila) if fila is not None else None


def inicializar_bd(ruta: str, schema: Path) -> None:
    """Crea las tablas y las semillas ejecutando schema.sql.

    Es idempotente: schema.sql usa CREATE TABLE IF NOT EXISTS e
    INSERT OR IGNORE, asi que correrlo dos veces no duplica nada.
    """
    conexion = _conectar(ruta)
    try:
        conexion.executescript(schema.read_text(encoding="utf-8"))
    finally:
        conexion.close()
