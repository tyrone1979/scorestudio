@echo off
REM MuseScore plugin launcher — reads request.json, writes result.json
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "%~dp0config.json" (
  > "%~dp0result.json" echo {"ok":false,"error":"config.json missing — run install_musescore_plugin.ps1"}
  exit /b 1
)

set "CFG=%~dp0config.json"
set "PY="
set "ROOT="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "(Get-Content -Raw '%CFG%'|ConvertFrom-Json).python"`) do set "PY=%%I"
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "(Get-Content -Raw '%CFG%'|ConvertFrom-Json).project_root"`) do set "ROOT=%%I"

if "%PY%"=="" (
  > "%~dp0result.json" echo {"ok":false,"error":"python missing in config.json"}
  exit /b 1
)
if "%ROOT%"=="" (
  > "%~dp0result.json" echo {"ok":false,"error":"project_root missing in config.json"}
  exit /b 1
)
if not exist "%PY%" (
  > "%~dp0result.json" echo {"ok":false,"error":"python not found"}
  exit /b 1
)

set "GEN=%ROOT%\generate_score.py"
set "REQ=%~dp0request.json"
if not exist "%GEN%" (
  > "%~dp0result.json" echo {"ok":false,"error":"generate_score.py not found"}
  exit /b 1
)
if not exist "%REQ%" (
  > "%~dp0result.json" echo {"ok":false,"error":"request.json missing"}
  exit /b 1
)

"%PY%" "%GEN%" --request "%REQ%"
exit /b %ERRORLEVEL%
