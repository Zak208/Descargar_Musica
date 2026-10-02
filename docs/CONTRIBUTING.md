# Cómo trabajar en el proyecto

## Preparar el entorno
```bash
python -m venv venv
venv\Scripts\activate
pip install -r empaquetado/requirements.lock.txt      # versiones exactas (o requirements.txt para los mínimos)
pip install ruff pytest                   # herramientas de calidad
```

## Antes de subir un cambio
1. `ruff check src` → sin avisos (`ruff check --fix` arregla los sencillos).
2. `python pruebas/ejecutar_pruebas.py` (o `pytest -q`) → todas las pruebas en verde. Si tocas algo, añade una prueba
   en `pruebas/prueba_*.py`: cada script imprime `OK`/`FALLO` y termina con `FIN`.
3. Sube la versión en `src/version.py`, añade su sección en `docs/CHANGELOG.md` y actualiza «Versión actual» en `README.md`.
4. Commit, etiqueta `vX.Y.Z` y `git push origin HEAD --tags`: la publicación automática compila el `.exe`, lo comprueba con
   `--selftest`, crea el instalador y publica la versión en GitHub.

## Reglas del proyecto
- **Poco consumo**: nada de sondeos con temporizadores si Qt avisa por señal; tareas pesadas con `heavy_task()`;
  lecturas de disco o red siempre fuera del hilo de la interfaz.
- **Datos**: todo JSON se lee con `config.read_json` y se escribe con `config.atomic_write_json`. Nunca con `open()` directo.
- **Páginas**: usa `ui.pages.Page`, no números sueltos.
- **Textos** para el usuario en español claro y sin tecnicismos.
- **Privacidad**: nada de datos personales en el registro, los informes ni las peticiones. Respeta el modo privado
  (`network_service.private_mode()`) y el modo sin conexión.
- **Actualizaciones**: las versiones se buscan en la web de GitHub (`releases/latest`), no en la API (tiene límite de peticiones).
- `src/ui/main_window.py` solo coordina; la lógica nueva va en un mixin (`src/ui/*_mixin.py`) o en `src/services/`.
- **Un solo `.bat` en la carpeta principal** (`lanzador.bat`): todo lo demás vive en su carpeta (`src`, `empaquetado`, `docs`, `pruebas`).
- Probar el empaquetado de verdad: `lanzador.bat /sin-abrir` (compila, comprueba y crea el instalador).
