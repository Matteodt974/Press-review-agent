@echo off
REM ==================================================================
REM  Construit RevueSecurite.exe (Windows) avec PyInstaller.
REM  Prérequis : Python 3.11+ installé ("Add python.exe to PATH" coché).
REM  Résultat : dossier dist\ contenant RevueSecurite.exe + config.yaml
REM ==================================================================
cd /d "%~dp0"

if not exist .venv (
    python -m venv .venv || goto :erreur
)
call .venv\Scripts\activate.bat || goto :erreur
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller || goto :erreur

pyinstaller --noconfirm --onefile --name RevueSecurite ^
  --collect-data docx --collect-data tzdata ^
  --collect-submodules langchain_anthropic --collect-submodules langchain_openai ^
  --hidden-import revue.sources.factory ^
  main.py || goto :erreur

copy /Y config.yaml dist\config.yaml
echo.
echo OK : dist\RevueSecurite.exe est pret.
echo Copie RevueSecurite.exe ET config.yaml dans le dossier de ton choix.
pause
exit /b 0

:erreur
echo.
echo ECHEC de la construction. Lis le message ci-dessus.
pause
exit /b 1
