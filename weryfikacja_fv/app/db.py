"""Prosta baza SQLite: faktury (z wynikiem weryfikacji) i zamówienia pobrane z portalu."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from .config import katalog_danych
from .models import Faktura, WynikWeryfikacji, Zamowienie

SCHEMAT = """
CREATE TABLE IF NOT EXISTS faktury (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazwa_pliku TEXT NOT NULL,
    plik TEXT NOT NULL,
    zrodlo_odczytu TEXT,
    dane TEXT NOT NULL,
    wynik TEXT,
    status TEXT,
    utworzono TEXT NOT NULL,
    zatwierdzona INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS zamowienia (
    numer TEXT PRIMARY KEY,
    dane TEXT NOT NULL,
    pobrano TEXT NOT NULL
);
"""


@contextmanager
def polaczenie():
    con = sqlite3.connect(katalog_danych() / "baza.sqlite")
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMAT)
        yield con
        con.commit()
    finally:
        con.close()


def _teraz() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------- faktury ----------

def dodaj_fakture(nazwa_pliku: str, plik: str, zrodlo: str, faktura: Faktura) -> int:
    with polaczenie() as con:
        cur = con.execute(
            "INSERT INTO faktury (nazwa_pliku, plik, zrodlo_odczytu, dane, utworzono) VALUES (?,?,?,?,?)",
            (nazwa_pliku, plik, zrodlo, faktura.model_dump_json(), _teraz()),
        )
        return cur.lastrowid


def zapisz_dane_faktury(fid: int, faktura: Faktura) -> None:
    with polaczenie() as con:
        con.execute("UPDATE faktury SET dane=? WHERE id=?", (faktura.model_dump_json(), fid))


def zapisz_wynik(fid: int, wynik: WynikWeryfikacji) -> None:
    with polaczenie() as con:
        con.execute(
            "UPDATE faktury SET wynik=?, status=? WHERE id=?",
            (wynik.model_dump_json(), wynik.status, fid),
        )


def zatwierdz(fid: int, wartosc: bool) -> None:
    with polaczenie() as con:
        con.execute("UPDATE faktury SET zatwierdzona=? WHERE id=?", (1 if wartosc else 0, fid))


def usun_fakture(fid: int) -> str | None:
    with polaczenie() as con:
        r = con.execute("SELECT plik FROM faktury WHERE id=?", (fid,)).fetchone()
        con.execute("DELETE FROM faktury WHERE id=?", (fid,))
        return r["plik"] if r else None


def _wiersz_faktury(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "nazwa_pliku": r["nazwa_pliku"],
        "plik": r["plik"],
        "zrodlo_odczytu": r["zrodlo_odczytu"],
        "dane": json.loads(r["dane"]),
        "wynik": json.loads(r["wynik"]) if r["wynik"] else None,
        "status": r["status"],
        "utworzono": r["utworzono"],
        "zatwierdzona": bool(r["zatwierdzona"]),
    }


def faktura(fid: int) -> dict | None:
    with polaczenie() as con:
        r = con.execute("SELECT * FROM faktury WHERE id=?", (fid,)).fetchone()
        return _wiersz_faktury(r) if r else None


def faktury() -> list[dict]:
    with polaczenie() as con:
        return [_wiersz_faktury(r) for r in con.execute("SELECT * FROM faktury ORDER BY id DESC")]


# ---------- zamówienia ----------

def zapisz_zamowienia(lista: list[Zamowienie]) -> int:
    with polaczenie() as con:
        for z in lista:
            con.execute(
                "INSERT INTO zamowienia (numer, dane, pobrano) VALUES (?,?,?) "
                "ON CONFLICT(numer) DO UPDATE SET dane=excluded.dane, pobrano=excluded.pobrano",
                (z.numer, z.model_dump_json(), _teraz()),
            )
    return len(lista)


def zamowienia() -> dict[str, Zamowienie]:
    with polaczenie() as con:
        return {
            r["numer"]: Zamowienie.model_validate_json(r["dane"])
            for r in con.execute("SELECT * FROM zamowienia ORDER BY numer")
        }


def ostatnia_synchronizacja() -> str | None:
    with polaczenie() as con:
        r = con.execute("SELECT MAX(pobrano) AS m FROM zamowienia").fetchone()
        return r["m"]
