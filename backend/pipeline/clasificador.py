"""Clasificador tematico determinista basado en palabras clave."""

from functools import lru_cache
from pathlib import Path

import yaml

from backend.pipeline.normalizador import normalizar

RUTA_TEMAS = Path(__file__).with_name("temas.yml")
UMBRAL_MINIMO = 1.0


@lru_cache(maxsize=1)
def cargar_temas() -> dict[str, dict]:
    with RUTA_TEMAS.open(encoding="utf-8") as archivo:
        catalogo = yaml.safe_load(archivo) or {}
    if "otros" not in catalogo:
        raise ValueError("temas.yml debe declarar el tema 'otros'")
    return catalogo


def _coincidencias(texto: str, clave: str) -> int:
    if not texto or not clave:
        return 0
    return f" {texto} ".count(f" {clave} ")


def clasificar(titular: object, resumen: object) -> tuple[str, float]:
    titulo_normalizado = normalizar(titular)
    resumen_normalizado = normalizar(resumen)
    candidatos: list[tuple[float, int, str]] = []
    for slug, reglas in cargar_temas().items():
        if slug == "otros":
            continue
        peso = float(reglas.get("peso", 1.0))
        score = sum(
            (2 * _coincidencias(titulo_normalizado, normalizar(clave))
             + _coincidencias(resumen_normalizado, normalizar(clave))) * peso
            for clave in reglas.get("claves", [])
        )
        candidatos.append((score, -int(reglas.get("prioridad", 999)), slug))
    mejor_score, _prioridad, mejor_slug = max(candidatos, default=(0.0, 0, "otros"))
    if mejor_score < UMBRAL_MINIMO:
        return "otros", 0
    return mejor_slug, mejor_score
