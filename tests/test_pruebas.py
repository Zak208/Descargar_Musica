"""Para quien prefiera `pytest`: cada script de dev_tools/prueba_*.py es un test. Uso:  pytest -q"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = sorted((ROOT / "dev_tools").glob("prueba_*.py"))


@pytest.mark.parametrize("script", SCRIPTS, ids=[s.stem for s in SCRIPTS])
def test_script(script):
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "QT_QPA_PLATFORM": "offscreen"},
                          cwd=str(ROOT), timeout=900)
    out = proc.stdout + proc.stderr
    fails = [ln for ln in out.splitlines() if ln.startswith("FALLO")]
    assert not fails, "\n".join(fails)
    assert "Traceback (most recent call last)" not in out
    assert any(ln.strip() == "FIN" for ln in out.splitlines()), "la prueba no llegó a terminar"
