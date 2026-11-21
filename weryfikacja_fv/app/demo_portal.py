"""Demonstracyjny portal zamówień firmy spiekającej (login: demo / hasło: demo).

Symuluje zewnętrzną stronę, z której aplikacja pobiera zamówienia. Służy do przetestowania
konektora 'html' (selektory w config.example.toml pasują do tego portalu).
"""
from __future__ import annotations

from html import escape

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

DOSTAWCA_NIP = "6772345618"

ZAMOWIENIA = {
    "ZAM/2026/0451": {"data": "2026-10-02", "status": "zrealizowane", "pozycje": [
        ("SP-1020", "Spiekanie tulei Fe-Cu fi12", 5000, "szt", 0.85),
        ("SP-2210", "Spiekanie koła zębatego z=24", 1200, "szt", 2.40)]},
    "ZAM/2026/0458": {"data": "2026-10-09", "status": "zrealizowane", "pozycje": [
        ("SP-3105", "Spiekanie wsadu proszkowego - piec taśmowy", 850, "kg", 6.20)]},
    "ZAM/2026/0470": {"data": "2026-10-20", "status": "w realizacji", "pozycje": [
        ("SP-1020", "Spiekanie tulei Fe-Cu fi12", 3000, "szt", 0.85)]},
    "ZAM/2026/0477": {"data": "2026-11-03", "status": "zrealizowane", "pozycje": [
        ("SP-4400", "Spiekanie i kalibracja pierścieni", 2000, "szt", 1.15),
        ("SP-4401", "Hartowanie po spiekaniu", 2000, "szt", 0.35)]},
}

router = APIRouter(prefix="/demo-portal", include_in_schema=False)

STYL = """<style>body{font-family:system-ui;margin:2rem;color:#222}table{border-collapse:collapse}
td,th{border:1px solid #bbb;padding:.3rem .6rem}th{background:#eee}header{background:#7a2e0e;color:#fff;
padding:.6rem 1rem;margin:-2rem -2rem 1.5rem}</style>"""


def _strona(tresc: str) -> str:
    return f"<!doctype html><meta charset=utf-8><title>SpiekPol - portal klienta</title>{STYL}" \
           f"<header><b>SpiekPol</b> · portal zamówień klienta (DEMO)</header>{tresc}"


def _zalogowany(request: Request) -> bool:
    return request.cookies.get("demo_sesja") == "ok"


def html_szczegolow(numer: str) -> str:
    z = ZAMOWIENIA[numer]
    wiersze = "".join(
        f"<tr><td>{k}</td><td>{escape(n)}</td><td>{i}</td><td>{jm}</td><td>{c:.2f}</td>"
        f"<td>{i * c:.2f}</td></tr>"
        for k, n, i, jm, c in z["pozycje"]
    )
    return _strona(
        f"<h2>Zamówienie <span class=numer>{numer}</span></h2>"
        f"<p>Data: <span class=data>{z['data']}</span> · Status: <span class=status>{z['status']}</span>"
        f" · NIP wykonawcy: <span class=dostawca-nip>{DOSTAWCA_NIP}</span></p>"
        f"<table id=pozycje><thead><tr><th>Indeks</th><th>Opis usługi</th><th>Ilość</th><th>J.m.</th>"
        f"<th>Cena netto</th><th>Wartość netto</th></tr></thead><tbody>{wiersze}</tbody></table>"
        f"<p><a href='/demo-portal/zamowienia'>&larr; lista</a></p>"
    )


@router.get("/login", response_class=HTMLResponse)
def login_form():
    return _strona("<form method=post><p>Login: <input name=login></p><p>Hasło: <input name=haslo "
                   "type=password></p><button>Zaloguj</button></form><p><small>demo / demo</small></p>")


@router.post("/login")
def login(login: str = Form(...), haslo: str = Form(...)):
    if login == "demo" and haslo == "demo":
        r = RedirectResponse("/demo-portal/zamowienia", status_code=303)
        r.set_cookie("demo_sesja", "ok")
        return r
    return RedirectResponse("/demo-portal/login", status_code=303)


@router.get("/zamowienia", response_class=HTMLResponse)
def lista(request: Request):
    if not _zalogowany(request):
        return RedirectResponse("/demo-portal/login", status_code=303)
    wiersze = "".join(
        f"<tr><td><a href='zamowienia/{n}'>{n}</a></td><td>{z['data']}</td><td>{z['status']}</td>"
        f"<td>{sum(i * c for _, _, i, _, c in z['pozycje']):.2f}</td></tr>"
        for n, z in ZAMOWIENIA.items()
    )
    return _strona("<h2>Zamówienia</h2><table id=zamowienia><thead><tr><th>Numer</th><th>Data</th>"
                   f"<th>Status</th><th>Netto</th></tr></thead><tbody>{wiersze}</tbody></table>")


@router.get("/zamowienia/{numer:path}", response_class=HTMLResponse)
def szczegoly(numer: str, request: Request):
    if not _zalogowany(request):
        return RedirectResponse("/demo-portal/login", status_code=303)
    if numer not in ZAMOWIENIA:
        return HTMLResponse(_strona("<p>Nie znaleziono zamówienia</p>"), status_code=404)
    return html_szczegolow(numer)
