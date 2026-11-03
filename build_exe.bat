@echo off
REM Wymaga Pythona 3.9+ z https://python.org (zaznacz "Add to PATH")
python -m pip install -r requirements.txt
python -m PyInstaller --noconsole --onefile --name KameraUSB kamera_usb.py
echo.
echo Gotowe: dist\KameraUSB.exe
pause
