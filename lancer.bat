@echo off
REM Lance l'agent sans compiler d'exe (double-clic). Nécessite installer.bat d'abord.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python main.py %*
