@echo off
REM Installe l'environnement Python (une seule fois).
cd /d "%~dp0"
python -m venv .venv || goto :erreur
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || goto :erreur
echo.
echo Installation OK. Etapes suivantes :
echo   1) colle ta cle API dans config.yaml (llm.api_key)
echo   2) lancer.bat --verifier-flux   (teste les flux RSS)
echo   3) lancer.bat                   (produit le rapport)
pause
exit /b 0
:erreur
echo ECHEC de l'installation.
pause
exit /b 1
