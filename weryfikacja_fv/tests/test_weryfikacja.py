"""Testy end-to-end na przykładowych fakturach (silnik lokalny, portal demo)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

KATALOG = Path(__file__).resolve().parent.parent
PRZYKLADY = KATALOG / "przyklady"


@pytest.fixture(scope="module")
def klient(tmp_path_factory):
    os.environ["FV_DANE"] = str(tmp_path_factory.mktemp("dane"))
    os.environ.pop("ANTHROPIC_API_KEY", None)  # testy bez sieci: silnik lokalny
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
    if not (PRZYKLADY / "01_poprawna.pdf").exists():
        subprocess.run([sys.executable, str(PRZYKLADY / "generuj_przyklady.py")], check=True)
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


def wgraj(klient, nazwa):
    with open(PRZYKLADY / nazwa, "rb") as f:
        r = klient.post("/api/faktury", files=[("pliki", (nazwa, f, "application/pdf"))])
    assert r.status_code == 200, r.text
    return r.json()[0]


def reguly(fv, poziom="blad"):
    return {u["regula"] for u in fv["wynik"]["uwagi"] if u["poziom"] == poziom}


def test_synchronizacja_portalu(klient):
    r = klient.post("/api/zamowienia/synchronizuj")
    assert r.status_code == 200
    assert r.json()["pobrano"] == 4
    zam = {z["numer"]: z for z in klient.get("/api/zamowienia").json()["zamowienia"]}
    assert zam["ZAM/2026/0451"]["pozycje"][0]["cena_netto"] == 0.85


def test_faktura_poprawna(klient):
    fv = wgraj(klient, "01_poprawna.pdf")
    assert fv["status"] == "OK", fv["wynik"]


def test_zawyzona_cena(klient):
    fv = wgraj(klient, "02_zawyzona_cena.pdf")
    assert fv["status"] == "BLEDY"
    assert reguly(fv) == {"Cena"}


def test_ilosc_i_rachunki(klient):
    fv = wgraj(klient, "03_ilosc_i_rachunki.pdf")
    assert {"Ilość", "Rachunki pozycji"} <= reguly(fv)


def test_vat_nabywca_status(klient):
    fv = wgraj(klient, "04_vat_nabywca_status.pdf")
    assert {"Stawka VAT", "Nabywca"} <= reguly(fv)
    assert "Status zamówienia" in reguly(fv, "ostrzezenie")


def test_duplikat_i_korekta(klient):
    fv = wgraj(klient, "01_poprawna.pdf")
    assert "Duplikat" in reguly(fv)
    # ręczna korekta numeru usuwa duplikat (ilość nadal przekroczona - to ta sama usługa)
    dane = fv["dane"] | {"numer": "FV/2026/11/099"}
    fv2 = klient.put(f"/api/faktury/{fv['id']}", json=dane).json()
    assert "Duplikat" not in reguly(fv2)
    assert "Ilość" in reguly(fv2)


def test_import_csv(klient):
    csv = "numer;data;status;kod;nazwa;ilość;jm;cena\nZAM/X/1;2026-11-01;zrealizowane;SP-9;Spiek;10;kg;5,50\n"
    r = klient.post("/api/zamowienia/import", files={"plik": ("z.csv", csv.encode(), "text/csv")})
    assert r.json()["pobrano"] == 1


def test_nip_i_nrb():
    from app.weryfikacja import nip_poprawny, nrb_poprawny
    assert nip_poprawny("677-234-56-18")
    assert not nip_poprawny("6772345619")
    assert nrb_poprawny("60 1020 1026 0000 0422 7020 1111")
    assert not nrb_poprawny("61 1020 1026 0000 0422 7020 1111")


def test_parser_toleruje_artefakty_ocr():
    from app.ocr import parsuj_tekst
    t = ("Faktura VAT nr FV/1/2026\nNIP: 6772345618 NIP: 9541234576\n"
         "1.  Spiekanie tulei SP-1020 5000 szt 0,85 23%. 4250,00. 977,50 5 227,50\n")
    f = parsuj_tekst(t)
    assert len(f.pozycje) == 1 and f.pozycje[0].wartosc_netto == 4250.0 and f.pozycje[0].kod == "SP-1020"


def test_mozliwy_duplikat_przy_blednym_numerze():
    from app.models import Faktura
    from app.weryfikacja import weryfikuj
    a = Faktura(numer="FV/1", sprzedawca_nip="6772345618", suma_brutto=100.0, numery_zamowien=["ZAM/1"])
    b = a.model_copy(update={"numer": "FVv/1"})
    assert any(u.regula == "Możliwy duplikat" for u in weryfikuj(b, {}, [a]).uwagi)
