"""Crea la base de datos ejecutando schema.sql.

    python -m backend.init_db

Se usa esto en vez de `sqlite3 noticia_ec.db < schema.sql` porque el CLI de
sqlite3 no viene instalado en Windows, mientras que el modulo sqlite3 de
Python si es parte de la libreria estandar. Es idempotente.
"""

import sys

from backend.config import Config
from backend.db import inicializar_bd


def main() -> int:
    config = Config()
    ruta = config.DATABASE_URL
    schema = config.SCHEMA_PATH

    if not schema.exists():
        print(f"ERROR: no se encontro {schema}", file=sys.stderr)
        return 1

    try:
        inicializar_bd(ruta, schema)
    except Exception as error:  # noqa: BLE001 - se reporta y se sale con codigo
        print(f"ERROR al crear la base: {error}", file=sys.stderr)
        return 1

    print(f"Base lista en {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
