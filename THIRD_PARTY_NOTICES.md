# Software de terceros

El programa usa y/o descarga los siguientes componentes. Cada uno mantiene su propia licencia.

| Componente | Para qué | Licencia | Cómo llega |
|---|---|---|---|
| [PySide6 / Qt 6](https://www.qt.io/qt-for-python) | Interfaz y reproducción | LGPL v3 | Incluido en el programa |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Buscar y descargar audio | Unlicense | Incluido; se actualiza solo desde su web oficial (con SHA-256) |
| [mutagen](https://github.com/quodlibet/mutagen) | Etiquetas de los archivos | GPL v2+ | Incluido |
| [requests](https://github.com/psf/requests) | Peticiones web | Apache 2.0 | Incluido |
| [FFmpeg](https://ffmpeg.org/) (builds de [BtbN](https://github.com/BtbN/FFmpeg-Builds)) | Convertir audio | GPL v3 | **No se incluye**: se descarga la primera vez (con SHA-256) |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) y modelo `ggml-base` de OpenAI Whisper | Generar y sincronizar letras sin internet | MIT | **No se incluye**: se descarga si el usuario lo acepta (con SHA-256) |
| [Poppins](https://fonts.google.com/specimen/Poppins) | Tipografía | SIL Open Font License 1.1 | Incluido |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | Crear el instalador | Licencia de Inno Setup | Solo al publicar versiones |

Las letras se consultan en servicios públicos (LRCLIB, lyrics.ovh) y la información de artistas en Deezer, iTunes y
Wikipedia, solo cuando el usuario no ha activado el **modo privado** ni el modo sin conexión.

**Nota de licencias.** El código de este proyecto es MIT (ver `LICENSE`). El programa compilado incluye mutagen (GPL v2+) y
Qt/PySide6 (LGPL v3): quien redistribuya el `.exe` debe respetar también esas licencias (el código fuente de todo está
disponible: este repositorio y los de cada componente).
