"""Configuracion del backend, leida siempre desde variables de entorno.

Ninguna credencial vive en el repositorio: este modulo carga el archivo .env
local (ignorado por git) y expone los valores ya validados.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent

# encoding="utf-8-sig" y no "utf-8" a proposito: en Windows, PowerShell escribe
# los archivos en UTF-8 CON BOM, y el BOM se pega al nombre de la primera
# variable ("﻿API_KEY"), que entonces nunca se encuentra. utf-8-sig lo
# descarta y funciona igual con archivos sin BOM (Linux/macOS).
load_dotenv(RAIZ / ".env", encoding="utf-8-sig")


class ErrorDeConfiguracion(RuntimeError):
    """Falta una variable de entorno obligatoria."""


def _requerido(nombre: str) -> str:
    valor = os.environ.get(nombre, "").strip()
    if not valor:
        raise ErrorDeConfiguracion(
            f"Falta la variable de entorno {nombre}. "
            f"Copia .env.example a .env y completala."
        )
    return valor


class Config:
    """Configuracion base (desarrollo)."""

    # Ruta al archivo SQLite. En produccion se reemplaza por una URL de
    # PostgreSQL y solo cambia la implementacion de backend/db.py.
    #
    # Una ruta relativa se resuelve contra la RAIZ del repo, no contra el
    # directorio actual, para que el backend y el scraper apunten siempre al
    # mismo archivo sin importar desde donde se los invoque.
    DATABASE_URL = str(RAIZ / os.environ.get("DATABASE_URL", "noticia_ec.db"))
    SCHEMA_PATH = RAIZ / "schema.sql"
    TESTING = False

    @property
    def api_key(self) -> str:
        """Clave que deben enviar los clientes en el header X-API-Key."""
        return _requerido("API_KEY")


class ConfigDePruebas(Config):
    """Configuracion usada por pytest: BD temporal y clave fija."""

    TESTING = True

    @property
    def api_key(self) -> str:
        return os.environ.get("API_KEY", "clave-de-pruebas")


def obtener_config(testing: bool = False) -> Config:
    return ConfigDePruebas() if testing else Config()
