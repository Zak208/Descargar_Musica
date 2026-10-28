@echo off
rem ===========================================================================================================
rem  Descargador de Música — iniciar.bat
rem  Abre el programa desde el código (la versión en la que se está trabajando), para probarlo sin compilar nada.
rem  La primera vez prepara el entorno de Python y las librerías; las siguientes abre directamente.
rem  Usa los datos de desarrollo (carpeta app_data de aquí), no los del programa instalado.
rem  Si algo falla, esta ventana se queda abierta con el error.
rem ===========================================================================================================
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Descargador de Música - versión en desarrollo

set "VENV=%~dp0venv"
set "PY=%VENV%\Scripts\python.exe"

if not exist "%PY%" (
    echo  Preparando el entorno de Python ^(solo la primera vez, tarda unos minutos^)...
    set "PYBASE="
    where py >nul 2>&1 && set "PYBASE=py -3"
    if not defined PYBASE where python >nul 2>&1 && set "PYBASE=python"
    if not defined PYBASE (
        echo.
        echo  No encuentro Python. Instálalo desde https://www.python.org/downloads/
        echo  ^(marca la casilla "Add python.exe to PATH"^) y vuelve a abrir este archivo.
        goto :error
    )
    call %%PYBASE%% -m venv "%~dp0venv"
    if errorlevel 1 goto :error
    "%PY%" -m pip install --quiet --disable-pip-version-check -r requirements.txt
    if errorlevel 1 goto :error
)

echo  Abriendo el Descargador de Música ^(versión en desarrollo^)...
echo  ^(Puede estar abierto a la vez que el programa instalado: cada uno usa sus propios datos.^)
"%PY%" src\main.py %*
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo  Algo ha fallado. Copia lo que pone arriba si necesitas ayuda.
pause
exit /b 1
