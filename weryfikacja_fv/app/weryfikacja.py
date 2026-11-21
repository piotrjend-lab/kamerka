"""Reguły weryfikacji faktury za usługę spieku względem zamówień z portalu."""
from __future__ import annotations

import re
from datetime import date, timedelta
from difflib import SequenceMatcher

from .config import konfiguracja
from .models import Faktura, PozycjaFaktury, PozycjaZamowienia, Uwaga, WynikWeryfikacji, Zamowienie

# ---------------------------------------------------------------- narzędzia


def nip_poprawny(nip: str | None) -> bool:
    n = re.sub(r"\D", "", nip or "")
    if len(n) != 10:
        return False
    s = sum(int(a) * w for a, w in zip(n, (6, 5, 7, 2, 3, 4, 5, 6, 7))) % 11
    return s != 10 and s == int(n[9])


def nrb_poprawny(nrb: str | None) -> bool:
    """Suma kontrolna polskiego numeru rachunku (26 cyfr, IBAN mod 97)."""
    n = re.sub(r"\D", "", nrb or "")
    if len(n) != 26:
        return False
    return int(n[2:] + "2521" + n[:2]) % 97 == 1  # "PL" -> 25 21


def _norm(s: str | None) -> str:
    return re.sub(r"[^0-9a-ząćęłńóśźż]", "", (s or "").lower())


def _norm_numer(s: str | None) -> str:
    return re.sub(r"[^0-9A-Z]", "", (s or "").upper())


