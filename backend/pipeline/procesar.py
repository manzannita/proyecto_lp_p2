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


# Centinela para las filas que fallaron por un motivo NO atribuible a la
# noticia. No es un tema: le dice al bucle que deje la fila intacta.
FALLO = None


def _clasificar_fila(fila: pd.Series) -> tuple[str | None, float]:
    """Clasifica una fila. Distingue dos clases de problema, que no son lo mismo.

    NOTICIA INVALIDA (titular vacio): "otros" y se registra. Es permanente --
    ese titular no va a mejorar en la proxima corrida-- asi que dejarla
    pendiente para siempre solo la acumularia como ruido en el contador de
    sin_clasificar. Este es el comportamiento que ya existia y que cubre
    test_noticia_invalida_cae_en_otros_y_se_registra.

    CUALQUIER OTRO FALLO (un temas.yml mal formado, un KeyError, un bug):
    devuelve FALLO y la fila queda SIN TOCAR. Antes tambien caia en "otros" con
    clasificado_en escrito, y como el bucle solo reintenta las filas con
    tema_id IS NULL, la noticia quedaba etiquetada "otros" PARA SIEMPRE e
    indistinguible de una clasificacion legitima: un fallo transitorio en medio
    de una corrida podia convertir el lote entero en "otros" sin que el resumen
    de la CLI reportara un solo error. Ahora sigue pendiente y se reintenta.
    """
    identificador = fila.get("id")
    titular = fila.get("titular")

    if titular is None or not str(titular).strip():
        LOG.error("Noticia %s no pudo clasificarse: titular vacio", identificador)
        return "otros", 0

    try:
        return clasificar(titular, fila.get("resumen"))
    except Exception as error:
        LOG.error(
            "Noticia %s no pudo clasificarse (%s: %s). Queda pendiente.",
            identificador, type(error).__name__, error,
        )
        return FALLO, 0.0


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
    fallidas = 0
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
            if slug is FALLO:
                # Se deja pendiente a proposito: la proxima corrida la reintenta.
                fallidas += 1
                continue
            actualizaciones.append((temas[slug], ahora, int(id_noticia)))
            conteos[slug] += 1
        if actualizaciones:
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
        # Se reporta para que la CLI no pueda decir "Procesadas: 500" ocultando
        # 500 fallos silenciosos.
        "fallidas": fallidas,
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
    if resultado["fallidas"]:
        print(f"NO CLASIFICADAS por error: {resultado['fallidas']} "
              f"(quedan pendientes, se reintentan en la proxima corrida; ver el log)")
    print(f"Tiempo total: {resultado['segundos']:.3f} s")


if __name__ == "__main__":
    main()
