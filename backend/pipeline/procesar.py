"""CLI del pipeline: ``python -m backend.pipeline.procesar``."""

import argparse
import logging
import time
from collections import Counter
from datetime import datetime, timezone

import pandas as pd

from backend.app import crear_app
from backend.db import consultar, transaccion
from backend.pipeline.clasificador import cargar_temas, clasificar

LOG = logging.getLogger(__name__)


def _clasificar_fila(fila: pd.Series) -> tuple[str, float]:
    try:
        if fila.get("titular") is None or not str(fila.get("titular")).strip():
            raise ValueError("titular vacio")
        return clasificar(fila.get("titular"), fila.get("resumen"))
    except Exception as error:
        LOG.error("Noticia %s no pudo clasificarse: %s", fila.get("id"), error)
        return "otros", 0


def procesar(lote: int = 500, reclasificar: bool = False) -> dict:
    if lote < 1:
        raise ValueError("El tamano de lote debe ser mayor que cero")
    temas = {fila["slug"]: fila["id"] for fila in consultar("SELECT id, slug FROM temas")}
    faltantes = set(cargar_temas()) - set(temas)
    if faltantes:
        raise RuntimeError(f"Slugs de temas ausentes en la BD: {sorted(faltantes)}")

    ultimo_id = 0
    conteos: Counter[str] = Counter()
    procesadas = 0
    inicio = time.perf_counter()
    while True:
        condicion = "id > ?" if reclasificar else "id > ? AND tema_id IS NULL"
        filas = consultar(
            f"SELECT id, titular, resumen FROM noticias WHERE {condicion} ORDER BY id LIMIT ?",
            (ultimo_id, lote),
        )
        if not filas:
            break
        frame = pd.DataFrame(filas)
        resultados = frame.apply(_clasificar_fila, axis=1)
        ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        actualizaciones = []
        for id_noticia, (slug, _score) in zip(frame["id"], resultados):
            actualizaciones.append((temas[slug], ahora, int(id_noticia)))
            conteos[slug] += 1
        with transaccion() as conexion:
            conexion.executemany(
                "UPDATE noticias SET tema_id = ?, clasificado_en = ? WHERE id = ?",
                actualizaciones,
            )
        procesadas += len(actualizaciones)
        ultimo_id = int(frame["id"].iloc[-1])

    return {
        "procesadas": procesadas,
        "por_tema": dict(sorted(conteos.items())),
        "otros": conteos["otros"],
        "segundos": round(time.perf_counter() - inicio, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Clasifica noticias pendientes por tema")
    parser.add_argument("--lote", type=int, default=500)
    parser.add_argument("--reclasificar", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    app = crear_app()
    with app.app_context():
        resultado = procesar(args.lote, args.reclasificar)
    print(f"Procesadas: {resultado['procesadas']}")
    print("Clasificadas por tema:")
    for tema, total in resultado["por_tema"].items():
        print(f"  {tema}: {total}")
    print(f"Otros: {resultado['otros']}")
    print(f"Tiempo total: {resultado['segundos']:.3f} s")


if __name__ == "__main__":
    main()
