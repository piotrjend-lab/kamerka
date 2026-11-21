"""Generuje przykładowe faktury (PDF + symulowane skany JPG) pasujące do portalu demo.

    python przyklady/generuj_przyklady.py
"""
from __future__ import annotations

import random
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

KATALOG = Path(__file__).resolve().parent
CZCIONKI = [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("C:/Windows/Fonts/arial.ttf"),
            Path("/Library/Fonts/Arial Unicode.ttf")]
for c in CZCIONKI:
    if c.exists():
        pdfmetrics.registerFont(TTFont("F", str(c)))
        FONT = "F"
        break
else:
    FONT = "Helvetica"

SPRZEDAWCA = ("SpiekPol Sp. z o.o.", "ul. Hutnicza 7, 42-200 Częstochowa", "6772345618")
NABYWCA = ("Nasza Firma Sp. z o.o.", "ul. Fabryczna 1, 00-001 Warszawa", "9541234576")


def nrb(baza24: str) -> str:
    kontrolna = 98 - int(baza24 + "252100") % 97
    return f"{kontrolna:02d}{baza24}"


RACHUNEK = nrb("102010260000042270201111")


def kw(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ").replace(".", ",")


def faktura_pdf(plik: Path, numer: str, wyst: date, sprz: date, zamowienia: list[str], pozycje: list[dict],
                nabywca=NABYWCA, przesuniecie_netto: dict | None = None):
    c = canvas.Canvas(str(plik), pagesize=A4)
    W, H = A4
    y = H - 60
    c.setFont(FONT, 16)
    c.drawString(40, y, f"Faktura VAT nr {numer}")
    c.setFont(FONT, 9)
    c.drawRightString(W - 40, y + 6, f"Data wystawienia: {wyst.isoformat()}")
    c.drawRightString(W - 40, y - 6, f"Data wykonania usługi: {sprz.isoformat()}")
    y -= 45
    for x, tytul, (nazwa, adres, nip) in [(40, "Sprzedawca:", SPRZEDAWCA), (310, "Nabywca:", nabywca)]:
        c.setFont(FONT, 9)
        c.drawString(x, y, tytul)
        c.setFont(FONT, 10)
        c.drawString(x, y - 14, nazwa)
        c.drawString(x, y - 27, adres)
        c.drawString(x, y - 40, f"NIP: {nip}")
    y -= 70
    c.setFont(FONT, 9)
    c.drawString(40, y, "Dotyczy zamówienia: " + ", ".join(zamowienia))
    y -= 25
    kol = [40, 60, 300, 340, 370, 420, 450, 500, 545]
    for x, t in zip(kol, ["Lp", "Nazwa usługi", "Ilość", "J.m.", "Cena netto", "VAT", "Netto", "VAT", "Brutto"]):
        c.drawString(x, y, t)
    c.line(40, y - 4, W - 40, y - 4)
    y -= 18
    s_n = s_v = s_b = 0.0
    for i, p in enumerate(pozycje, 1):
        netto = round(p["ilosc"] * p["cena"], 2) + (przesuniecie_netto or {}).get(i, 0)
        vat = round(netto * p["vat"] / 100, 2)
        brutto = round(netto + vat, 2)
        s_n, s_v, s_b = s_n + netto, s_v + vat, s_b + brutto
        c.setFont(FONT, 8)
        for x, t in zip(kol, [f"{i}.", p["nazwa"], f"{p['ilosc']:g}", p["jm"], kw(p["cena"]), f"{p['vat']}%",
                              kw(netto), kw(vat), kw(brutto)]):
            c.drawString(x, y, t)
        y -= 16
    c.line(40, y + 6, W - 40, y + 6)
    c.setFont(FONT, 9)
    y -= 6
    c.drawString(300, y, "Razem:")
    c.drawString(kol[6], y, kw(s_n))
    c.drawString(kol[7], y, kw(s_v))
    c.drawString(kol[8], y, kw(s_b))
    y -= 35
    c.setFont(FONT, 12)
    c.drawString(40, y, f"Do zapłaty: {kw(s_b)} PLN")
    c.setFont(FONT, 9)
    y -= 20
    c.drawString(40, y, f"Termin płatności: {(wyst + timedelta(days=30)).isoformat()}   Forma płatności: przelew")
    y -= 14
    r = RACHUNEK
    c.drawString(40, y, "Nr rachunku: " + " ".join([r[:2]] + [r[i:i + 4] for i in range(2, 26, 4)]))
    c.save()


def skan_jpg(pdf: Path, jpg: Path, kat: float = 0.8):
    """Symuluje skan: rasteryzacja 150 dpi, lekki obrót, szum, kompresja JPEG."""
    prefiks = jpg.with_suffix("")
    subprocess.run(["pdftoppm", "-r", "150", "-png", "-singlefile", str(pdf), str(prefiks)], check=True)
    png = prefiks.with_suffix(".png")
    img = Image.open(png).convert("L")
    img = img.rotate(kat, expand=True, fillcolor=255, resample=Image.BICUBIC)
    px = img.load()
    rnd = random.Random(1)
    for _ in range(img.size[0] * img.size[1] // 60):
        x, y = rnd.randrange(img.size[0]), rnd.randrange(img.size[1])
        px[x, y] = max(0, px[x, y] - rnd.randrange(60, 160))
    img = img.filter(ImageFilter.GaussianBlur(0.5))
    img.save(jpg, "JPEG", quality=70)
    png.unlink()


def main():
    P = lambda kod, nazwa, il, jm, cena, vat=23: {"nazwa": f"{nazwa} {kod}", "ilosc": il, "jm": jm, "cena": cena, "vat": vat}
    wyst = date(2026, 11, 2)
    przyklady = [
        ("01_poprawna", "FV/2026/11/001", wyst, date(2026, 10, 31), ["ZAM/2026/0451"],
         [P("SP-1020", "Spiekanie tulei Fe-Cu fi12", 5000, "szt", 0.85),
          P("SP-2210", "Spiekanie koła zębatego z=24", 1200, "szt", 2.40)], {}),
        ("02_zawyzona_cena", "FV/2026/11/002", wyst, date(2026, 10, 30), ["ZAM/2026/0458"],
         [P("SP-3105", "Spiekanie wsadu proszkowego - piec taśmowy", 850, "kg", 6.50)], {}),
        ("03_ilosc_i_rachunki", "FV/2026/11/003", date(2026, 11, 10), date(2026, 11, 7), ["ZAM/2026/0477"],
         [P("SP-4400", "Spiekanie i kalibracja pierścieni", 2200, "szt", 1.15),
          P("SP-4401", "Hartowanie po spiekaniu", 2000, "szt", 0.35)], {"przesuniecie": {2: 20.0}}),
        ("04_vat_nabywca_status", "FV/2026/11/004", date(2026, 11, 12), date(2026, 11, 12), ["ZAM/2026/0470"],
         [P("SP-1020", "Spiekanie tulei Fe-Cu fi12", 3000, "szt", 0.85, vat=8)],
         {"nabywca": ("Inna Firma S.A.", "ul. Polna 3, 30-001 Kraków", "1234563218")}),
    ]
    for plik, numer, d_w, d_s, zam, poz, opcje in przyklady:
        pdf = KATALOG / f"{plik}.pdf"
        faktura_pdf(pdf, numer, d_w, d_s, zam, poz, nabywca=opcje.get("nabywca", NABYWCA),
                    przesuniecie_netto=opcje.get("przesuniecie"))
        print("utworzono", pdf.name)
    # skan JPG faktury 01 - wgrany po PDF-ie wykaże duplikat; skan 02 do testu OCR
    try:
        skan_jpg(KATALOG / "01_poprawna.pdf", KATALOG / "05_skan_duplikat_01.jpg", 0.7)
        skan_jpg(KATALOG / "02_zawyzona_cena.pdf", KATALOG / "06_skan_zawyzona_cena.jpg", -1.1)
        print("utworzono skany JPG")
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("pdftoppm (poppler) niedostępny - pominięto skany JPG", file=sys.stderr)


if __name__ == "__main__":
    main()
