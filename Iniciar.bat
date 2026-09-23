@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto erro
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto erro
if not exist config.json copy config.exemplo.json config.json >nul
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto erro
exit /b
:erro
echo Nao foi possivel iniciar. Confira a mensagem acima e o LEIA-ME.
pause
