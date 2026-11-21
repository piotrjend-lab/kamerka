"""Wczytywanie konfiguracji z config.toml (lub config.example.toml jako domyślnej)."""
from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

KATALOG = Path(__file__).resolve().parent.parent


@lru_cache
def konfiguracja() -> dict:
    sciezka = Path(os.environ.get("FV_CONFIG", KATALOG / "config.toml"))
    if not sciezka.exists():
        sciezka = KATALOG / "config.example.toml"
    with open(sciezka, "rb") as f:
        return tomllib.load(f)


def katalog_danych() -> Path:
    d = Path(os.environ.get("FV_DANE", KATALOG / "dane"))
    (d / "skany").mkdir(parents=True, exist_ok=True)
    return d
