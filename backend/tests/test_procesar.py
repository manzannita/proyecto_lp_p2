import sqlite3

import pandas as pd
import pytest

from backend.pipeline.procesar import _clasificar_fila, procesar


def _escalar(ruta: str, sql: str):
    conexion = sqlite3.connect(ruta)
    try:
        return conexion.execute(sql).fetchone()[0]
    finally:
        conexion.close()


def test_procesa_todas_las_pendientes(app, bd_temporal):
    with app.app_context():
        resultado = procesar(lote=1)
    assert resultado["procesadas"] == 2
    assert _escalar(bd_temporal, "SELECT COUNT(*) FROM noticias WHERE tema_id IS NULL") == 0


def test_segunda_corrida_es_idempotente_y_reclasificar_procesa_todas(app):
    with app.app_context():
        primera = procesar()
        segunda = procesar()
        tercera = procesar(reclasificar=True)
    assert primera["procesadas"] == 2
    assert segunda["procesadas"] == 0
    assert tercera["procesadas"] == 28


def test_noticia_invalida_cae_en_otros_y_se_registra(caplog):
    slug, score = _clasificar_fila(pd.Series({"id": 99, "titular": None, "resumen": ""}))
    assert (slug, score) == ("otros", 0)
    assert "Noticia 99 no pudo clasificarse" in caplog.text


def test_fallo_a_mitad_del_lote_hace_rollback(app, bd_temporal):
    conexion = sqlite3.connect(bd_temporal)
    try:
        pendientes = [
            fila[0]
            for fila in conexion.execute(
                "SELECT id FROM noticias WHERE tema_id IS NULL ORDER BY id"
            )
        ]
        conexion.execute(
            f"""
            CREATE TRIGGER fallo_controlado
            BEFORE UPDATE OF tema_id ON noticias
            WHEN OLD.id = {pendientes[1]}
            BEGIN
                SELECT RAISE(ABORT, 'fallo controlado');
            END
            """
        )
        conexion.commit()
    finally:
        conexion.close()

    with app.app_context(), pytest.raises(sqlite3.IntegrityError, match="fallo controlado"):
        procesar(lote=500)

    assert _escalar(bd_temporal, "SELECT COUNT(*) FROM noticias WHERE tema_id IS NULL") == 2
