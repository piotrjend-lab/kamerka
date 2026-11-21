"""Pobieranie zamówień ze strony zewnętrznej firmy (portal zamówień na spieki).

Ponieważ każdy portal wygląda inaczej, konektor jest konfigurowalny (config.toml, sekcja [portal]):
adresy stron, nazwy pól formularza logowania oraz selektory CSS tabel.
Dodatkowo można zaimportować zamówienia z pliku CSV/XLSX wyeksportowanego z portalu.
"""
from __future__ import annotations

import csv
import io
import os
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .config import konfiguracja
from .models import PozycjaZamowienia, Zamowienie


class BladPortalu(Exception):
    pass


def _liczba(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = re.sub(r"[^\d,.\-]", "", str(s))
    if "," in s and "." in s:
        s = s.replace(".", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _cfg() -> dict:
    return konfiguracja()["portal"]


def _url(sciezka: str) -> str:
    return urljoin(_cfg()["adres"].rstrip("/") + "/", sciezka.lstrip("/"))


def _dane_logowania() -> tuple[str, str]:
    c = _cfg()
    if c["tryb"] == "demo":
        return "demo", "demo"
    login, haslo = os.environ.get("PORTAL_LOGIN"), os.environ.get("PORTAL_HASLO")
    if not login or not haslo:
        raise BladPortalu("Ustaw zmienne środowiskowe PORTAL_LOGIN i PORTAL_HASLO")
    return login, haslo


# ---------------------------------------------------------------- parsowanie HTML

def parsuj_szczegoly(html: str, numer_awaryjny: str | None = None) -> Zamowienie:
    sel = _cfg()["selektory"]
    soup = BeautifulSoup(html, "html.parser")

    def tekst(s: str) -> str | None:
        el = soup.select_one(s) if s else None
        return el.get_text(strip=True) if el else None

    pozycje = []
    for tr in soup.select(sel["wiersz_pozycji"]):
        kom = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(kom) <= max(sel["kol_nazwa"], sel["kol_ilosc"]):
            continue
        ilosc = _liczba(kom[sel["kol_ilosc"]])
        if ilosc is None:
            continue
        pozycje.append(PozycjaZamowienia(
            kod=kom[sel["kol_kod"]] if sel.get("kol_kod", -1) >= 0 and sel["kol_kod"] < len(kom) else None,
            nazwa=kom[sel["kol_nazwa"]],
            ilosc=ilosc,
            jm=kom[sel["kol_jm"]] if sel.get("kol_jm", -1) >= 0 and sel["kol_jm"] < len(kom) else None,
            cena_netto=_liczba(kom[sel["kol_cena"]]) if sel.get("kol_cena", -1) >= 0 and sel["kol_cena"] < len(kom) else None,
        ))
    numer = tekst(sel["numer"]) or numer_awaryjny
    if not numer:
        raise BladPortalu("Nie znaleziono numeru zamówienia na stronie szczegółów - sprawdź selektory")
    nip = tekst(sel.get("dostawca_nip", ""))
    return Zamowienie(
        numer=numer,
        data=tekst(sel.get("data", "")),
        status=tekst(sel.get("status", "")),
        dostawca_nip=re.sub(r"\D", "", nip) if nip else None,
        pozycje=pozycje,
    )


def _linki_z_listy(html: str, baza: str) -> list[str]:
    sel = _cfg()["selektory"]
    soup = BeautifulSoup(html, "html.parser")
    linki = []
    for tr in soup.select(sel["wiersz_listy"]):
        a = tr.select_one(sel["link_szczegolow"])
        if a and a.get("href"):
            linki.append(urljoin(baza, a["href"]))
    return linki


# ---------------------------------------------------------------- tryby

def _pobierz_html_requests() -> list[Zamowienie]:
    c = _cfg()
    login, haslo = _dane_logowania()
    s = requests.Session()
    s.headers["User-Agent"] = "WeryfikacjaFV/1.0"
    try:
        r = s.post(_url(c["login_url"]), data={c["pole_login"]: login, c["pole_haslo"]: haslo}, timeout=30)
        r.raise_for_status()
        lista_url = _url(c["zamowienia_url"])
        r = s.get(lista_url, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        raise BladPortalu(f"Błąd połączenia z portalem: {e}") from e
    if "login" in r.url and r.url != lista_url:
        raise BladPortalu("Logowanie do portalu nie powiodło się - sprawdź login i hasło")

    wynik = []
    for link in _linki_z_listy(r.text, r.url):
        try:
            rr = s.get(link, timeout=30)
            rr.raise_for_status()
        except requests.RequestException as e:
            raise BladPortalu(f"Nie udało się pobrać {link}: {e}") from e
        wynik.append(parsuj_szczegoly(rr.text))
    return wynik


def _pobierz_playwright() -> list[Zamowienie]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise BladPortalu("Zainstaluj Playwright: pip install playwright && playwright install chromium") from e
    c = _cfg()
    login, haslo = _dane_logowania()
    wynik = []
    with sync_playwright() as p:
        przegladarka = p.chromium.launch()
        strona = przegladarka.new_page()
        strona.goto(_url(c["login_url"]))
        strona.fill(f"[name='{c['pole_login']}']", login)
        strona.fill(f"[name='{c['pole_haslo']}']", haslo)
        strona.press(f"[name='{c['pole_haslo']}']", "Enter")
        strona.wait_for_load_state("networkidle")
        strona.goto(_url(c["zamowienia_url"]))
        strona.wait_for_load_state("networkidle")
        for link in _linki_z_listy(strona.content(), strona.url):
            strona.goto(link)
            strona.wait_for_load_state("networkidle")
            wynik.append(parsuj_szczegoly(strona.content()))
        przegladarka.close()
    return wynik


def _pobierz_json() -> list[Zamowienie]:
    """Portal z API: GET {adres}{zamowienia_url} zwraca listę zamówień w formacie modelu Zamowienie."""
    c = _cfg()
    naglowki = {}
    if token := os.environ.get("PORTAL_TOKEN"):
        naglowki["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(_url(c["zamowienia_url"]), headers=naglowki, timeout=30)
        r.raise_for_status()
        dane = r.json()
    except (requests.RequestException, ValueError) as e:
        raise BladPortalu(f"Błąd pobierania JSON z portalu: {e}") from e
    if isinstance(dane, dict):
        dane = dane.get("zamowienia") or dane.get("orders") or dane.get("data") or []
    return [Zamowienie.model_validate(z) for z in dane]


def _pobierz_demo() -> list[Zamowienie]:
    """Tryb demo nie wykonuje zapytań HTTP - parsuje HTML generowany przez wbudowany portal,
    dokładnie tą samą ścieżką co tryb 'html' (dzięki temu demonstruje działanie selektorów)."""
    from . import demo_portal

    return [parsuj_szczegoly(demo_portal.html_szczegolow(n)) for n in demo_portal.ZAMOWIENIA]


def pobierz_zamowienia() -> list[Zamowienie]:
    tryb = _cfg().get("tryb", "demo")
    funkcje = {"demo": _pobierz_demo, "html": _pobierz_html_requests,
               "playwright": _pobierz_playwright, "json": _pobierz_json}
    if tryb not in funkcje:
        raise BladPortalu(f"Nieznany tryb portalu: {tryb}")
    return funkcje[tryb]()


# ---------------------------------------------------------------- import pliku

KOLUMNY = {
    "numer": ["numer", "nr zamówienia", "numer zamówienia", "zamówienie", "nr", "order"],
    "data": ["data", "data zamówienia", "date"],
    "status": ["status"],
    "dostawca_nip": ["nip", "nip dostawcy", "dostawca nip"],
    "kod": ["kod", "indeks", "nr rysunku", "kod detalu", "code"],
    "nazwa": ["nazwa", "opis", "detal", "usługa", "name"],
    "ilosc": ["ilość", "ilosc", "qty", "ilość zamówiona"],
    "jm": ["jm", "j.m.", "jednostka"],
    "cena_netto": ["cena", "cena netto", "cena jedn.", "cena jedn. netto", "price"],
}


def importuj_plik(nazwa: str, dane: bytes) -> list[Zamowienie]:
    """CSV lub XLSX: jeden wiersz = jedna pozycja zamówienia (numer zamówienia powtarza się)."""
    if nazwa.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(dane), read_only=True, data_only=True)
        wiersze = [[("" if v is None else v) for v in w] for w in wb.active.iter_rows(values_only=True)]
    else:
        tekst = dane.decode("utf-8-sig", errors="replace")
        dialekt = csv.Sniffer().sniff(tekst[:2000], delimiters=";,\t")
        wiersze = list(csv.reader(io.StringIO(tekst), dialekt))
    if not wiersze:
        return []
    naglowek = [str(h).strip().lower() for h in wiersze[0]]
    idx = {}
    for pole, nazwy in KOLUMNY.items():
        for i, h in enumerate(naglowek):
            if h in nazwy:
                idx[pole] = i
                break
    if "numer" not in idx or "ilosc" not in idx:
        raise BladPortalu("Plik musi mieć kolumny 'numer' i 'ilość'")

    zam: dict[str, Zamowienie] = {}
    for w in wiersze[1:]:
        def k(p):
            return str(w[idx[p]]).strip() if p in idx and idx[p] < len(w) else None
        numer = k("numer")
        if not numer:
            continue
        z = zam.setdefault(numer, Zamowienie(
            numer=numer, data=k("data"), status=k("status"),
            dostawca_nip=re.sub(r"\D", "", k("dostawca_nip") or "") or None,
        ))
        ilosc = _liczba(k("ilosc"))
        if ilosc is not None:
            z.pozycje.append(PozycjaZamowienia(
                kod=k("kod") or None, nazwa=k("nazwa") or k("kod") or "", ilosc=ilosc,
                jm=k("jm") or None, cena_netto=_liczba(k("cena_netto")),
            ))
    return list(zam.values())
