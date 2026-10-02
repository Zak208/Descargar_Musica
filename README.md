# Descargador de Música

**Versión actual: 1.6.0** · [Historial de versiones](CHANGELOG.md) · cada versión subida tiene su etiqueta `vX.Y.Z` en GitHub

Aplicación de escritorio para **Windows** que combina un reproductor con aspecto de Spotify y un descargador de música:
buscas una canción, un artista o un álbum, escuchas un adelanto y la descargas a tu equipo en MP3, M4A, FLAC o WAV,
con su portada y sus etiquetas. Todo (listas, favoritos, artistas que sigues, recomendaciones) funciona en local,
sin cuentas ni claves.

> **Aviso legal.** Esta herramienta es para uso personal. Descargar contenido protegido por derechos de autor puede
> estar prohibido en tu país o ir contra las condiciones de uso de las plataformas de origen. Eres responsable del uso
> que le des. Respeta a los artistas: si puedes, apóyalos comprando su música.

---

## Índice

1. [Qué hace](#qué-hace)
2. [Requisitos](#requisitos)
3. [Instalación y ejecución](#instalación-y-ejecución)
4. [Crear el ejecutable (.exe)](#crear-el-ejecutable-exe)
5. [Cómo se usa](#cómo-se-usa)
6. [Cómo funciona por dentro](#cómo-funciona-por-dentro)
7. [Estructura del proyecto](#estructura-del-proyecto)
8. [Datos que guarda y privacidad](#datos-que-guarda-y-privacidad)
9. [Rendimiento y modo ahorro](#rendimiento-y-modo-ahorro)
10. [Pruebas](#pruebas)
11. [Solución de problemas](#solución-de-problemas)
12. [Créditos y licencias de terceros](#créditos-y-licencias-de-terceros)

---

## Qué hace

**Buscar y descargar**
- Buscador único en la barra superior: canciones, artistas y álbumes (con filtros *Todo / Canciones / Artistas / Álbumes*).
  Al llegar al final de los resultados se cargan más automáticamente.
- También acepta enlaces de YouTube (canción o lista) y de Spotify (canción, álbum o lista): de Spotify solo se leen
  los títulos de su página pública y el audio se busca en YouTube; no se usa la API oficial ni ninguna cuenta.
- Escucha un adelanto antes de descargar.
- Descarga una canción, un álbum completo, o «descargar y crear lista» (descarga el álbum y crea una lista con su portada).
- Calidades: *Alta calidad* (MP3 320), *Normal* (MP3 192), *Fidelidad original* (M4A, sin recomprimir), *FLAC* y *WAV*.
  Las canciones vienen de fuentes ya comprimidas, así que FLAC y WAV no suenan mejor: solo ocupan más.
- Panel de **descargas en curso** con el progreso de cada canción.

**Biblioteca al estilo Spotify**
- *Canciones que te gustan* (con pestañas *Todas / Descargadas / Sin descargar*), *Mis descargas* y tus propias listas.
- Listas con filas numeradas como en Spotify: al pasar el ratón el número se convierte en ▶, un clic marca la fila y
  muestra los tres puntitos (menú: añadir a una lista, quitar de la lista, descargar, ir al artista o al álbum…) y un
  doble clic reproduce la canción.
- Listas con portada personalizable, columnas (título, álbum, fecha en que se añadió, duración), orden por cualquier
  columna, buscador y duración total.
- Seguir artistas: aparecen en la barra lateral y en Inicio. Filtros *Todo / Listas / Artistas*.
- La carpeta de música se vigila: si borras o añades archivos desde el Explorador, la app se actualiza sola.

**Descubrir**
- Inicio con recomendaciones calculadas a partir de tu música: *mixes*, artistas y canciones parecidos,
  «porque escuchas a…», novedades de los artistas que sigues, éxitos del momento y exploración por géneros.

**Reproductor**
- Cola, aleatorio, repetir, «anterior» como en Spotify (reinicia pasados 20 s; antes vuelve a la canción previa),
  reproductor pequeño siempre visible, letras sincronizadas y **ecualizador** real (graves, medios y agudos) que está
  siempre activo: con todo en 0 el audio no se toca y solo se procesa si mueves algún control.
- Panel lateral derecho **«En reproducción»**: portada grande, botón «+» para guardar, letra que avanza sola,
  información del artista (seguidores y una breve reseña) y la siguiente canción.
- 12 colores de aplicación.

## Requisitos

- **Windows 10 u 11** (es donde se ha desarrollado y probado; el código no depende de nada exclusivo de Windows salvo detalles menores, como abrir el Explorador).
- **Python 3.12** (para ejecutar desde el código). Con el `.exe` compilado no hace falta instalar nada.
- **Letras**: se oscurecen las frases ya leídas, se subraya la que tienes bajo el ratón y al pulsarla la canción salta a ese
  momento. Si una canción no tiene letra, en las canciones **descargadas** puedes pulsar **«Generar con el sistema»**: el
  programa escucha la canción y escribe lo que canta (con tiempos). Queda marcada como «generada por el sistema» porque puede
  tener errores. Con **«Editar»** (o «Escribir la letra yo») abres un editor dentro de la app para corregirla o escribir la tuya;
  la letra propia manda sobre cualquier otra y se puede restaurar. La primera vez, y solo si aceptas, se descarga el reconocedor
  de voz (whisper.cpp, ≈ 68 MB, con comprobación SHA-256); después funciona sin internet.
- Conexión a internet para buscar, escuchar adelantos, descargar, letras y recomendaciones.
- **FFmpeg** (convierte el audio y aplica el ecualizador). No hace falta instalarlo a mano: si no lo encuentra,
  la aplicación lo descarga sola la primera vez (carpeta `app_data/ffmpeg`).
  Si prefieres tenerlo ya, copia `ffmpeg.exe` y `ffprobe.exe` en una carpeta `bin/` junto a `main.py`.

## Instalación y ejecución

```bash
git clone https://github.com/Zak208/Descargar_Musica.git
cd Descargar_Musica

python -m venv venv
venv\Scripts\activate          # en PowerShell: .\venv\Scripts\Activate.ps1

pip install -r requirements.txt
python main.py
```

Las canciones se guardan por defecto en `Música\Canciones_YouTube` (se puede cambiar en **Ajustes**).

## Crear el ejecutable (.exe)

```bash
pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --distpath dist_app --workpath build_tmp Descargar_Musica.spec
```

También puedes hacer doble clic en `compilar_exe.bat`. El resultado queda en `dist_app\Descargar_Musica\`
(copia esa carpeta completa a otro equipo para usarla; empieza con los datos vacíos).
Si existe la carpeta `bin/` con `ffmpeg.exe` y `ffprobe.exe`, se incluye dentro; si no, la app descargará FFmpeg al abrirse.

Para comprobar que el ejecutable ha quedado bien (iconos, tipografía, librerías, FFmpeg y ausencia de ventanas sueltas):

```bash
Descargar_Musica.exe --selftest        # escribe selftest.log junto al programa
```

## Cómo se usa

| Quiero… | Cómo |
|---|---|
| Buscar | Escribe en la barra de arriba (Intro, o espera un instante). También puedes pegar un enlace. |
| Escuchar / reproducir | Doble clic en la fila (en los resultados de búsqueda, el botón ▶ redondo). |
| Descargar | Botón verde **Descargar**. En un álbum: *Descargar álbum completo* o *Descargar y crear lista*. |
| Guardar una canción | Botón «+» (fila, tarjeta, panel o barra de reproducción): el primer clic la guarda en «Canciones que te gustan»; si ya está guardada, abre la lista de listas para marcarla (✓ verde) o quitarla de cada una. |
| Crear una lista | **+** en *Tu biblioteca* → nombre. Añade canciones con «Añadir canciones» o con el menú `+` de cada canción. |
| Cambiar la imagen de una lista | Pulsa su portada, o clic derecho en la barra lateral. |
| Ordenar una lista | Pulsa los títulos de columna o el botón **Orden**. |
| Seguir a un artista | Botón **Seguir** en su perfil. |
| Ver las descargas en curso | Botón **Descargas** (arriba a la derecha). |
| Más opciones de una canción | Un clic en la fila y los tres puntitos de la derecha, o clic derecho. |
| Ver la portada, la letra y el artista | Botón de panel de la barra de reproducción (**En reproducción**). |
| Ecualizador, cola, letra, reproductor pequeño | Botones de la barra de reproducción. |

**Atajos de teclado:** `Espacio` pausa/reanuda · `←` / `→` retroceden/avanzan 5 s · `M` silencia · `Ctrl+F` va al buscador ·
teclas multimedia del teclado (reproducir, siguiente, anterior).

## Cómo funciona por dentro

```
 Barra superior ──► Búsqueda ──► iTunes Search (canciones, artistas, álbumes)   [services/catalog_service.py]
                         └─────► yt-dlp (enlaces y búsqueda en YouTube)         [services/youtube_service.py]

 Adelanto  ──► yt-dlp obtiene la URL del audio ──► QMediaPlayer
 Descarga  ──► yt-dlp + FFmpeg (conversión) ──► mutagen (título, artista, álbum, portada) ──► carpeta de música

 Carpeta de música ──► LibraryScanWorker (lee etiquetas una vez y las guarda en caché)
                  └──► QFileSystemWatcher (detecta cambios y actualiza la interfaz sin recargarla)

 Recomendaciones ──► perfil de gustos (tus descargas, favoritas y artistas seguidos)
                └──► Deezer (artistas relacionados, populares, géneros, listas de éxitos) + iTunes (novedades)

 Letras ──► LRCLIB (sincronizadas) y lyrics.ovh   ·   Ecualizador ──► copia temporal con filtros de FFmpeg
```

- **Interfaz**: PySide6 (Qt). La ventana principal reparte su lógica en módulos «mixin»
  (`playback_mixin`, `lists_mixin`, `home_mixin`, `search_mixin`, `downloads_mixin`).
- **Ventanas internas**: los cuadros de diálogo se muestran sobre la propia ventana (`ui/overlay.py`), no como
  ventanas aparte. Solo la letra de la canción es una ventana independiente.
- **Reproducción**: se mantiene una *lista de reproducción de contexto* (la lista o página desde la que pulsaste ▶)
  y un historial, de modo que «siguiente» y «anterior» se comportan como en Spotify.
- **Listas sin recargas**: al cambiar algo (añadir, quitar, renombrar, descargar) solo se actualizan las filas afectadas.
- **Imágenes**: un único grupo de 3 hilos con caché en memoria y en disco (`ui/imageloader.py`).
- **Temas**: los colores se definen una vez (`ui/styles.py`) y se aplican a toda la aplicación.

## Estructura del proyecto

```
main.py                    punto de entrada (y --selftest)
config.py                  rutas, ajustes y escritura segura de JSON
Descargar_Musica.spec      configuración de PyInstaller
compilar_exe.bat           atajo para compilar
requirements*.txt          dependencias (ejecución / compilación)
assets/                    iconos SVG, logo y tipografía Poppins
services/                  lógica sin interfaz
    catalog_service.py       búsqueda en iTunes (artistas, álbumes, canciones)
    youtube_service.py       búsqueda, adelanto y descarga con yt-dlp
    spotify_service.py       lectura de enlaces de Spotify
    metadata_service.py      etiquetas y portadas (mutagen)
    library_service.py       biblioteca local, caché de etiquetas y vigilancia de la carpeta
    playlist_service.py      favoritos y listas
    artist_service.py        artistas seguidos
    recommendation_service.py  recomendaciones (Deezer + iTunes)
    lyrics_service.py        letras de internet (solo del artista correcto)
    lyrics_store.py          letras propias y generadas (app_data/letras)
    transcribe_service.py    «generar letra»: reconocimiento de voz local (whisper.cpp)
    equalizer_service.py     ecualizador con FFmpeg
    ffmpeg_service.py        localiza o descarga FFmpeg
ui/                        interfaz
    main_window.py           ventana principal
    *_mixin.py               reproducción, listas, inicio, búsqueda y descargas
    *_page.py                páginas (inicio, lista, biblioteca, artista, álbum)
    track_row.py             fila de canción estilo Spotify (número, ▶ al pasar el ratón, tres puntitos)
    now_playing.py           panel lateral «En reproducción» (se abre solo al reproducir)
    save_popup.py            botón «+» y listita de guardado en listas
    overlay.py, dialogs.py   ventanas internas
    styles.py, covers.py ... estilos, portadas, iconos, animaciones
dev_tools/                 pruebas automáticas
```

## Datos que guarda y privacidad

Todo se guarda en la carpeta `app_data/` junto al programa (no se envía a ningún sitio):

| Archivo | Contenido |
|---|---|
| `settings.json` | calidad, carpeta de descargas, tema, modo ahorro |
| `favoritos.json`, `playlists.json`, `artistas_seguidos.json` | tus listas |
| `historial_descargas.json`, `biblioteca_cache.json` | descargas realizadas y caché de etiquetas |
| `recomendaciones.json` | última recomendación calculada |
| `covers/`, `img_cache/`, `eq_cache/` | imágenes y copias temporales |
| `ffmpeg/` | FFmpeg descargado automáticamente |
| `letras/` | letras que escribes tú o que genera el sistema |
| `whisper/` | reconocedor de voz (solo si aceptas generar letras) |

La aplicación **no usa cuentas, claves ni telemetría**. Lo único que sale de tu equipo son las búsquedas y peticiones
a los servicios públicos que usa (iTunes, Deezer, LRCLIB, lyrics.ovh, YouTube mediante yt-dlp, la página pública de Spotify si pegas un enlace suyo, y la descarga de FFmpeg desde GitHub y, solo si aceptas generar letras, la del reconocedor de voz desde GitHub y Hugging Face).
`app_data/` y los registros están excluidos del repositorio (`.gitignore`) para que tus listas e historial nunca se suban.

## Rendimiento y modo ahorro

Está pensada para equipos modestos. En **Ajustes → Rendimiento** hay un *modo ahorro de recursos* (activado por defecto)
que desactiva animaciones, usa imágenes más ligeras y ralentiza el visualizador. Además:

- las listas largas solo crean las filas visibles (se completan al desplazarse);
- las etiquetas se leen una sola vez y se guardan en caché;
- la biblioteca se vigila con un observador del sistema en lugar de releer la carpeta;
- las imágenes se cachean y se procesan con pocos hilos.

## Pruebas

Se ejecutan sin abrir ventanas, desde la raíz del proyecto (algunas usan internet y tu carpeta de música; limpian lo que crean):

```bash
python dev_tools/prueba_interfaz.py     # ventanas internas, búsqueda, álbumes, orden, vigilancia de la carpeta...
python dev_tools/prueba_listas.py       # listas, artistas, sin recargas
python dev_tools/prueba_detalles.py     # fechas «añadida», rueda lateral, géneros, ventanas sueltas
python dev_tools/prueba_letras.py       # coincidencia de artista, letras propias/generadas, estados de las frases
python dev_tools/prueba_filas.py        # filas estilo Spotify, menú, panel «En reproducción», ecualizador siempre activo
```

## Solución de problemas

- **No suena el adelanto / no descarga**: comprueba tu conexión. YouTube cambia a menudo; actualiza yt-dlp con
  `pip install -U yt-dlp` (si usas el `.exe`, vuelve a compilarlo con la versión nueva).
- **«Falta un componente de audio»**: FFmpeg no se pudo descargar. Copia `ffmpeg.exe` y `ffprobe.exe` en `bin/` o en `app_data/ffmpeg/`.
- **No aparecen los iconos o el texto se ve distinto**: ejecuta `Descargar_Musica.exe --selftest` y revisa `selftest.log`.
- **La app va justa de recursos**: activa el *modo ahorro* en Ajustes.
- **Errores**: se anotan en `app_descargas.log` junto al programa.

## Créditos y licencias de terceros

- Interfaz: [PySide6 / Qt](https://www.qt.io/qt-for-python) (LGPL).
- Descargas: [yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense) y [FFmpeg](https://ffmpeg.org/) (LGPL/GPL según la compilación).
- Etiquetas de audio: [mutagen](https://github.com/quodlibet/mutagen) (GPL).
- Tipografía: [Poppins](https://fonts.google.com/specimen/Poppins) (SIL Open Font License, incluida en `assets/fonts/OFL.txt`).
- Datos: iTunes Search API, Deezer API, [LRCLIB](https://lrclib.net/) y lyrics.ovh.

Este proyecto no está afiliado a Spotify, YouTube, Apple ni Deezer. Los nombres y marcas pertenecen a sus propietarios.
