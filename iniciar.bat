@echo off
rem ===========================================================================================================
rem  Descargador de Música — iniciar.bat
rem  Abre el programa desde el código (la versión en la que se está trabajando), para probarlo sin compilar nada.
rem  La primera vez prepara el entorno de Python y las librerías; las siguientes abre directamente.
rem  Si cambia requirements.txt, instala solo lo nuevo la próxima vez que se abra.
rem  Usa los datos de desarrollo (carpeta app_data de aquí), no los del programa instalado.
rem  Si algo falla, esta ventana se queda abierta con el error.
rem ===========================================================================================================
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Descargador de Música - versión en desarrollo

set "VENV=%~dp0venv"
set "PY=%VENV%\Scripts\python.exe"
set "LISTO=%VENV%\.librerias-instaladas"

if not exist "%PY%" call :crear_entorno
if not exist "%PY%" goto :error

rem Las librerías se instalan si faltan o si requirements.txt es más nuevo que la última instalación
set "HACE_FALTA="
if not exist "%LISTO%" set "HACE_FALTA=1"
if exist "%LISTO%" for /f %%n in ('powershell -NoProfile -Command "if ((Get-Item 'requirements.txt').LastWriteTime -gt (Get-Item '%LISTO%').LastWriteTime) { 1 }"') do set "HACE_FALTA=1"
if defined HACE_FALTA (
    echo  Instalando las librerías ^(solo cuando hace falta, la primera vez tarda unos minutos^)...
    "%PY%" -m pip install --quiet --disable-pip-version-check -r requirements.txt
    if errorlevel 1 goto :error
    echo ok> "%LISTO%"
)

echo  Abriendo el Descargador de Música ^(versión en desarrollo^)...
echo  ^(Puede estar abierto a la vez que el programa instalado: cada uno usa sus propios datos.^)
"%PY%" src\main.py %*
if errorlevel 1 goto :error
exit /b 0

:crear_entorno
echo  Preparando el entorno de Python ^(solo la primera vez^)...
set "PYBASE="
where py >nul 2>&1 && (py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1 && set "PYBASE=py -3")
if not defined PYBASE where python >nul 2>&1 && (python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1 && set "PYBASE=python")
if not defined PYBASE (
    echo.
    echo  No encuentro Python 3.10 o más nuevo. Instálalo desde https://www.python.org/downloads/
    echo  ^(marca la casilla "Add python.exe to PATH"^) y vuelve a abrir este archivo.
    exit /b 1
)
%PYBASE% -m venv "%~dp0venv"
exit /b %errorlevel%

:error
echo.
echo  Algo ha fallado. Copia lo que pone arriba si necesitas ayuda.
pause
exit /b 1
