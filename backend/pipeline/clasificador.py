"""Clasificador tematico determinista basado en palabras clave."""

import re
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


def _variantes(clave: str) -> list[str]:
    """La clave y sus formas de numero, singular y plural.

    temas.yml lista casi todo en singular, y el espanol periodistico usa el
    plural de forma masiva: "robos", "elecciones", "hospitales", "precios",
    "bandas", "policias". Antes se exigia el token exacto, asi que
    "Detienen a tres policias por robos" no calzaba con ninguna clave y caia
    en "otros" -- mientras "Detienen a un policia por robo" puntuaba 4.0. Esa
    es la causa raiz del peso desmedido que tenia el tema "otros", que la
    propia vista de comparativa marca como senal de alarma.

    Se generan las dos direcciones porque el catalogo mezcla numeros: de
    "robo" salen "robos"/"roboes", y de "elecciones" sale "eleccion".
    """
    formas = {clave}
    formas.add(f"{clave}s")
    formas.add(f"{clave}es")
    if clave.endswith("es") and len(clave) > 3:
        formas.add(clave[:-2])
    if clave.endswith("s") and len(clave) > 2:
        formas.add(clave[:-1])
    # De mas largo a mas corto para que la alternancia del regex prefiera la
    # forma mas especifica y no corte el token a la mitad.
    return sorted(formas, key=len, reverse=True)


@lru_cache(maxsize=512)
def _patron(clave: str) -> re.Pattern[str]:
    """Regex de token completo para una clave, con sus variantes de numero.

    Se usan lookarounds y no separadores de espacio consumidos, que era el otro
    defecto del conteo anterior: `" robo robo ".count(" robo ")` devuelve 1 y no
    2, porque str.count no se solapa y el espacio del medio se consume una sola
    vez. Con lookarounds, dos claves adyacentes cuentan dos veces.
    """
    alternancia = "|".join(re.escape(v) for v in _variantes(clave))
    return re.compile(rf"(?<![a-z0-9])(?:{alternancia})(?![a-z0-9])")


def _coincidencias(texto: str, clave: str) -> int:
    if not texto or not clave:
        return 0
    return len(_patron(clave).findall(texto))


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
