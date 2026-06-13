@echo off
:: Lanzador Margo · Nelí — sin ventana de terminal
:: Usa Python directamente (código actualizado).
:: Para recompilar el .exe: python -m PyInstaller margo.spec --noconfirm

set "DIR=%~dp0"
set "PY=%DIR%app_qt.py"
set "LOG=%DIR%startup_error.txt"

cd /d "%DIR%"
start "" pythonw "%PY%"
