#!/usr/bin/env bash
# Uruchamia aplikację w sieci firmowej: http://<adres-tego-komputera>:8000
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }
[ -f config.toml ] || cp config.example.toml config.toml
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
