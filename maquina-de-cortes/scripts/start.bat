@echo off
rem Abre a Maquina de Cortes em http://localhost:8000 (NAO TESTADO no Windows).
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
  echo A instalacao ainda nao foi feita. Rode primeiro: scripts\setup.ps1
  pause
  exit /b 1
)
.venv\Scripts\python.exe run.py %*
