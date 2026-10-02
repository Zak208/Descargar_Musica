# -*- mode: python ; coding: utf-8 -*-
# Se quitan componentes de Qt que la aplicación no usa (ahorran espacio en disco y memoria).

import os

# el código (config.py, services, ui) ya va compilado dentro del programa: copiarlo también solo duplicaría el peso
datas = [('assets', 'assets')]
# ffmpeg.exe (opcional: si no está, la app lo descarga la primera vez). ffprobe.exe NO se incluye: no hace falta
# (las conversiones funcionan solo con ffmpeg) y ocupa unos 145 MB.
if os.path.isfile('bin/ffmpeg.exe'):
    datas.append(('bin/ffmpeg.exe', 'bin'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['winrt.windows.media', 'winrt.windows.media.playback', 'winrt.windows.storage.streams',
                   'winrt.windows.foundation', 'winrt.windows.foundation.collections', 'winrt.windows.storage',
                   'PySide6.QtNetwork'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.Qt3DCore', 'PySide6.QtQuick3D', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
              'PySide6.QtBluetooth', 'PySide6.QtSensors', 'PySide6.QtSql', 'PySide6.QtTest'],
    noarchive=False,
    optimize=1,
)

UNUSED = ('opengl32sw.dll', 'Qt6Pdf.dll', 'qpdf.dll', 'qtvirtualkeyboardplugin.dll', 'qtuiotouchplugin.dll')
a.binaries = [b for b in a.binaries if not b[0].lower().endswith(tuple(u.lower() for u in UNUSED))]
a.datas = [d for d in a.datas if 'translations' not in d[0].replace(chr(92), '/').split('/')]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Descargar_Musica',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Descargar_Musica',
)
