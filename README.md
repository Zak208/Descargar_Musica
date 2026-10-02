# Descargador de Música

**Versión actual: 1.15.0** · [Historial de versiones](CHANGELOG.md) · cada versión subida tiene su etiqueta `vX.Y.Z` en GitHub

Aplicación de escritorio para **Windows** que combina un reproductor con aspecto de Spotify y un descargador de música:
buscas una canción, un artista o un álbum, escuchas un adelanto y la descargas a tu equipo en MP3, M4A, FLAC o WAV,
con su portada, sus etiquetas y su letra. Todo (listas, favoritos, artistas que sigues, recomendaciones) funciona en
local, sin cuentas ni claves. Está pensada para gastar muy poco y para que cualquiera pueda usarla sin saber de
informática. **Tu música descargada y tus listas funcionan también sin internet.**

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
6. [Sin conexión](#sin-conexión)
7. [Cómo funciona por dentro](#cómo-funciona-por-dentro)
8. [Estructura del proyecto](#estructura-del-proyecto)
9. [Datos que guarda y privacidad](#datos-que-guarda-y-privacidad)
10. [Rendimiento y consumo](#rendimiento-y-consumo)
11. [Pruebas](#pruebas)
12. [Solución de problemas](#solución-de-problemas)
13. [Publicar una versión](#publicar-una-versión)
14. [Créditos y licencias de terceros](#créditos-y-licencias-de-terceros)

---

## Qué hace

**Buscar y descargar**
- Buscador único en la barra superior: canciones, artistas y álbumes (con filtros *Todo / Canciones / Artistas / Álbumes*).
  Al llegar al final de los resultados se cargan más automáticamente.
- También acepta enlaces de YouTube (canción o lista) y de Spotify (canción, álbum o lista): de Spotify solo se leen
  los títulos de su página pública y el audio se busca en YouTube; no se usa la API oficial ni ninguna cuenta.
  Puedes **pegar un enlace con Ctrl+V** en cualquier sitio o **soltarlo sobre la ventana**.
- Escucha un adelanto antes de descargar.
- Descarga una canción, un álbum completo, o «descargar y crear lista» (descarga el álbum y crea una lista con su portada).
- **Elige la versión correcta**: compara las duraciones de los resultados de YouTube, comprueba el archivo descargado y,
  si no es lo esperado (otra versión, archivo dañado o no disponible), prueba solo con otra (hasta 3 intentos).
- Calidades explicadas con lo que ocupa una canción de unos 4 minutos: *Alta calidad* (MP3 320, ≈ 9 MB), *Normal*
  (MP3 192, ≈ 6 MB), *Ahorrar espacio* (MP3 128, ≈ 4 MB), *Fidelidad original* (M4A sin recomprimir), *FLAC* y *WAV*.
  Las canciones vienen de fuentes ya comprimidas, así que FLAC y WAV no suenan mejor: solo ocupan más.
- Organización opcional: todas juntas (por defecto), una carpeta por artista, o artista y álbum.
- Panel de **descargas en curso** con progreso, **cola con pausa, reanudar y cancelar**, aviso si va a faltar espacio en
  el disco y confirmación con el tamaño estimado cuando descargas mucho.
- La letra se guarda **dentro del archivo** (etiquetas ID3/MP4/FLAC) para que viaje con la canción y funcione sin internet.

**Biblioteca al estilo Spotify**
- *Canciones que te gustan* (con pestañas *Todas / Descargadas / Sin descargar*), *Mis descargas* y tus propias listas.
- Filas numeradas: al pasar el ratón el número se convierte en ▶ (un clic sobre él reproduce), un clic marca la fila y
  muestra los tres puntitos (añadir a una lista, quitar, descargar, ir al artista o al álbum…) y un doble clic reproduce.
- **Selección múltiple** (Ctrl o Mayús + clic) con barra de acciones: añadir a una lista, reproducir a continuación,
  descargar, quitar de la lista o enviar a la papelera. Se pueden **arrastrar** (una o varias) a una lista de la barra
  lateral, y dentro de una playlist **arrastrar para reordenar**.
- **Deshacer** (botón o Ctrl+Z, 90 s) al quitar de una lista, de favoritas, dejar de seguir a un artista o eliminar una
  lista; borrar una canción la manda a la **papelera de Windows**.
- Listas con portada personalizable, columnas (título, álbum, fecha en que se añadió, duración), orden por cualquier
  columna, buscador y duración total. Manejo con teclado: ↑ ↓, Intro, Supr, Esc.
- **Listas automáticas** (se arman solas): añadidas esta semana, canciones largas, lo más escuchado, aún sin escuchar,
  sin artista o álbum. Más **«Mixes de tu música»**, **«Lo más escuchado»** y **«Redescubre»** en Inicio (estadísticas
  locales: nada se envía a ningún sitio).
- En *Mis descargas* → «…»: **buscar canciones repetidas** (propone quedarse con la de mejor calidad) y **mejorar los
  datos** (artista, álbum y portada) buscando la ficha más parecida; tú revisas antes de aplicar.
- Seguir artistas: aparecen en la barra lateral y en Inicio. La carpeta de música se vigila y la app se actualiza sola.

**Descubrir**
- Inicio con recomendaciones calculadas a partir de tu música: *mixes*, artistas y canciones parecidos,
  «porque escuchas a…», novedades de los artistas que sigues, éxitos del momento y exploración por géneros.

**Reproductor**
- Cola, aleatorio, repetir, «anterior» como en Spotify, reproductor pequeño siempre visible y **ecualizador** real
  (graves, medios y agudos, con ajustes como Auriculares o Noche) que está siempre activo: con todo en 0 el audio no se toca.
- **Botón del reloj** en la barra: *temporizador para dormir* (con bajada gradual del volumen, o «al terminar la
  canción»), *velocidad* de reproducción, *repetir un tramo* A-B, *fundido* entre canciones e **igualar el volumen entre
  canciones** (se mide una vez con FFmpeg y se guarda).
- **Control multimedia de Windows** (título y portada en el panel del sistema; botones de auriculares y teclados) y
  **controles en la bandeja** del sistema, con opción de seguir sonando al cerrar la ventana.
- Se **sigue donde lo dejaste**: volumen, canción y punto en que iba, cola, lista abierta, aleatorio/repetir, panel y
  tamaño de la ventana.
- Panel lateral derecho **«En reproducción»**: portada grande, botón «+» para guardar, letra que avanza sola,
  información del artista y la siguiente canción.
- **Letras** (panel lateral y ventana propia, con pantalla completa en F11): se oscurecen las frases ya leídas, se
  subraya la que tienes bajo el ratón y al pulsarla la canción salta a ese momento. Si una canción no tiene letra, en
  las **descargadas** puedes pulsar **«Generar con el sistema»** (el programa escucha la canción y escribe lo que canta,
  con tiempos; queda marcada como generada porque puede tener errores). Con **«Editar»** abres un editor sencillo:
  escribes o pegas la letra y puedes **ponerles los tiempos automáticamente** (el sistema escucha la canción y encaja
  tu texto; en las pruebas el error mediano es de 0,4 s) o **marcarlos con la barra espaciadora** mientras suena.
  La letra propia manda sobre cualquier otra y se puede restaurar. La primera vez, y solo si aceptas, se descarga el
  reconocedor de voz (whisper.cpp, ≈ 68 MB, con comprobación SHA-256); después funciona sin internet.
- 12 colores de aplicación, **tamaño de la aplicación** (100/115/130 %) y **alto contraste** (Ajustes → Accesibilidad).
- **Fundido cruzado entre canciones** (2 a 12 s): la siguiente empieza mientras la actual baja el volumen. Con el
  **aleatorio**, «A continuación» enseña exactamente la canción que va a sonar.
- **Animaciones con cuidado del consumo**: tres niveles (Ninguna / Suaves / Completas) en Ajustes → Rendimiento, que
  siguen la preferencia de Windows, bajan solas con batería baja, y un medidor de consumo con «Probar animaciones».
  Transiciones entre páginas, portadas que viajan, letras que se rellenan al cantarse, visualizador que sigue la música,
  pantalla completa «Ahora suena» (F11), avisos con icono, esqueletos de carga, botones en la miniatura de la barra de
  tareas y progreso de descargas en su icono, y más (ver el historial de versiones).

**Cuidado de tus datos**
- Tus datos viven en `%APPDATA%\Descargador de Música`, **fuera de la carpeta del programa**: actualizar o mover el
  `.exe` nunca los borra. Hay **copia de seguridad en un clic** (y una automática cada semana), restauración,
  **«Liberar espacio»** y un **informe de problemas sin datos personales** (Ayuda).
- **Actualizaciones**: el motor de descargas (yt-dlp) se actualiza por separado (desde Ayuda o con el mismo botón azul de
  abajo) para que las descargas sigan funcionando cuando YouTube cambia algo.
- **Modo privado, listas M3U y acceso a YouTube**: en Ajustes puedes impedir que la aplicación busque nada por su cuenta, exportar e importar tus listas en M3U y elegir cómo se presenta ante YouTube (con cookies del navegador opcionales).
- **Karaoke por palabras**: la letra sincronizada rellena cada palabra a su ritmo (sílabas y ritmo de la canción); en
  canciones descargadas, con el reconocedor de voz instalado, se miden una vez los tiempos reales de cada palabra.
- **La aplicación se actualiza sola desde GitHub**: cuando subes una versión nueva (etiqueta `vX.Y.Z`) y en otro ordenador
  tienes una anterior, ahí aparece un **botón azul arriba a la izquierda**: primero se descarga (se comprueba su huella
  SHA-256) y luego pone **«Reiniciar y actualizar a la X»**. Con la aplicación abierta se mira cada 10 minutos, sin
  reiniciar; al volver a abrirla avisa de a qué versión se actualizó. Hace falta la 1.12 o posterior en
  cada ordenador (la primera vez se instala a mano desde Releases).
- **Asistente de bienvenida** de 3 pasos y **recorrido guiado** (Ayuda).

## Licencia

Código bajo licencia [MIT](LICENSE). Los componentes de terceros que usa están en [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Para colaborar: [CONTRIBUTING.md](CONTRIBUTING.md).

## Requisitos

- **Windows 10 u 11** (es donde se ha desarrollado y probado).
- **Python 3.12** (para ejecutar desde el código). Con el `.exe` compilado no hace falta instalar nada.
- Conexión a internet para buscar, escuchar adelantos, descargar y recomendaciones. **Sin ella** sigues escuchando y
  organizando tu música descargada.
- **FFmpeg** (convierte el audio y aplica el ecualizador). No hace falta instalarlo a mano: si no lo encuentra,
  la aplicación lo descarga sola la primera vez. Si prefieres tenerlo ya, copia `ffmpeg.exe` en una carpeta `bin/` junto
  a `main.py` (`ffprobe.exe` no hace falta).

## Instalación y ejecución

**Como una aplicación más de Windows (lo normal):** en [Releases](https://github.com/Zak208/Descargar_Musica/releases) descarga `Descargador_Musica-Setup-vX.Y.Z.exe` y ábrelo. Se instala solo para tu usuario (sin permisos de administrador), crea el acceso en el menú Inicio y aparece en **Configuración de Windows → Aplicaciones → Aplicaciones instaladas**, desde donde se desinstala (tus listas y ajustes se conservan). Después se actualiza sola con el botón azul.

**Desde el código:**

```bash
git clone https://github.com/Zak208/Descargar_Musica.git
cd Descargar_Musica

python -m venv venv
venv\Scripts\activate          # en PowerShell: .\venv\Scripts\Activate.ps1

pip install -r requirements.txt
python main.py
```

Las canciones se guardan por defecto en `Música\Canciones_YouTube` (se puede cambiar en **Ajustes**). Ejecutando desde el
código, los datos se guardan en la carpeta `app_data/` del proyecto.

## Crear el ejecutable (.exe)

```bash
pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --distpath dist_app --workpath build_tmp Descargar_Musica.spec
```

También puedes hacer doble clic en `compilar_exe.bat`. El resultado queda en `dist_app\Descargar_Musica\` (≈ 270 MB con
FFmpeg; copia esa carpeta completa a otro equipo para usarla). Si existe `bin/ffmpeg.exe`, se incluye dentro (sin
`ffprobe.exe`, que no hace falta y ocupa ~145 MB); si no, la app descargará FFmpeg al abrirse.

Para comprobar que el ejecutable ha quedado bien (iconos, tipografía, índice SQLite, yt-dlp, control multimedia, FFmpeg y
ausencia de ventanas sueltas; trabaja con datos temporales, nunca con los tuyos):

```bash
Descargar_Musica.exe --selftest        # escribe selftest.log junto al programa
```

## Cómo se usa

| Quiero… | Cómo |
|---|---|
| Buscar | Escribe en la barra de arriba (Intro, o espera un instante). También puedes pegar (Ctrl+V) o soltar un enlace. |
| Escuchar / reproducir | Doble clic en la fila, o clic sobre el ▶ que sale en lugar del número. |
| Descargar | Botón verde **Descargar**. En un álbum: *Descargar álbum completo* o *Descargar y crear lista*. |
| Guardar una canción | Botón «+»: el primer clic la guarda en «Canciones que te gustan»; si ya está guardada, abre la lista de listas para marcarla (✓ verde) o quitarla de cada una. |
| Crear una lista | **+** en *Tu biblioteca* → nombre; o arrastra canciones sobre una lista de la barra lateral. |
| Marcar varias canciones | Ctrl + clic (suma) o Mayús + clic (rango); aparece una barra con acciones. |
| Reordenar una playlist | Arrastra las canciones dentro de la lista (con su orden propio). |
| Deshacer | Botón «Deshacer» del aviso o Ctrl+Z. |
| Cambiar la imagen de una lista | Pulsa su portada, o clic derecho en la barra lateral. |
| Ordenar una lista | Pulsa los títulos de columna o el botón **Orden**. |
| Seguir a un artista | Botón **Seguir** en su perfil. |
| Ver / pausar las descargas | Botón **Descargas** (arriba a la derecha). |
| Temporizador, velocidad, repetir tramo | Botón del reloj en la barra de reproducción. |
| Ver la portada, la letra y el artista | Botón de panel de la barra de reproducción (**En reproducción**). |
| Letra sin letra / corregirla | **Generar con el sistema**, **Escribir la letra yo** o **Editar**. |
| Saltar a una frase de la letra | Pulsa la frase (se subraya al pasar el ratón). |
| Copia de seguridad, espacio, calidad, colores | **Ajustes**. |
| Recorrido, atajos, actualizar el motor, informe de problemas | **Ayuda**. |

**Atajos de teclado:** `Espacio` pausa/reanuda · `←` / `→` retroceden/avanzan 5 s · `M` silencia · `Ctrl+F` va al
buscador · `Ctrl+V` pega un enlace · `Ctrl+Z` deshace · `↑` `↓` `Intro` `Supr` `Esc` en las listas · `F11` letra a pantalla
completa «Ahora suena» · `Ctrl+↑` `Ctrl+↓` volumen · teclas multimedia del teclado.

## Sin conexión

La aplicación detecta si hay internet (con un aviso de Qt, sin consultar nada cada pocos segundos) y se adapta:

- Aparece un aviso amable y todo se recupera solo al volver la conexión. Se puede forzar el **modo sin conexión** en Ajustes.
- Las canciones **no descargadas se oscurecen y no se pueden seleccionar**; «siguiente» solo salta a las descargadas.
- **Inicio** muestra tus listas, «Mixes de tu música» (hechos con lo descargado) y lo reciente.
- La **búsqueda** busca solo dentro de tu música descargada. Artistas y álbumes abren tus canciones de ellos.
- Las listas muestran «N de M disponibles sin conexión» y empiezan viendo solo lo descargado.
- Lo que pidas **descargar** sin conexión (o que falle por la red) queda **pendiente** y se descarga solo al volver.
- Las letras, la información de los artistas y las portadas ya vistos se guardan para verlos sin conexión.

## Cómo funciona por dentro

```
 Barra superior ──► Búsqueda ──► iTunes Search (canciones, artistas, álbumes)   [services/catalog_service.py]
                         └─────► yt-dlp (enlaces y búsqueda en YouTube)         [services/youtube_service.py]

 Adelanto  ──► yt-dlp obtiene la URL del audio ──► QMediaPlayer
 Descarga  ──► yt-dlp (compara versiones) + FFmpeg ──► comprobación ──► mutagen (etiquetas, portada, letra) ──► tu música

 Carpeta de música ──► LibraryScanWorker ──► índice SQLite (etiquetas, reproducciones, volumen medido)
                  └──► QFileSystemWatcher (detecta cambios y actualiza la interfaz sin recargarla)

 Recomendaciones ──► perfil de gustos (tus descargas, favoritas y artistas seguidos)
                └──► Deezer (artistas relacionados, populares, géneros, listas de éxitos) + iTunes (novedades)

 Letras ──► tuya ► copia guardada ► la del archivo ► LRCLIB / lyrics.ovh (solo del artista correcto) ► generada con whisper.cpp
 Ecualizador ──► copia temporal con filtros de FFmpeg        Volumen igualado ──► FFmpeg (ebur128) una vez por canción
 Red ──► una sesión web compartida (conexiones reutilizadas) · detección de conexión por eventos de Qt
```

- **Interfaz**: PySide6 (Qt). La ventana principal reparte su lógica en módulos «mixin» (`playback_mixin`, `lists_mixin`,
  `home_mixin`, `search_mixin`, `downloads_mixin`, `offline_mixin`, `usability_mixin`, `playback_options`).
- **Ventanas internas**: los cuadros de diálogo se muestran sobre la propia ventana (`ui/overlay.py`), no como ventanas
  aparte. Solo la letra de la canción es una ventana independiente.
- **Reproducción**: se mantiene una *lista de reproducción de contexto* y un historial, de modo que «siguiente» y
  «anterior» se comportan como en Spotify.
- **Listas sin recargas**: al cambiar algo solo se actualizan las filas afectadas.
- **Tareas pesadas de una en una** (`services/heavy.py`) y con prioridad baja.

## Estructura del proyecto

```
main.py                    punto de entrada (y --selftest)
config.py                  rutas, ajustes y escritura segura de JSON
version.py                 número de versión (también en CHANGELOG.md) y versión de yt-dlp incluida
CHANGELOG.md               qué trae cada versión
Descargar_Musica.spec      configuración de PyInstaller
compilar_exe.bat           atajo para compilar
.github/workflows/         publicación automática de versiones (compila el .exe y lo sube a GitHub)
requirements*.txt          dependencias (ejecución / compilación)
assets/                    iconos SVG, logo y tipografía Poppins
services/                  lógica sin interfaz
    catalog_service.py       búsqueda en iTunes (artistas, álbumes, canciones)
    youtube_service.py       búsqueda, adelanto y descarga con yt-dlp (versiones, comprobación y reintentos)
    ytdlp_loader.py          carga de yt-dlp bajo demanda y su actualización
    update_service.py        avisos de versión nueva y actualización del motor de descargas
    spotify_service.py       lectura de enlaces de Spotify
    metadata_service.py      etiquetas y portadas (mutagen)
    library_service.py       biblioteca local y vigilancia de la carpeta
    library_db.py            índice SQLite: etiquetas, reproducciones y volumen medido
    library_search.py        búsqueda en tu música (sin acentos ni mayúsculas)
    local_mixes.py           mixes y listas automáticas con tu música
    duplicates.py            canciones repetidas
    tag_fixer.py             mejorar etiquetas (iTunes)
    playlist_service.py      favoritos y listas (con deshacer y reordenar)
    artist_service.py        artistas seguidos
    recommendation_service.py  recomendaciones (Deezer + iTunes) e información de artistas
    lyrics_service.py        letras de internet · lyrics_store.py letras propias, generadas y guardadas
    transcribe_service.py    «generar letra» con reconocimiento de voz local (whisper.cpp)
    lyric_align.py           poner el tiempo a una letra pegada
    loudness_service.py      igualar el volumen entre canciones
    smtc_service.py          control multimedia de Windows
    equalizer_service.py     ecualizador con FFmpeg
    network_service.py       ¿hay internet? · http.py sesión web compartida
    pending_downloads.py     descargas pendientes sin conexión
    session_service.py       seguir donde lo dejaste
    backup_service.py        copia de seguridad · storage_service.py espacio · diagnostics_service.py informe y reparación
    recycle.py               papelera de Windows · quality.py calidades · heavy.py tareas pesadas
    envelope.py              envolvente de graves/medios/agudos de cada canción para el visualizador
    app_updater.py           actualizar la propia aplicación desde GitHub (descarga, huella, instalación y reinicio)
    ffmpeg_service.py        localiza o descarga FFmpeg
ui/                        interfaz
    main_window.py           ventana principal
    *_mixin.py, playback_options.py   reproducción, listas, inicio, búsqueda, descargas, sin conexión, comodidad
    *_page.py                páginas (inicio, lista, biblioteca, artista, álbum)
    track_row.py             fila de canción estilo Spotify
    now_playing.py           panel lateral «En reproducción»
    lyric_line.py, lyrics_dialog.py, lyrics_editor.py   letras
    library_tools.py         repetidas y mejora de etiquetas
    settings_dialog.py, help_dialog.py, welcome.py, tour.py   ajustes, ayuda, bienvenida y recorrido
    dragdrop.py              arrastrar y soltar
    overlay.py, dialogs.py   ventanas internas
    perf.py                  ahorro de recursos, equipo modesto, batería y memoria
    motion.py, anim_clock.py   nivel de movimiento y reloj de animación compartido (en reposo no hay temporizadores)
    snapshot.py, animations.py, controls.py, textfx.py, hover.py   transiciones con «fotos», microanimaciones, controles y texto animado
    ambient.py, lyric_follow.py, nowplaying_full.py   fondos ambientales, seguimiento de la letra y pantalla completa
    scrolling.py, toast.py, tooltips.py, focusring.py, osd.py, sliders.py   desplazamiento, avisos, ayudas, foco, avisos del teclado
    winext.py                barra de título, barra de tareas y «siempre encima» de Windows (ctypes, opcional)
    styles.py, covers.py ... estilos, portadas, iconos
dev_tools/                 pruebas automáticas y medición de arranque
```

## Datos que guarda y privacidad

Todo se guarda **solo en tu equipo**: en `%APPDATA%\Descargador de Música` si usas el `.exe`, o en `app_data/` si ejecutas
desde el código (la variable `DESCARGADOR_DATA_DIR` lo cambia; las pruebas la usan):

| Archivo | Contenido |
|---|---|
| `settings.json` | calidad, carpeta de descargas, tema, modo ahorro y demás ajustes |
| `favoritos.json`, `playlists.json`, `artistas_seguidos.json` | tus listas |
| `historial_descargas.json`, `descargas_pendientes.json` | descargas realizadas y pendientes |
| `biblioteca.sqlite` | índice de tu música: etiquetas, reproducciones y volumen medido |
| `sesion.json` | cómo dejaste la aplicación |
| `letras/`, `artistas_info.json`, `recomendaciones.json` | letras (tuyas, generadas y copias), información de artistas y recomendaciones |
| `copias/` | copias de seguridad automáticas |
| `covers/`, `img_cache/`, `eq_cache/` | imágenes y copias temporales |
| `yt_dlp/` | motor de descargas actualizado (si lo actualizas) |
| `ffmpeg/`, `whisper/` | FFmpeg y reconocedor de voz descargados (solo si hacen falta) |
| `app_descargas.log` | registro de avisos y errores |

La aplicación **no usa cuentas, claves ni telemetría**. Lo único que sale de tu equipo son las búsquedas y peticiones a
los servicios públicos que usa (iTunes, Deezer, LRCLIB, lyrics.ovh, YouTube mediante yt-dlp, la página pública de
Spotify si pegas un enlace suyo, y GitHub para avisar de versiones nuevas y descargar FFmpeg o yt-dlp; y, solo si
aceptas generar letras, el reconocedor de voz desde GitHub y Hugging Face, con comprobación de huella SHA-256).
Las estadísticas («lo más escuchado») se calculan y quedan en tu equipo. `app_data/` y los registros están excluidos
del repositorio (`.gitignore`) para que tus listas e historial nunca se suban.

## Rendimiento y consumo

Está pensada para equipos modestos. Medido con el programa compilado (sin pantalla), tras arrancar:

- **CPU**: ≈ 1,3 s en total durante el arranque y 0 % en reposo (antes ≈ 20-40 s de CPU en los primeros segundos).
  Lo que más ayudó: **una sola sesión web compartida** con conexiones reutilizadas (cada petición suelta gastaba ≈ 170 ms
  de CPU solo en cargar certificados).
- **Memoria**: ≈ 120 MB reales; Windows muestra ≈ 8 MB de «conjunto de trabajo» en reposo porque la aplicación devuelve
  lo que no usa tras arrancar y al minimizarla. yt-dlp (≈ 27 MB) solo se carga la primera vez que se busca o descarga.
- **Disco**: ≈ 270 MB (antes 481 MB): ya no se incluye `ffprobe`.

Medidas que aplica: modo ahorro (activado por defecto), índice SQLite, caché de imágenes con tope de memoria, tareas pesadas
de una en una y con prioridad baja, procesos hijos (ffmpeg…) con prioridad baja, animaciones detenidas con la ventana
minimizada, un único reloj de animación que se para solo (0 temporizadores en reposo; medido ≈ 0,8 % de CPU en reposo y
≈ 1,6 % reproduciendo con animaciones «Suaves»), efectos gráficos que se retiran al terminar, listas que solo crean las filas visibles, recomendaciones que no se piden solas con batería baja o datos medidos,
y detección de equipo modesto (4 GB o menos / 2 núcleos o menos: descargas de una en una y visualizador apagado).
`python dev_tools/medir_arranque.py` mide CPU y memoria del arranque.

## Pruebas

Se ejecutan sin abrir ventanas, desde la raíz del proyecto, con una carpeta de datos temporal (nunca tocan tus listas ni
ajustes; algunas usan internet y tu carpeta de música y limpian lo que crean):

```bash
python dev_tools/prueba_base.py          # datos fuera del programa, copia de seguridad, espacio, sesión, ayuda y recorrido
python dev_tools/prueba_sin_conexion.py  # banner, tarjetas oscurecidas, Inicio local, búsqueda local, descargas pendientes
python dev_tools/prueba_consumo.py       # sesión web compartida, límite de memoria, tareas pesadas, equipo modesto
python dev_tools/prueba_comodidad.py     # deshacer, papelera, arrastrar y soltar, teclado, pegar enlaces, alto contraste
python dev_tools/prueba_reproductor.py   # volumen igualado, temporizador, velocidad, tramo, fundido, control multimedia
python dev_tools/prueba_biblioteca.py    # repetidas, etiquetas, listas automáticas, selección múltiple, reordenar
python dev_tools/prueba_descargas.py     # versión correcta, reintentos, carpetas, cola con pausa, espacio, actualización de yt-dlp
python dev_tools/prueba_sincronizar.py   # tiempos de la letra (con una sincronización real si hay reconocedor de voz)
python dev_tools/prueba_letras.py        # letras: artista, propias/generadas, estados de las frases
python dev_tools/prueba_filas.py         # filas estilo Spotify, menú, panel «En reproducción», ecualizador
python dev_tools/prueba_interfaz.py      # ventanas internas, búsqueda, álbumes, orden, vigilancia de la carpeta...
python dev_tools/prueba_listas.py        # listas, artistas, sin recargas
python dev_tools/prueba_detalles.py      # fechas «añadida», rueda lateral, géneros, ventanas sueltas
python dev_tools/prueba_fundido.py       # aleatorio coherente y fundido cruzado con dos reproductores (audio real)
python dev_tools/prueba_animaciones.py   # niveles de movimiento, reposo, efectos, controles, avisos, visualizador, Windows
python dev_tools/prueba_actualizar.py    # actualización desde GitHub: huella, instalación (se ejecuta de verdad) y botón azul
python dev_tools/ejecutar_pruebas.py     # todas las pruebas seguidas (código de salida 1 si alguna falla)
python dev_tools/prueba_calidad.py      # M3U, limpieza de títulos, modo privado, acceso a YouTube, ajustes nuevos
python dev_tools/prueba_robustez.py     # JSON a la vez/estropeados, favoritos, copias, enlaces, biblioteca, descargas, una sola copia
python dev_tools/prueba_palabras.py      # karaoke por palabras: tiempos, reparto, guardado y barrido por píxeles
python dev_tools/prueba_letra_cambio.py  # la letra del panel se ve al cambiar de canción (abre una ventana real un momento)
```

## Solución de problemas

- **No suena el adelanto / no descarga**: comprueba tu conexión. YouTube cambia a menudo: en **Ayuda → Actualizaciones**
  pulsa «Actualizar el motor de descargas» (o deja activada la actualización automática).
- **«Falta un componente de audio»**: FFmpeg no se pudo descargar. Copia `ffmpeg.exe` en `bin/` o en la carpeta `ffmpeg/` de tus datos.
- **Algo no va bien**: en **Ayuda** pulsa «Reparar la aplicación» (vacía cachés, no toca tus datos) o «Copiar informe de
  problemas» (no lleva datos personales).
- **Perdí mis listas**: en **Ajustes → Copia de seguridad** restaura una copia, o mira la carpeta `copias/` de tus datos.
- **No aparecen los iconos o el texto se ve distinto**: ejecuta `Descargar_Musica.exe --selftest` y revisa `selftest.log`.
- **La app va justa de recursos**: activa el *modo ahorro* en Ajustes; en equipos modestos ya viene ajustado.
- **Errores**: se anotan en `app_descargas.log` (en la carpeta de tus datos).

## Publicar una versión

1. Sube el número en `version.py`, añade la sección en `CHANGELOG.md` y actualiza «Versión actual» arriba.
2. `git commit`, `git tag -a vX.Y.Z -m "..."` y `git push origin HEAD --tags`.
3. GitHub Actions (`.github/workflows/release.yml`) compila el `.exe` en Windows, lo comprueba con `--selftest` y
   publica la versión con el `.zip` adjunto y las notas sacadas del `CHANGELOG.md`.

## Créditos y licencias de terceros

- Interfaz: [PySide6 / Qt](https://www.qt.io/qt-for-python) (LGPL).
- Descargas: [yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense) y [FFmpeg](https://ffmpeg.org/) (LGPL/GPL según la compilación).
- Reconocimiento de voz opcional: [whisper.cpp](https://github.com/ggml-org/whisper.cpp) (MIT) y modelos de Whisper (MIT).
- Control multimedia de Windows: [pywinrt](https://github.com/pywinrt/pywinrt) (MIT).
- Etiquetas de audio: [mutagen](https://github.com/quodlibet/mutagen) (GPL).
- Tipografía: [Poppins](https://fonts.google.com/specimen/Poppins) (SIL Open Font License, incluida en `assets/fonts/OFL.txt`).
- Datos: iTunes Search API, Deezer API, [LRCLIB](https://lrclib.net/) y lyrics.ovh.

Este proyecto no está afiliado a Spotify, YouTube, Apple ni Deezer. Los nombres y marcas pertenecen a sus propietarios.
