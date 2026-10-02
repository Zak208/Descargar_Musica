"""Las pruebas trabajan con una carpeta de datos temporal: nunca tocan tus listas, favoritos ni ajustes reales.
Se importa lo primero en cada prueba (antes de importar nada del proyecto)."""
import atexit
import os
import shutil
import sys
import tempfile

if "DESCARGADOR_DATA_DIR" not in os.environ:
    _tmp = tempfile.mkdtemp(prefix="descargador_prueba_")
    os.environ["DESCARGADOR_DATA_DIR"] = _tmp
    atexit.register(shutil.rmtree, _tmp, True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
