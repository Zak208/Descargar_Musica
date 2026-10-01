@echo off
title Compilando Descargador de Musica

echo ============================================================
echo   Compilando la aplicacion (.exe)
echo ============================================================
echo.

pip install -r requirements-build.txt

echo.
echo Generando el ejecutable...
python -m PyInstaller --noconfirm --distpath dist_app --workpath build_tmp Descargar_Musica.spec

echo.
echo ============================================================
echo   Listo. Encontraras la aplicacion en: dist_app\Descargar_Musica
echo   Para llevarla a otro equipo copia esa carpeta completa.
echo ============================================================
