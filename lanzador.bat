@echo off
rem ===========================================================================================================
rem  Descargador de Música — lanzador.bat
rem  Un solo archivo para todo: prepara lo que falte, compila el programa, crea el instalador y lo abre.
rem  Al terminar, el instalador queda aquí, en la carpeta principal:  Descargador_Musica-Setup-vX.Y.Z.exe
rem  (Se puede ejecutar con doble clic.  Con el parámetro  /sin-abrir  crea el instalador pero no lo abre.)
rem ===========================================================================================================
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title Descargador de Música - crear el instalador

set "ABRIR=1"
if /i "%~1"=="/sin-abrir" set "ABRIR=0"

set "INNO_VERSION=6.5.4"
set "INNO_URL=https://github.com/jrsoftware/issrc/releases/download/is-6_5_4/innosetup-6.5.4.exe"
set "INNO_SHA256=fa73bf47a4da250d185d07561c2bfda387e5e20db77e4570004cf6a133cc10b1"
set "VENV=%~dp0venv"
set "PY=%VENV%\Scripts\python.exe"

echo.
echo  ============================================================
echo    Descargador de Música: crear el instalador
echo  ============================================================
echo.

rem ---------------------------------------------------------------- 1. Python
echo  [1/6] Buscando Python...
set "PYBASE="
where py >nul 2>&1 && (py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1 && set "PYBASE=py -3")
if not defined PYBASE (
    where python >nul 2>&1 && (python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1 && set "PYBASE=python")
)
if not exist "%PY%" (
    if not defined PYBASE (
        echo.
        echo  No encuentro Python 3.10 o más nuevo. Instálalo desde https://www.python.org/downloads/
        echo  ^(marca la casilla "Add python.exe to PATH"^) y vuelve a abrir este archivo.
        goto :error
    )
)

rem ---------------------------------------------------------------- 2. Entorno y librerías
echo  [2/6] Preparando las librerías ^(la primera vez tarda unos minutos^)...
if not exist "%PY%" (
    %PYBASE% -m venv "%VENV%"
    if errorlevel 1 goto :error
)
"%PY%" -m pip install --quiet --disable-pip-version-check -r "empaquetado\requirements-build.txt"
if errorlevel 1 goto :error

set "VER="
for /f "tokens=2 delims==" %%v in ('findstr /b /c:"__version__" "src\version.py"') do set "VER=%%v"
set "VER=!VER: =!"
set "VER=!VER:"=!"
if not defined VER goto :error
echo        Versión: %VER%

rem ---------------------------------------------------------------- 3. Compilar el programa
echo  [3/6] Compilando el programa ^(unos minutos^)...
if exist "dist_app\Descargar_Musica" rmdir /s /q "dist_app\Descargar_Musica"
"%PY%" -m PyInstaller --noconfirm --log-level WARN --distpath dist_app --workpath build_tmp "empaquetado\Descargar_Musica.spec"
if errorlevel 1 goto :error
if not exist "dist_app\Descargar_Musica\Descargar_Musica.exe" goto :error

rem ---------------------------------------------------------------- 4. Comprobar lo compilado
echo  [4/6] Comprobando que el programa compilado funciona...
set "QT_QPA_PLATFORM=offscreen"
set "SELFTEST_SIN_FFMPEG=1"
start "" /wait "dist_app\Descargar_Musica\Descargar_Musica.exe" --selftest
set "RESULTADO=!errorlevel!"
set "QT_QPA_PLATFORM="
set "SELFTEST_SIN_FFMPEG="
if exist "dist_app\Descargar_Musica\selftest.log" del /q "dist_app\Descargar_Musica\selftest.log"
if not "!RESULTADO!"=="0" (
    echo  La autocomprobación falló. Mira el mensaje de arriba.
    goto :error
)

rem ---------------------------------------------------------------- 5. Inno Setup (crea el instalador)
echo  [5/6] Creando el instalador...
set "ISCC="
for %%p in ("%~dp0build_tmp\inno\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do (
    if not defined ISCC if exist %%p set "ISCC=%%~p"
)
if not defined ISCC (
    echo.
    echo  Falta Inno Setup %INNO_VERSION%, el programa gratuito que crea instaladores de Windows ^(unos 8 MB^).
    set /p "RESP=  ¿Lo descargo e instalo ahora? [S/N]: "
    if /i not "!RESP!"=="S" (
        echo  Sin Inno Setup no se puede crear el instalador. Puedes bajarlo de https://jrsoftware.org/isdl.php
        goto :error
    )
    echo        Descargando...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%INNO_URL%' -OutFile '%TEMP%\inno_setup.exe' -UseBasicParsing; $h=(Get-FileHash '%TEMP%\inno_setup.exe' -Algorithm SHA256).Hash.ToLower(); if ($h -ne '%INNO_SHA256%') { Write-Host 'La descarga no coincide con la huella esperada.'; exit 1 }"
    if errorlevel 1 goto :error
    echo        Instalando ^(solo para tu usuario^)...
    "%TEMP%\inno_setup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /NOICONS /DIR="%~dp0build_tmp\inno"
    del /q "%TEMP%\inno_setup.exe" >nul 2>&1
    if not exist "%~dp0build_tmp\inno\ISCC.exe" goto :error
    set "ISCC=%~dp0build_tmp\inno\ISCC.exe"
)
del /q "Descargador_Musica-Setup-*.exe" >nul 2>&1
"%ISCC%" /Qp /DAppVersion=%VER% "empaquetado\Descargador.iss"
if errorlevel 1 goto :error
set "SETUP=Descargador_Musica-Setup-v%VER%.exe"
if not exist "%SETUP%" goto :error

rem ---------------------------------------------------------------- 6. Listo
echo  [6/6] Listo.
echo.
echo  ============================================================
echo    Instalador creado en esta carpeta:
echo      %SETUP%
echo  ============================================================
echo.
if "%ABRIR%"=="1" (
    echo  Abriendo el instalador...
    start "" "%~dp0%SETUP%"
)
endlocal
exit /b 0

:error
echo.
echo  ------------------------------------------------------------
echo   No se pudo terminar. Revisa el mensaje de arriba.
echo  ------------------------------------------------------------
echo.
pause
endlocal
exit /b 1
