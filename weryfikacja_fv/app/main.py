"""Aplikacja webowa: weryfikacja faktur za usługi spieku względem zamówień z portalu dostawcy.

Uruchomienie:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import csv
import io
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, demo_portal
from .config import katalog_danych, konfiguracja
from .models import Faktura
from .ocr import TYPY_OBRAZOW, BladOdczytu, odczytaj_fakture
from .portal import BladPortalu, importuj_plik, pobierz_zamowienia
from .weryfikacja import weryfikuj

STATIC = Path(__file__).parent / "static"
DOZWOLONE = {".pdf", *TYPY_OBRAZOW}
MAKS_ROZMIAR = 30 * 1024 * 1024

app = FastAPI(title="Weryfikacja faktur - usługi spieku")
app.include_router(demo_portal.router)


def _inne_faktury(fid: int) -> list[Faktura]:
    return [Faktura.model_validate(f["dane"]) for f in db.faktury() if f["id"] != fid]


def _zweryfikuj(fid: int) -> dict:
    rekord = db.faktura(fid)
    wynik = weryfikuj(Faktura.model_validate(rekord["dane"]), db.zamowienia(), _inne_faktury(fid))
    db.zapisz_wynik(fid, wynik)
    return db.faktura(fid)


# ---------------------------------------------------------------- faktury

@app.post("/api/faktury")
async def wgraj_faktury(pliki: list[UploadFile] = File(...)):
    wyniki = []
    for plik in pliki:
        rozszerzenie = Path(plik.filename or "").suffix.lower()
        if rozszerzenie not in DOZWOLONE:
            wyniki.append({"nazwa_pliku": plik.filename, "blad": "Dozwolone pliki: PDF, JPG, PNG, TIFF, WEBP, BMP"})
            continue
        dane = await plik.read()
        if len(dane) > MAKS_ROZMIAR:
            wyniki.append({"nazwa_pliku": plik.filename, "blad": "Plik większy niż 30 MB"})
            continue
        sciezka = katalog_danych() / "skany" / f"{uuid.uuid4().hex}{rozszerzenie}"
        sciezka.write_bytes(dane)
        try:
            faktura, silnik = odczytaj_fakture(sciezka)
        except BladOdczytu as e:
            sciezka.unlink(missing_ok=True)
            wyniki.append({"nazwa_pliku": plik.filename, "blad": str(e)})
            continue
        fid = db.dodaj_fakture(plik.filename, sciezka.name, silnik, faktura)
        wyniki.append(_zweryfikuj(fid))
    return wyniki


@app.get("/api/faktury")
def lista_faktur():
    return db.faktury()


@app.get("/api/faktury/{fid}")
def pobierz_fakture(fid: int):
    if not (f := db.faktura(fid)):
        raise HTTPException(404, "Nie ma takiej faktury")
    return f


@app.put("/api/faktury/{fid}")
def popraw_fakture(fid: int, faktura: Faktura):
    """Ręczna korekta odczytanych danych (gdy OCR się pomylił) i ponowna weryfikacja."""
    if not db.faktura(fid):
        raise HTTPException(404, "Nie ma takiej faktury")
    db.zapisz_dane_faktury(fid, faktura)
    return _zweryfikuj(fid)


@app.post("/api/faktury/{fid}/weryfikuj")
def weryfikuj_ponownie(fid: int):
    if not db.faktura(fid):
        raise HTTPException(404, "Nie ma takiej faktury")
    return _zweryfikuj(fid)


class Zatwierdzenie(BaseModel):
    zatwierdzona: bool


@app.post("/api/faktury/{fid}/zatwierdz")
def zatwierdz(fid: int, z: Zatwierdzenie):
    db.zatwierdz(fid, z.zatwierdzona)
    return db.faktura(fid)


@app.delete("/api/faktury/{fid}")
def usun(fid: int):
    if plik := db.usun_fakture(fid):
        (katalog_danych() / "skany" / plik).unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/faktury/{fid}/plik")
def plik_faktury(fid: int):
    if not (f := db.faktura(fid)):
        raise HTTPException(404)
    return FileResponse(katalog_danych() / "skany" / f["plik"], filename=f["nazwa_pliku"])


@app.post("/api/weryfikuj-wszystkie")
def weryfikuj_wszystkie():
    return [_zweryfikuj(f["id"]) for f in db.faktury()]


@app.get("/api/raport.csv")
def raport():
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Plik", "Numer FV", "Data wystawienia", "Sprzedawca NIP", "Zamówienia", "Netto", "VAT",
                "Brutto", "Status", "Zatwierdzona", "Uwagi"])
    for f in db.faktury():
        d, wyn = f["dane"], f["wynik"] or {"uwagi": []}
        w.writerow([
            f["nazwa_pliku"], d.get("numer"), d.get("data_wystawienia"), d.get("sprzedawca_nip"),
            ", ".join(d.get("numery_zamowien") or []),
            *[str(d.get(k) or "").replace(".", ",") for k in ("suma_netto", "suma_vat", "suma_brutto")],
            f["status"], "tak" if f["zatwierdzona"] else "nie",
            " | ".join(f"[{u['poziom']}] {u['opis']}" for u in wyn["uwagi"] if u["poziom"] != "info"),
        ])
    dane = io.BytesIO(("﻿" + buf.getvalue()).encode("utf-8"))
    return StreamingResponse(dane, media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=raport_faktur.csv"})


# ---------------------------------------------------------------- zamówienia

@app.post("/api/zamowienia/synchronizuj")
def synchronizuj():
    try:
        lista = pobierz_zamowienia()
    except BladPortalu as e:
        raise HTTPException(502, str(e)) from e
    n = db.zapisz_zamowienia(lista)
    weryfikuj_wszystkie()
    return {"pobrano": n}


@app.post("/api/zamowienia/import")
async def import_zamowien(plik: UploadFile = File(...)):
    try:
        lista = importuj_plik(plik.filename or "", await plik.read())
    except BladPortalu as e:
        raise HTTPException(400, str(e)) from e
    n = db.zapisz_zamowienia(lista)
    weryfikuj_wszystkie()
    return {"pobrano": n}


@app.get("/api/zamowienia")
def lista_zamowien():
    return {
        "ostatnia_synchronizacja": db.ostatnia_synchronizacja(),
        "tryb": konfiguracja()["portal"].get("tryb"),
        "zamowienia": [z.model_dump() | {"wartosc_netto": z.wartosc_netto} for z in db.zamowienia().values()],
    }


@app.get("/api/ustawienia")
def ustawienia():
    import os

    c = konfiguracja()
    return {
        "firma": c["firma"], "dostawca_nip": c["dostawca"].get("nip"),
        "silnik_ocr": c["ocr"].get("silnik") if (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")) else "lokalny",
        "portal": c["portal"].get("tryb"), "adres_portalu": c["portal"].get("adres"),
    }


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
