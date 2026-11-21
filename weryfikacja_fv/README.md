# Weryfikacja faktur za usługi spieku

Aplikacja webowa dla sieci firmowej. Pracownik biura wgrywa skany faktur (PDF/JPG/PNG/TIFF). Aplikacja:

1. **odczytuje fakturę** – numer, daty, NIP-y, numery zamówień, pozycje, kwoty, rachunek bankowy;
2. **pobiera zamówienia ze strony firmy spiekającej** – loguje się do portalu i czyta tabelę zamówień
   (albo importuje eksport CSV/XLSX);
3. **porównuje jedno z drugim** i pokazuje wynik: ✅ OK / ⚠️ Uwagi / ❌ Błędy, z opisem każdego problemu.

Pracownik może poprawić źle odczytane pola obok podglądu skanu i zatwierdzić fakturę do zapłaty.
Raport wszystkich faktur można pobrać jako CSV (otwiera się w Excelu).

## Co jest sprawdzane

| Obszar | Reguła | Poziom |
|---|---|---|
| Kompletność | numer, data wystawienia, NIP-y, pozycje | błąd |
| NIP | suma kontrolna NIP sprzedawcy i nabywcy | błąd |
| Nabywca | faktura wystawiona na NIP naszej firmy | błąd |
| Sprzedawca | NIP zgodny z dostawcą usług spieku i z zamówieniem | błąd |
| Rachunek | suma kontrolna NRB, rachunek z listy znanych rachunków dostawcy | błąd |
| Rachunki pozycji | ilość × cena = netto, VAT od netto, netto + VAT = brutto | błąd |
| Stawka VAT | zgodna z oczekiwaną (domyślnie 23%) | błąd |
| Sumy | suma pozycji = podsumowanie, netto + VAT = brutto | błąd |
| Zamówienie | numer zamówienia na fakturze istnieje w portalu | błąd |
| Pozycja zamówienia | usługa z faktury jest w zamówieniu (po indeksie lub nazwie) | błąd |
| Cena | cena jednostkowa nie wyższa niż w zamówieniu (wylicza nadpłatę) | błąd |
| Ilość | łączna ilość zafakturowana (także na wcześniejszych FV) ≤ zamówiona | błąd |
| Duplikat | ta sama FV wprowadzona drugi raz (lub ta sama kwota i zamówienie) | błąd / ostrzeżenie |
| Status zamówienia | zamówienie zrealizowane | ostrzeżenie |
| Daty | data w przyszłości, termin 15. dnia miesiąca (art. 106i), data usługi < data zamówienia | błąd / ostrzeżenie |
| Termin płatności | zgodny z umownym (np. 30 dni) | ostrzeżenie |
| Biała lista VAT | (opcjonalnie) status VAT sprzedawcy i rachunek w wykazie MF | błąd |

Wszystkie progi (tolerancje, stawka VAT, statusy, NIP-y) ustawia się w `config.toml`.

## Uruchomienie

Wymagany Python 3.11+.

**Windows:** dwuklik `start.bat` · **Linux/macOS:** `./start.sh`

Przy pierwszym uruchomieniu skrypt tworzy środowisko, instaluje zależności i kopiuje
`config.example.toml` → `config.toml`. Aplikacja działa pod `http://<adres-komputera>:8000`
dla wszystkich w sieci firmowej (port 8000 musi być otwarty w zaporze).

### Odczyt skanów

* **Claude (zalecane)** – ustaw zmienną `ANTHROPIC_API_KEY`. Model AI czyta skany i zdjęcia
  faktur dowolnego układu, także krzywe i słabej jakości. W `config.toml`: `[ocr] silnik = "claude"`.
  Uwaga: plik faktury jest wtedy wysyłany do API Anthropic.
* **Lokalnie** – bez klucza aplikacja czyta PDF-y z warstwą tekstową (np. FV wysłane mailem
  z programu księgowego). Do skanów trzeba zainstalować
  [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) z językiem polskim i Poppler.
  Parser lokalny jest heurystyczny – skuteczny przy typowym układzie FV, dlatego warto
  przejrzeć odczytane pola.

### Portal zamówień

Każdy portal wygląda inaczej, więc konektor ustawia się w sekcji `[portal]` w `config.toml`:

* `tryb = "demo"` – wbudowany portal demonstracyjny (`/demo-portal`, login `demo`/`demo`);
* `tryb = "html"` – logowanie formularzem i odczyt tabel HTML. Ustaw adresy stron, nazwy pól
  formularza i **selektory CSS** (prawy klik na tabeli → *Zbadaj* w przeglądarce);
* `tryb = "playwright"` – to samo przez prawdziwą przeglądarkę, dla portali opartych na JavaScripcie
  (`pip install playwright && playwright install chromium`);
* `tryb = "json"` – jeśli dostawca udostępnia API (token w zmiennej `PORTAL_TOKEN`).

Login i hasło do portalu podaje się w zmiennych środowiskowych `PORTAL_LOGIN` i `PORTAL_HASLO`
(nie w pliku). Jeśli portal pozwala wyeksportować zamówienia do Excela/CSV, można je też
zaimportować przyciskiem **Importuj CSV/XLSX** (kolumny: numer, data, status, kod, nazwa, ilość, jm, cena).

## Przykłady i testy

`przyklady/` zawiera faktury pasujące do portalu demo: poprawną, z zawyżoną ceną,
z przekroczoną ilością i błędem rachunkowym, ze złym VAT i nabywcą oraz skany JPG (w tym duplikat).

```
pip install -r requirements.txt pytest httpx
python -m pytest -q tests
```

## Struktura

```
app/main.py         API (FastAPI) + serwowanie interfejsu
app/ocr.py          odczyt faktur: Claude / pdfplumber / Tesseract + parser
app/portal.py       pobieranie zamówień z portalu, import CSV/XLSX
app/weryfikacja.py  reguły weryfikacji
app/db.py           baza SQLite (dane/baza.sqlite) + skany w dane/skany/
app/demo_portal.py  demonstracyjny portal dostawcy
app/static/         interfejs użytkownika
```
