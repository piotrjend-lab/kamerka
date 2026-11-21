@echo off
rem Uruchamia aplikacje w sieci firmowej: http://<adres-tego-komputera>:8000
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
)
if not exist config.toml copy config.example.toml config.toml
rem set ANTHROPIC_API_KEY=sk-ant-...
rem set PORTAL_LOGIN=...
rem set PORTAL_HASLO=...
.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
