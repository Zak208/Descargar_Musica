"""Ejecuta todas las pruebas (pruebas/prueba_*.py) una detrás de otra y devuelve un código de salida distinto de 0 si
alguna falla (línea «FALLO», error de Python o no llega a imprimir «FIN»). Uso:
    python pruebas/ejecutar_pruebas.py            # todas
    python pruebas/ejecutar_pruebas.py letras     # solo las que contengan «letras» en el nombre"""
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    wanted = sys.argv[1:]
    scripts = sorted(p for p in HERE.glob("prueba_*.py") if not wanted or any(w in p.name for w in wanted))
    env = dict(os.environ, PYTHONIOENCODING="utf-8", QT_QPA_PLATFORM="offscreen")
    bad = []
    for script in scripts:
        started = time.time()
        try:
            proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", env=env, timeout=900, cwd=str(HERE.parent))
            out = (proc.stdout or "") + (proc.stderr or "")
            timed_out = False
        except subprocess.TimeoutExpired as e:
            out, timed_out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), True
        fails = [ln for ln in out.splitlines() if ln.startswith("FALLO")]
        crashed = "Traceback (most recent call last)" in out
        finished = any(ln.strip() == "FIN" for ln in out.splitlines())
        ok = not fails and not crashed and finished and not timed_out
        print(f"{'OK   ' if ok else 'FALLO'} {script.name} ({time.time() - started:.0f} s)", flush=True)
        if not ok:
            bad.append(script.name)
            for ln in fails[:10]:
                print("      ", ln, flush=True)
            if crashed:
                print("       (error de Python)", flush=True)
            if timed_out:
                print("       (tiempo agotado)", flush=True)
            elif not finished and not fails and not crashed:
                print("       (no llegó a terminar)", flush=True)
    print(f"\n{len(scripts) - len(bad)} de {len(scripts)} pruebas correctas", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
