"""Odczyt danych z faktur: skany (JPG/PNG/TIFF), PDF-y skanowane i PDF-y tekstowe.

Silniki:
  * claude  - model Claude czyta obraz/PDF i zwraca ustrukturyzowane dane (najlepsza jakość)
  * lokalny - pdfplumber (PDF z warstwą tekstową) lub Tesseract (jeśli zainstalowany)
              + parser wyrażeń regularnych dla typowego układu polskiej faktury
"""
from __future__ import annotations

import base64
import io
import os
import re
import shutil
from pathlib import Path

from PIL import Image

from .config import konfiguracja
from .models import Faktura, PozycjaFaktury

TYPY_OBRAZOW = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".tif": "image/tiff", ".tiff": "image/tiff",
    ".bmp": "image/bmp",
}

PROMPT = """Jesteś asystentem działu księgowości. Odczytaj dane z załączonej polskiej faktury VAT
(dotyczy usług spiekania / spieku detali). Zwróć wyłącznie dane widoczne na dokumencie - nie zgaduj.
Zasady:
- daty w formacie RRRR-MM-DD,
- NIP-y i numer rachunku jako same cyfry (bez myślników, spacji i prefiksu PL),
- kwoty jako liczby (kropka dziesiętna, bez separatorów tysięcy),
- stawka VAT jako liczba procent (np. 23); dla "zw" lub "np" zostaw puste,
- numery zamówień: wszystkie numery zamówień / WZ / "Zam." widoczne na fakturze
  (w nagłówku, uwagach lub przy pozycjach); przy pozycji wpisz numer, jeśli jest przy niej podany,
- kod: indeks/numer rysunku detalu, jeśli występuje w pozycji,
- pole, którego nie da się odczytać, zostaw puste."""


class BladOdczytu(Exception):
    pass


# ---------------------------------------------------------------- Claude

def _obraz_do_bloku(dane: bytes, rozszerzenie: str) -> dict:
    """Przygotowuje obraz dla API: konwersja TIFF/BMP i zmniejszenie dużych skanów."""
    media = TYPY_OBRAZOW[rozszerzenie]
    img = Image.open(io.BytesIO(dane))
    if media in ("image/tiff", "image/bmp") or max(img.size) > 2400 or len(dane) > 4_500_000:
        img = img.convert("RGB")
        img.thumbnail((2400, 2400))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        dane, media = buf.getvalue(), "image/jpeg"
    return {"type": "image", "source": {"type": "base64", "media_type": media,
                                        "data": base64.standard_b64encode(dane).decode()}}