def _data(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def _zl(x: float | None) -> str:
    return "—" if x is None else f"{x:,.2f}".replace(",", " ").replace(".", ",")


def znajdz_zamowienie(numer: str, zamowienia: dict[str, Zamowienie]) -> Zamowienie | None:
    if numer in zamowienia:
        return zamowienia[numer]
    klucz = _norm_numer(numer)
    for n, z in zamowienia.items():
        if _norm_numer(n) == klucz:
            return z
    return None


def dopasuj_pozycje(poz: PozycjaFaktury, zam: Zamowienie) -> tuple[PozycjaZamowienia | None, str]:
    """Zwraca (pozycja zamówienia, sposób dopasowania)."""
    kod_f = _norm(poz.kod)
    nazwa_f = _norm(poz.nazwa)
    for p in zam.pozycje:
        kod_z = _norm(p.kod)
        if kod_z and (kod_z == kod_f or kod_z in nazwa_f):
            return p, "kod"
    najlepsza, wynik = None, 0.0
    for p in zam.pozycje:
        r = SequenceMatcher(None, nazwa_f, _norm(p.nazwa)).ratio()
        if r > wynik:
            najlepsza, wynik = p, r
    if najlepsza and wynik >= 0.6:
        return najlepsza, f"nazwa ({wynik:.0%})"
    if len(zam.pozycje) == 1 and len(nazwa_f) == 0:
        return zam.pozycje[0], "jedyna pozycja"
    return None, ""


def przypisz_pozycje(f: Faktura, zamowienia: dict[str, Zamowienie]):
    """Dla każdej pozycji faktury: (pozycja_fv, zamówienie|None, pozycja_zam|None, numer_szukany, sposób)."""
    wynik = []
    numery_fv = f.numery_zamowien
    for poz in f.pozycje:
        kandydaci = [poz.numer_zamowienia] if poz.numer_zamowienia else list(numery_fv)
        trafienie = None
        for numer in kandydaci:
            zam = znajdz_zamowienie(numer, zamowienia)
            if zam is None:
                continue
            p, sposob = dopasuj_pozycje(poz, zam)
            if p is not None:
                trafienie = (poz, zam, p, numer, sposob)
                break
            if trafienie is None:
                trafienie = (poz, zam, None, numer, "")
        wynik.append(trafienie or (poz, None, None, kandydaci[0] if kandydaci else None, ""))
    return wynik


# ---------------------------------------------------------------- weryfikacja


def weryfikuj(f: Faktura, zamowienia: dict[str, Zamowienie], inne_faktury: list[Faktura]) -> WynikWeryfikacji:
    cfg = konfiguracja()
    w = cfg["weryfikacja"]
    tol = float(w.get("tolerancja_kwot", 0.02))
    uwagi: list[Uwaga] = []

    def blad(regula, opis):
        uwagi.append(Uwaga(poziom="blad", regula=regula, opis=opis))

    def ostrz(regula, opis):
        uwagi.append(Uwaga(poziom="ostrzezenie", regula=regula, opis=opis))

    def info(regula, opis):
        uwagi.append(Uwaga(poziom="info", regula=regula, opis=opis))

    # 1. Kompletność
    for pole, nazwa in [("numer", "numer faktury"), ("sprzedawca_nip", "NIP sprzedawcy"),
                        ("nabywca_nip", "NIP nabywcy"), ("data_wystawienia", "data wystawienia")]:
        if not getattr(f, pole):
            blad("Kompletność", f"Brak pola: {nazwa}")
    for pole, nazwa in [("data_sprzedazy", "data sprzedaży/wykonania usługi"),
                        ("termin_platnosci", "termin płatności"), ("suma_brutto", "kwota do zapłaty")]:
        if getattr(f, pole) in (None, ""):
            ostrz("Kompletność", f"Brak pola: {nazwa}")
    if not f.pozycje:
        blad("Kompletność", "Nie odczytano żadnej pozycji faktury")
    if f.waluta and f.waluta.upper() not in ("PLN", "ZŁ", "ZL"):
        ostrz("Waluta", f"Faktura w walucie {f.waluta} - zamówienia są w PLN")

    # 2-4. Strony transakcji
    for pole, kto in [("sprzedawca_nip", "sprzedawcy"), ("nabywca_nip", "nabywcy")]:
        nip = getattr(f, pole)
        if nip and not nip_poprawny(nip):
            blad("NIP", f"NIP {kto} {nip} ma niepoprawną sumę kontrolną (błąd odczytu lub na fakturze)")
    nip_firmy = re.sub(r"\D", "", cfg["firma"].get("nip", ""))
    if nip_firmy and f.nabywca_nip and re.sub(r"\D", "", f.nabywca_nip) != nip_firmy:
        blad("Nabywca", f"Faktura wystawiona na NIP {f.nabywca_nip}, a nasz NIP to {nip_firmy}")
    nip_dost = re.sub(r"\D", "", cfg["dostawca"].get("nip", ""))
    if nip_dost and f.sprzedawca_nip and re.sub(r"\D", "", f.sprzedawca_nip) != nip_dost:
        blad("Sprzedawca", f"NIP sprzedawcy {f.sprzedawca_nip} różni się od NIP dostawcy usług spieku ({nip_dost})")

    # 5. Rachunek bankowy
    if f.rachunek:
        if not nrb_poprawny(f.rachunek):
            blad("Rachunek", f"Numer rachunku {f.rachunek} ma niepoprawną sumę kontrolną")
        dozwolone = [re.sub(r"\D", "", r) for r in cfg["dostawca"].get("rachunki", [])]
        if dozwolone and re.sub(r"\D", "", f.rachunek) not in dozwolone:
            blad("Rachunek", "Rachunek bankowy spoza listy znanych rachunków dostawcy - ryzyko oszustwa!")
    elif cfg["dostawca"].get("rachunki"):
        ostrz("Rachunek", "Na fakturze nie odczytano numeru rachunku")

    # 6. Arytmetyka pozycji i stawka VAT
    stawka = float(w.get("stawka_vat", 23))
    for i, p in enumerate(f.pozycje, 1):
        etykieta = f"Poz. {i} ({p.kod or p.nazwa[:30]})"
        if p.ilosc is not None and p.cena_netto is not None and p.wartosc_netto is not None:
            oczek = round(p.ilosc * p.cena_netto, 2)
            if abs(oczek - p.wartosc_netto) > tol:
                blad("Rachunki pozycji", f"{etykieta}: {p.ilosc:g} × {_zl(p.cena_netto)} = {_zl(oczek)}, "
                                         f"a na fakturze netto {_zl(p.wartosc_netto)}")
        if p.stawka_vat is None:
            ostrz("Stawka VAT", f"{etykieta}: nie odczytano stawki VAT")
        elif abs(p.stawka_vat - stawka) > 0.001:
            blad("Stawka VAT", f"{etykieta}: stawka {p.stawka_vat:g}% zamiast {stawka:g}%")
        if p.wartosc_netto is not None and p.wartosc_vat is not None and p.stawka_vat is not None:
            oczek = round(p.wartosc_netto * p.stawka_vat / 100, 2)
            if abs(oczek - p.wartosc_vat) > tol:
                blad("Rachunki pozycji", f"{etykieta}: VAT {p.stawka_vat:g}% od {_zl(p.wartosc_netto)} "
                                         f"to {_zl(oczek)}, a na fakturze {_zl(p.wartosc_vat)}")
        if None not in (p.wartosc_netto, p.wartosc_vat, p.wartosc_brutto):
            if abs(p.wartosc_netto + p.wartosc_vat - p.wartosc_brutto) > tol:
                blad("Rachunki pozycji", f"{etykieta}: netto + VAT ≠ brutto")

    # 7. Sumy faktury
    if f.pozycje:
        sumy = {
            "netto": (f.suma_netto, [p.wartosc_netto for p in f.pozycje]),
            "VAT": (f.suma_vat, [p.wartosc_vat for p in f.pozycje]),
            "brutto": (f.suma_brutto, [p.wartosc_brutto for p in f.pozycje]),
        }
        for nazwa, (suma, wartosci) in sumy.items():
            if suma is None or any(v is None for v in wartosci):
                continue
            oczek = round(sum(wartosci), 2)
            if abs(oczek - suma) > tol * max(1, len(wartosci)):
                blad("Sumy", f"Suma {nazwa} pozycji = {_zl(oczek)}, a w podsumowaniu {_zl(suma)}")
    if None not in (f.suma_netto, f.suma_vat, f.suma_brutto):
        if abs(f.suma_netto + f.suma_vat - f.suma_brutto) > tol:
            blad("Sumy", f"Razem netto {_zl(f.suma_netto)} + VAT {_zl(f.suma_vat)} ≠ brutto {_zl(f.suma_brutto)}")

    # 8. Daty
    d_wyst, d_sprz, d_term = _data(f.data_wystawienia), _data(f.data_sprzedazy), _data(f.termin_platnosci)
    if f.data_wystawienia and not d_wyst:
        ostrz("Daty", f"Nieczytelna data wystawienia: {f.data_wystawienia}")
    if d_wyst and d_wyst > date.today():
        blad("Daty", f"Data wystawienia {d_wyst} jest w przyszłości")
    if d_wyst and d_sprz:
        # art. 106i ust. 1 ustawy o VAT: nie później niż 15. dnia miesiąca następującego po wykonaniu usługi
        nast = (d_sprz.replace(day=1) + timedelta(days=32)).replace(day=15)
        if d_wyst > nast:
            ostrz("Daty", f"Faktura wystawiona {d_wyst}, później niż 15. dzień miesiąca po wykonaniu usługi ({nast})")
        if d_wyst < d_sprz - timedelta(days=30):
            ostrz("Daty", "Faktura wystawiona ponad 30 dni przed wykonaniem usługi")
    dni = int(cfg["dostawca"].get("termin_platnosci_dni", 0) or 0)
    if dni and d_wyst and d_term:
        oczek = d_wyst + timedelta(days=dni)
        if d_term < oczek:
            ostrz("Termin płatności", f"Termin płatności {d_term} krótszy niż umowne {dni} dni (powinien być {oczek})")

    # 9. Duplikaty
    for inna in inne_faktury:
        if (f.numer and inna.numer and _norm_numer(inna.numer) == _norm_numer(f.numer)
                and re.sub(r"\D", "", inna.sprzedawca_nip or "") == re.sub(r"\D", "", f.sprzedawca_nip or "")):
            blad("Duplikat", f"Faktura nr {f.numer} tego sprzedawcy była już wprowadzona - możliwa podwójna płatność")
            break
    else:
        # ten sam sprzedawca, ta sama kwota i wspólne zamówienie - np. ta sama FV z innym (błędnie odczytanym) numerem
        for inna in inne_faktury:
            if (f.suma_brutto is not None and inna.suma_brutto is not None
                    and abs(f.suma_brutto - inna.suma_brutto) <= tol
                    and re.sub(r"\D", "", inna.sprzedawca_nip or "") == re.sub(r"\D", "", f.sprzedawca_nip or "")
                    and {_norm_numer(n) for n in f.numery_zamowien} & {_norm_numer(n) for n in inna.numery_zamowien}):
                ostrz("Możliwy duplikat", f"Faktura {inna.numer} ma tę samą kwotę {_zl(f.suma_brutto)} i to samo zamówienie")
                break

    # 10-13. Zgodność z zamówieniami z portalu
    numery = set(f.numery_zamowien) | {p.numer_zamowienia for p in f.pozycje if p.numer_zamowienia}
    if not numery:
        blad("Zamówienie", "Na fakturze nie znaleziono numeru zamówienia - nie można powiązać z portalem")
    if not zamowienia:
        ostrz("Zamówienie", "Brak zamówień w bazie - pobierz je z portalu (przycisk 'Synchronizuj')")
    elif numery:
        for numer in sorted(numery):
            zam = znajdz_zamowienie(numer, zamowienia)
            if zam is None:
                blad("Zamówienie", f"Zamówienie {numer} nie istnieje w portalu")
                continue
            zrealiz = [s.lower() for s in w.get("statusy_zrealizowane", [])]
            if zam.status and zrealiz and zam.status.lower() not in zrealiz:
                ostrz("Status zamówienia", f"Zamówienie {zam.numer} ma status '{zam.status}' - usługa mogła nie zostać wykonana")
            if zam.dostawca_nip and f.sprzedawca_nip and zam.dostawca_nip != re.sub(r"\D", "", f.sprzedawca_nip):
                blad("Sprzedawca", f"Zamówienie {zam.numer} złożono u NIP {zam.dostawca_nip}, faktura od {f.sprzedawca_nip}")
            if d_sprz and _data(zam.data) and d_sprz < _data(zam.data):
                ostrz("Daty", f"Data wykonania usługi {d_sprz} wcześniejsza niż data zamówienia {zam.numer} ({zam.data})")

        # ilości zafakturowane wcześniej (inne faktury) na te same pozycje zamówień
        wczesniej: dict[tuple[str, int], float] = {}
        for inna in inne_faktury:
            for pf, zam, pz, _, _ in przypisz_pozycje(inna, zamowienia):
                if zam and pz and pf.ilosc:
                    k = (zam.numer, id(pz))
                    wczesniej[k] = wczesniej.get(k, 0) + pf.ilosc

        biezace: dict[tuple[str, int], float] = {}
        tol_cena = float(w.get("tolerancja_ceny_proc", 0)) / 100
        tol_il = float(w.get("tolerancja_ilosci_proc", 0)) / 100
        for i, (pf, zam, pz, numer, sposob) in enumerate(przypisz_pozycje(f, zamowienia), 1):
            etykieta = f"Poz. {i} ({pf.kod or pf.nazwa[:30]})"
            if zam is None:
                continue  # brak zamówienia już zgłoszony
            if pz is None:
                blad("Pozycja zamówienia", f"{etykieta}: nie znaleziono takiej usługi w zamówieniu {zam.numer}")
                continue
            if pz.cena_netto is not None and pf.cena_netto is not None:
                if pf.cena_netto > pz.cena_netto * (1 + tol_cena) + 1e-9:
                    blad("Cena", f"{etykieta}: cena {_zl(pf.cena_netto)} wyższa niż w zamówieniu {zam.numer} "
                                 f"({_zl(pz.cena_netto)}) - nadpłata {_zl((pf.cena_netto - pz.cena_netto) * (pf.ilosc or 0))} netto")
                elif pf.cena_netto < pz.cena_netto * (1 - tol_cena) - 1e-9:
                    info("Cena", f"{etykieta}: cena {_zl(pf.cena_netto)} niższa niż w zamówieniu ({_zl(pz.cena_netto)})")
            if pz.jm and pf.jm and _norm(pz.jm) != _norm(pf.jm):
                ostrz("Jednostka", f"{etykieta}: jednostka '{pf.jm}' a w zamówieniu '{pz.jm}'")
            if pf.ilosc is not None:
                k = (zam.numer, id(pz))
                biezace[k] = biezace.get(k, 0) + pf.ilosc
                lacznie = biezace[k] + wczesniej.get(k, 0)
                if lacznie > pz.ilosc * (1 + tol_il) + 1e-9:
                    poprz = wczesniej.get(k, 0)
                    dop = f" (w tym {poprz:g} na wcześniejszych fakturach)" if poprz else ""
                    blad("Ilość", f"{etykieta}: zafakturowano łącznie {lacznie:g} {pf.jm or ''}{dop}, "
                                  f"a zamówiono {pz.ilosc:g} {pz.jm or ''} w {zam.numer}")
                elif lacznie < pz.ilosc:
                    info("Ilość", f"{etykieta}: częściowe fakturowanie {lacznie:g} z {pz.ilosc:g} {pz.jm or ''} ({zam.numer})")
            if sposob.startswith("nazwa"):
                info("Dopasowanie", f"{etykieta}: dopasowano do '{pz.nazwa}' po {sposob}")

    # 14. Biała lista VAT (opcjonalnie)
    if w.get("biala_lista") and f.sprzedawca_nip:
        uwagi.extend(sprawdz_biala_liste(f.sprzedawca_nip, f.rachunek, f.data_wystawienia))

    if any(u.poziom == "blad" for u in uwagi):
        status = "BLEDY"
    elif any(u.poziom == "ostrzezenie" for u in uwagi):
        status = "UWAGI"
    else:
        status = "OK"
    return WynikWeryfikacji(status=status, uwagi=uwagi)


def sprawdz_biala_liste(nip: str, rachunek: str | None, dzien: str | None) -> list[Uwaga]:
    """Wykaz podatników VAT Ministerstwa Finansów (publiczne API, bez klucza)."""
    import requests

    dzien = dzien if _data(dzien) and _data(dzien) <= date.today() else date.today().isoformat()
    nip = re.sub(r"\D", "", nip)
    try:
        r = requests.get(f"https://wl-api.mf.gov.pl/api/search/nip/{nip}", params={"date": dzien}, timeout=15)
        r.raise_for_status()
        podmiot = r.json()["result"]["subject"]
    except Exception as e:  # noqa: BLE001 - usługa zewnętrzna, nie przerywamy weryfikacji
        return [Uwaga(poziom="ostrzezenie", regula="Biała lista", opis=f"Nie udało się sprawdzić Białej listy: {e}")]
    if not podmiot:
        return [Uwaga(poziom="blad", regula="Biała lista", opis=f"NIP {nip} nie figuruje w wykazie podatników VAT")]
    wynik = []
    if podmiot.get("statusVat") != "Czynny":
        wynik.append(Uwaga(poziom="blad", regula="Biała lista", opis=f"Status VAT sprzedawcy: {podmiot.get('statusVat')}"))
    if rachunek:
        konta = [re.sub(r"\D", "", k) for k in podmiot.get("accountNumbers") or []]
        if re.sub(r"\D", "", rachunek) not in konta:
            wynik.append(Uwaga(poziom="blad", regula="Biała lista",
                               opis="Rachunek z faktury NIE jest zgłoszony na Białej liście VAT (ryzyko solidarnej odpowiedzialności)"))
    return wynik
