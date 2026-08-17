"""Normalizacion de texto en espanol, sin efectos secundarios."""

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

RUTA_STOPWORDS = Path(__file__).with_name("stopwords_es.txt")


def normalizar(texto: object) -> str:
    if texto is None:
        return ""
    descompuesto = unicodedata.normalize("NFKD", str(texto).lower())
    sin_tildes = "".join(c for c in descompuesto if not unicodedata.combining(c))
    sin_puntuacion = re.sub(r"[^a-z0-9\s]", " ", sin_tildes)
    return " ".join(sin_puntuacion.split())


@lru_cache(maxsize=1)
def _stopwords() -> frozenset[str]:
    return frozenset(
        linea.strip()
        for linea in RUTA_STOPWORDS.read_text(encoding="utf-8").splitlines()
        if linea.strip() and not linea.startswith("#")
    )


def tokenizar(texto: object) -> list[str]:
    return [token for token in normalizar(texto).split() if token not in _stopwords()]