def odczyt_claude(dane: bytes, rozszerzenie: str) -> Faktura:
    import anthropic

    if rozszerzenie == ".pdf":
        blok = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                               "data": base64.standard_b64encode(dane).decode()}}
    elif rozszerzenie in TYPY_OBRAZOW:
        blok = _obraz_do_bloku(dane, rozszerzenie)
    else:
        raise BladOdczytu(f"Nieobsługiwany typ pliku: {rozszerzenie}")

    client = anthropic.Anthropic()
    try:
        odp = client.beta.messages.parse(
            model=konfiguracja()["ocr"].get("model", "claude-opus-5-5"),
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # gdy model odmówi, API ponowi zapytanie na modelu zapasowym
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": [blok, {"type": "text", "text": PROMPT}]}],
            output_format=Faktura,
        )
    except anthropic.AuthenticationError as e:
        raise BladOdczytu("Nieprawidłowy klucz ANTHROPIC_API_KEY") from e
    except anthropic.RateLimitError as e:
        raise BladOdczytu("Przekroczony limit zapytań do Claude - spróbuj za chwilę") from e
    except anthropic.BadRequestError as e:
        raise BladOdczytu(f"Claude odrzucił plik: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise BladOdczytu(f"Błąd API Claude ({e.status_code})") from e
    except anthropic.APIConnectionError as e:
        raise BladOdczytu("Brak połączenia z API Claude") from e

    if odp.stop_reason == "refusal":
        raise BladOdczytu("Model odmówił odczytu dokumentu")
    if odp.stop_reason == "max_tokens" or odp.parsed_output is None:
        raise BladOdczytu("Nie udało się odczytać kompletnej struktury faktury")
    return odp.parsed_output


# ---------------------------------------------------------------- lokalnie

def _tekst_pdf(dane: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(dane)) as pdf:
        return "\n".join(s.extract_text() or "" for s in pdf.pages)


def _tekst_tesseract(dane: bytes, rozszerzenie: str) -> str:
    if not shutil.which("tesseract"):
        raise BladOdczytu(
            "Skan bez warstwy tekstowej: zainstaluj Tesseract OCR (z językiem polskim) "
            "albo ustaw silnik 'claude' i klucz ANTHROPIC_API_KEY"
        )
    import pytesseract

    if rozszerzenie == ".pdf":
        from pdf2image import convert_from_bytes
        obrazy = convert_from_bytes(dane, dpi=300)
    else:
        obrazy = [Image.open(io.BytesIO(dane))]
    return "\n".join(pytesseract.image_to_string(o, lang="pol") for o in obrazy)


def _liczba(s: str | None) -> float | None:
    if not s:
        return None
    s = s.replace("\xa0", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _data(s: str | None) -> str | None:
    if not s:
        return None
    m = re.match(r"(\d{4})[-./](\d{2})[-./](\d{2})", s)
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}"
    m = re.match(r"(\d{2})[-./](\d{2})[-./](\d{4})", s)
    if m:
        return f"{m[3]}-{m[2]}-{m[1]}"
    return None


DATA = r"(\d{4}[-./]\d{2}[-./]\d{2}|\d{2}[-./]\d{2}[-./]\d{4})"
KWOTA = r"(\d[\d \xa0]*[,.]\d{2})"
NUMER_ZAM = r"\b((?:ZAM|ZS|ZK|WZ)[/\-]?[A-Z0-9/\-]*\d[A-Z0-9/\-]*)"


def parsuj_tekst(tekst: str) -> Faktura:
    """Heurystyczny parser tekstu faktury (dla silnika lokalnego)."""
    t = tekst
    f = Faktura()

    if m := re.search(r"Faktura(?:\s+VAT)?\s*(?:nr|numer)?[:\s]*([A-Z0-9][A-Z0-9/\-]*\d[A-Z0-9/\-]*)", t, re.I):
        f.numer = m[1]
    if m := re.search(r"Data\s+wystawienia[:\s]*" + DATA, t, re.I):
        f.data_wystawienia = _data(m[1])
    if m := re.search(r"Data\s+(?:sprzeda[żz]y|wykonania\s+us[łl]ugi|dostawy)[:\s]*" + DATA, t, re.I):
        f.data_sprzedazy = _data(m[1])
    if m := re.search(r"Termin\s+p[łl]atno[śs]ci[:\s]*" + DATA, t, re.I):
        f.termin_platnosci = _data(m[1])

    nipy = [re.sub(r"\D", "", n) for n in re.findall(r"NIP[:\s]*(?:PL)?\s*([\d\- ]{10,13})", t, re.I)]
    nipy = [n for n in nipy if len(n) == 10]
    if nipy:
        f.sprzedawca_nip = nipy[0]
    if len(nipy) > 1:
        f.nabywca_nip = nipy[1]

    # nazwy stron tylko przy układzie jednokolumnowym (przy dwóch kolumnach tekst się miesza)
    if not re.search(r"Sprzedawca.*Nabywca", t, re.I):
        if m := re.search(r"Sprzedawca[:\s]*\n?\s*(.+)", t, re.I):
            f.sprzedawca_nazwa = m[1].strip()
        if m := re.search(r"Nabywca[:\s]*\n?\s*(.+)", t, re.I):
            f.nabywca_nazwa = m[1].strip()

    f.numery_zamowien = list(dict.fromkeys(re.findall(NUMER_ZAM, t)))

    if m := re.search(r"(?:rachunek|konto|nr\s+rachunku)[^\d]*((?:PL)?\s*\d{2}(?:[ ]?\d{4}){6})", t, re.I):
        f.rachunek = re.sub(r"\D", "", m[1])

    # Pozycje: "1. Nazwa ... ilość jm cena stawka% netto vat brutto"
    wzor_poz = re.compile(
        r"^\s*\d+[.)]?\s+(?P<nazwa>.+?)\s+(?P<ilosc>\d+(?:[,.]\d+)?)\s+(?P<jm>kg|szt\.?|t|kpl\.?|usł\.?|h)\s+"
        r"(?P<cena>\d[\d ]*[,.]\d{2,4})\s+(?P<vat>\d{1,2})\s*%[.,]?\s+"
        + KWOTA.replace("(", "(?P<netto>", 1) + r"[.,]?\s+"
        + KWOTA.replace("(", "(?P<kvat>", 1) + r"[.,]?\s+"
        + KWOTA.replace("(", "(?P<brutto>", 1),
        re.I | re.M,
    )
    for m in wzor_poz.finditer(t):
        nazwa = m["nazwa"].strip()
        zam = re.search(NUMER_ZAM, nazwa)
        kod = re.search(r"\b([A-Z]{1,4}-?\d{2,}[A-Z0-9\-]*)\b", nazwa)
        f.pozycje.append(PozycjaFaktury(
            nazwa=nazwa,
            kod=kod[1] if kod and not (zam and kod[1] in zam[1]) else None,
            numer_zamowienia=zam[1] if zam else None,
            ilosc=_liczba(m["ilosc"]), jm=m["jm"].rstrip("."), cena_netto=_liczba(m["cena"]),
            stawka_vat=float(m["vat"]), wartosc_netto=_liczba(m["netto"]),
            wartosc_vat=_liczba(m["kvat"]), wartosc_brutto=_liczba(m["brutto"]),
        ))

    if m := re.search(r"(?:Razem|Suma|Ogółem)[:\s]*" + KWOTA + r"\s+" + KWOTA + r"\s+" + KWOTA, t, re.I):
        f.suma_netto, f.suma_vat, f.suma_brutto = _liczba(m[1]), _liczba(m[2]), _liczba(m[3])
    if m := re.search(r"Do\s+zap[łl]aty[:\s]*" + KWOTA, t, re.I):
        f.suma_brutto = _liczba(m[1])
    return f


def odczyt_lokalny(dane: bytes, rozszerzenie: str) -> Faktura:
    tekst = ""
    if rozszerzenie == ".pdf":
        tekst = _tekst_pdf(dane)
    if len(tekst.strip()) < 50:
        tekst = _tekst_tesseract(dane, rozszerzenie)
    return parsuj_tekst(tekst)


# ---------------------------------------------------------------- wejście

def odczytaj_fakture(sciezka: Path) -> tuple[Faktura, str]:
    """Zwraca (faktura, nazwa_silnika)."""
    dane = sciezka.read_bytes()
    rozszerzenie = sciezka.suffix.lower()
    silnik = konfiguracja()["ocr"].get("silnik", "claude")
    if silnik == "claude" and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return odczyt_claude(dane, rozszerzenie), "claude"
    return odczyt_lokalny(dane, rozszerzenie), "lokalny"
