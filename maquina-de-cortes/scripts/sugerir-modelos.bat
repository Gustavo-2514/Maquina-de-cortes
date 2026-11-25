@echo off
REM Sugere os modelos de IA (Whisper e Ollama) que cabem no seu computador.
REM   scripts\sugerir-modelos.bat            so mostra a sugestao
REM   scripts\sugerir-modelos.bat --aplicar  salva no app e oferece baixar o modelo
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\sugerir_modelos.py %*
) else (
  py -3 scripts\sugerir_modelos.py %* 2>nul || python scripts\sugerir_modelos.py %*
)
