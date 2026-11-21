"""Modele danych: faktura (odczytana ze skanu) i zamówienie (pobrane z portalu)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PozycjaFaktury(BaseModel):
    nazwa: str = Field(description="Nazwa usługi/towaru, np. 'Usługa spiekania detalu XYZ-123'")
    kod: str | None = Field(default=None, description="Indeks / kod detalu, jeśli występuje")
    numer_zamowienia: str | None = Field(default=None, description="Numer zamówienia przypisany do pozycji, jeśli podany")
    ilosc: float | None = None
    jm: str | None = Field(default=None, description="Jednostka miary: kg, szt, t ...")
    cena_netto: float | None = Field(default=None, description="Cena jednostkowa netto")
    stawka_vat: float | None = Field(default=None, description="Stawka VAT w procentach, np. 23")
    wartosc_netto: float | None = None
    wartosc_vat: float | None = None
    wartosc_brutto: float | None = None


class Faktura(BaseModel):
    numer: str | None = Field(default=None, description="Numer faktury")
    data_wystawienia: str | None = Field(default=None, description="Data wystawienia w formacie RRRR-MM-DD")
    data_sprzedazy: str | None = Field(default=None, description="Data sprzedaży / wykonania usługi, RRRR-MM-DD")
    termin_platnosci: str | None = Field(default=None, description="Termin płatności, RRRR-MM-DD")
    sprzedawca_nazwa: str | None = None
    sprzedawca_nip: str | None = Field(default=None, description="NIP sprzedawcy, same cyfry")
    nabywca_nazwa: str | None = None
    nabywca_nip: str | None = Field(default=None, description="NIP nabywcy, same cyfry")
    numery_zamowien: list[str] = Field(default_factory=list, description="Wszystkie numery zamówień / WZ wymienione na fakturze")
    pozycje: list[PozycjaFaktury] = Field(default_factory=list)
    suma_netto: float | None = None
    suma_vat: float | None = None
    suma_brutto: float | None = None
    waluta: str | None = Field(default="PLN")
    rachunek: str | None = Field(default=None, description="Numer rachunku bankowego sprzedawcy, same cyfry")


class PozycjaZamowienia(BaseModel):
    kod: str | None = None
    nazwa: str
    ilosc: float
    jm: str | None = None
    cena_netto: float | None = None


class Zamowienie(BaseModel):
    numer: str
    data: str | None = None
    dostawca_nip: str | None = None
    status: str | None = None
    pozycje: list[PozycjaZamowienia] = Field(default_factory=list)

    @property
    def wartosc_netto(self) -> float:
        return round(sum((p.cena_netto or 0) * p.ilosc for p in self.pozycje), 2)


class Uwaga(BaseModel):
    poziom: str  # "blad" | "ostrzezenie" | "info"
    regula: str
    opis: str


class WynikWeryfikacji(BaseModel):
    status: str  # "OK" | "UWAGI" | "BLEDY"
    uwagi: list[Uwaga] = Field(default_factory=list)
