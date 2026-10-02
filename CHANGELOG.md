# Historial de versiones

Formato: `MAYOR.MENOR.PARCHE`. MAYOR = cambios que rompen datos o uso, MENOR = funciones nuevas, PARCHE = arreglos.
Cada versión subida a GitHub tiene su etiqueta `vX.Y.Z` (pestaña *Releases/Tags*).

## 1.14.1
**Arreglos**
- **La aplicación no encontraba versiones nuevas**: consultaba la API de GitHub, que solo deja 60 peticiones por hora y conexión; cuando se gastaban (o la conexión se compartía) no avisaba de nada y encima decía «todo al día». Ahora la versión se lee de la web de GitHub (la redirección de `releases/latest`), que no tiene ese límite, y las direcciones de descarga se calculan; la API queda solo como último recurso.
- Si no se puede consultar GitHub, ya no dice «todo al día»: dice que no se pudo.
- **Ajustes → Actualizaciones**: botón «Buscar actualizaciones», estado y opción de mantener yt-dlp al día (también sigue en Ayuda).

## 1.14.0
**Auditoría completa del proyecto: robustez, rendimiento y seguridad**

*Datos y fiabilidad*
- **Escrituras de JSON a prueba de fallos**: un solo bloqueo para todo el programa, archivo temporal propio en cada escritura y copia `.bak` del anterior. Si un JSON (listas, favoritos, ajustes) se estropea, ya no se toma por vacío y se pisa: se aparta como `.corrupto-<fecha>` y se recupera de la copia.
- **Favoritos y listas distinguen artistas**: dos canciones con el mismo título (otro artista, directo/estudio) ya no se pisan; antes marcar una marcaba la otra.
- **Renombrar o borrar una canción actualiza tus listas y favoritos** (antes quedaban con «No encontramos ese archivo»). Renombrar limpia el nombre (sin `..\` ni caracteres inválidos) y avisa si ya existe.
- **Copias de seguridad**: restaurar valida cada JSON antes de tocar nada, escribe de forma atómica, limita el tamaño y refresca los ajustes en memoria.
- **Biblioteca**: si el escaneo devuelve muy pocos archivos (OneDrive o disco de red desconectado) ya no se borran del índice; las reproducciones se conservan y `C:\Music2` ya no se confunde con `C:\Music`. La base de datos lleva versión de esquema para migraciones futuras y comprueba su estructura una sola vez por ejecución.
- **Una sola copia abierta**: si abres la aplicación dos veces, la segunda avisa a la primera (que se muestra) y se cierra; al reiniciarse la propia aplicación espera a que la anterior termine.
- **Al cerrar** se cancelan y esperan (2,5 s como mucho) las descargas, la actualización, las letras y demás tareas en marcha; antes solo se esperaba al ecualizador y se cancelaban atributos que ya no existían.

*Descargas*
- Una descarga que fallaba antes de empezar (ruta imposible, sin permisos) dejaba la cola parada; ahora avisa siempre.
- **Cancelar y reintentar por canción** en el panel de descargas, y «Reintentar fallidas».
- Ya no se pueden lanzar dos descargas de la misma canción a la vez.
- Nombres con `%` («100% Pure Love»), nombres reservados de Windows (`CON`, `NUL`…) y nombres larguísimos ya no rompen la descarga.
- FFmpeg: se comprueba su huella SHA-256 con la que publica el autor, se extrae a un archivo aparte y se prueba antes de usarlo (un corte ya no deja un `ffmpeg.exe` a medias); si no se pudo descargar al primer arranque, se reintenta al volver internet.
- Los errores que contenían «age» (message, image, language…) ya no se muestran como «requiere iniciar sesión».

*Rendimiento*
- Favoritos y listas se guardan en memoria y solo se vuelven a leer si el archivo cambia: pasar el ratón por una fila ya no lee y analiza dos JSON.
- La lectura inicial de la biblioteca ya no puede bloquear la ventana (antes, al abrir sin conexión, se hacía en el hilo de la interfaz).
- Las tareas pesadas tienen dos carriles: la voz (letras, tiempo de palabras; minutos) ya no bloquea el escaneo de la biblioteca ni el ecualizador, y se cancela la medición de palabras al cambiar de canción.

*Seguridad y privacidad*
- Los enlaces de YouTube y Spotify se validan por servidor (antes bastaba con que el texto mencionara «youtube.com/», p. ej. una dirección interna), y el parámetro de Spotify se codifica.
- La papelera avisa en vez de borrar para siempre cuando no cabe.
- El registro solo guarda avisos y errores (con `DESCARGADOR_DEBUG=1` guarda todo), y el informe de Ayuda quita además enlaces y títulos.
- La detección de internet prueba también por HTTPS (proxys y cortafuegos que bloquean conexiones directas).

*Actualizaciones y publicación*
- Las consultas a GitHub usan ETag (si no hay novedades no cuentan en el límite) y esperan una hora si GitHub dice «demasiadas peticiones».
- El script de instalación reintenta la copia si falla y solo instala lo que la propia aplicación dejó en su carpeta de preparación.
- La publicación automática comprueba que la etiqueta coincide con `version.py` y ejecuta `pyflakes` de verdad; nuevo `ci.yml` que pasa el análisis y todas las pruebas en cada subida. Nuevo `dev_tools/ejecutar_pruebas.py` (código de salida distinto de 0 si algo falla) y `prueba_robustez.py`.
- El instalador ya no deja elegir carpeta (desinstalar borra la carpeta entera).
- Los deslizadores de volumen y posición tienen nombre para lectores de pantalla.

## 1.13.1
**Arreglos**
- **La actualización automática se quedaba a medias**: la aplicación se cerraba pero no se instalaba la versión nueva ni se volvía a abrir. El script de instalación se quedaba esperando para siempre porque, lanzado sin consola, no podía enlazar dos programas de Windows. Ahora no usa tuberías, espera como mucho 90 segundos y deja un registro en `%APPDATA%\Descargador de Músicactualizacion.log`. Prueba nueva: una «aplicación» de mentira que sigue abierta unos segundos, con el mismo modo de lanzamiento que la real.
- Importante: las versiones 1.12.x y 1.13.0 llevan el script antiguo, así que **esta actualización hay que hacerla una vez a mano** (con el instalador de abajo). Desde la 1.13.1 todo es automático.

**Instalador de Windows**
- Cada versión publica ahora también `Descargador_Musica-Setup-vX.Y.Z.exe`: se instala solo para tu usuario (sin administrador), crea el acceso en el menú Inicio (y en el escritorio si quieres) y **aparece en Configuración de Windows → Aplicaciones**, con su icono, versión y botón de desinstalar. La actualización automática también pone la versión nueva en esa lista. Los datos no se borran al desinstalar.
- La aplicación tiene por fin **icono propio** (nota musical sobre fondo verde) en la ventana, la barra de tareas y el .exe.
- Al abrir la aplicación comprueba las novedades a los 5 segundos (no a los 12).

## 1.13.0
**Letra tipo karaoke que sigue la voz palabra a palabra**
- Antes la frase se rellenaba a velocidad uniforme por letra desde que empezaba hasta un tiempo estimado, y las palabras no coincidían con el cantante. Ahora cada palabra tiene su propio tiempo: se reparte el de la frase según las sílabas de cada palabra, usando el ritmo medio de esa canción (la última palabra de la frase se alarga) y respetando que la frase acaba antes de que empiece la siguiente.
- El relleno se pinta por píxeles según el ancho real de cada letra (antes se repartía por igual entre las letras, así una «i» y una «m» avanzaban lo mismo).
- **Tiempos medidos con la voz** (canciones descargadas, si ya tienes instalado el reconocedor de voz de «Generar letra»): la primera vez que suena una canción con letra sincronizada, el reconocedor la escucha una sola vez en segundo plano (prioridad baja) y mide cuándo canta cada palabra; se guarda en tu equipo y desde ahí el karaoke sigue la voz de verdad, también sin conexión. Si editas la letra se vuelve a medir.

**Actualizaciones**
- El **descargador de canciones (yt-dlp)** también avisa ahora con el botón azul de arriba a la izquierda: «Actualizar el descargador de canciones», con porcentaje al descargar y «Reiniciar para usar el descargador nuevo» si el anterior ya estaba en uso. Si tienes la actualización automática del motor activada, se descarga solo y el botón te dice cuándo reiniciar. Si hay a la vez una versión nueva de la aplicación, manda esta.
- La aplicación abierta mira si hay novedades **cada 10 minutos** (antes cada 3 horas) y no más de una vez cada 5, sin reiniciar nada.
- Al abrir la aplicación ya actualizada aparece un aviso: «se ha actualizado a la versión X» con «Ver novedades».
- Pruebas nuevas: `prueba_palabras.py` y más comprobaciones en `prueba_actualizar.py`.

## 1.12.1
**Arreglos**
- **La letra del panel lateral desaparecía al cambiar de canción**: cuando la letra llegaba de internet (tardaba un poco) las frases se colocaban con altura 0 y no se veía nada, sobre todo al pasar rápido de una canción a otra. Ahora se comprueba y se recolocan. Lo mismo en la ventana de letras. Prueba nueva: `prueba_letra_cambio.py` (reproduce el fallo con ventana real).

## 1.12.0
**La aplicación se actualiza sola desde GitHub**
- Si en GitHub hay una versión más nueva que la que tienes (por ejemplo, la 1.15 y tú tienes la 1.11), aparece un **botón azul arriba a la izquierda**. Se descarga sola en segundo plano (con batería baja o datos medidos espera a que lo pulses), se comprueba su huella SHA-256 y el botón pasa a **«Reiniciar y actualizar a la X»**: la aplicación se cierra, se instalan los archivos nuevos y se vuelve a abrir. Tus datos no se tocan.
- Se mira cada hora como mucho (y cada 3 horas si la dejas abierta). Solo descarga desde el repositorio oficial por HTTPS y solo instala si la versión publicada trae su huella (`.sha256`), que la publicación automática ya añade.
- Importante: las versiones anteriores a la 1.12 no saben actualizarse solas; en cada ordenador hay que instalar la 1.12 una vez a mano. Desde ahí, todo es automático.

**Arreglos**
- Ajustes: los interruptores solo respondían al pulsar en su texto; ahora responden en toda su superficie, perilla incluida.
- Fundido entre canciones: el volumen que se ajusta al medir la canción nueva se aplicaba de golpe y sonaba como un corte justo al terminar el fundido; ahora cambia poco a poco.
- El panel «En reproducción» se abre siempre la primera vez que suena algo y se queda abierto si ya lo estaba.

## 1.11.0
**Arreglos**
- **Aleatorio**: «A continuación» (panel y cola) enseñaba la siguiente de la lista y sonaba otra al azar. Ahora el orden aleatorio se decide de antemano y lo que se muestra es exactamente lo que suena (sin repetir hasta recorrer toda la lista).
- **Fundido entre canciones**: ahora es un fundido cruzado de verdad con dos reproductores. Al acercarse el final empieza ya la siguiente canción mientras la actual baja el volumen y la nueva sube (potencia constante). También al pulsar «siguiente» (fundido corto), y hay duraciones de hasta 12 s. Si no hay siguiente en tu equipo, solo baja el volumen como antes.

**Animaciones y mejoras de uso (100 ideas)**
- **Nivel de movimiento** en Ajustes → Rendimiento: Ninguna, Suaves (por defecto: solo anima lo que haces) y Completas (añade detalles continuos). Respeta «Efectos de animación» de Windows, baja solo con batería baja o si el equipo va justo, y hay un medidor de consumo y un botón «Probar animaciones» que elige el nivel adecuado.
- **Reposo sin gasto**: un único reloj de animación compartido que se para solo, se pausa con la ventana minimizada y baja de velocidad si el equipo va justo; los efectos gráficos de Qt ya no se quedan puestos (antes la barra inferior y cada página visitada llevaban uno permanente).
- **Transiciones**: cruce entre páginas con una «foto» de la anterior (avanzar/volver con dirección y recordando el scroll), la portada viaja a la cabecera de la página, ventanas internas con atenuado y entrada suaves, cambio de tema con cruce de colores, barra de reproducción que sube, panel «En reproducción» con fundido y fondo que cambia de color (y respira en «Completas»), mini reproductor sin parpadeo, miniaturas que vuelan al soltar una canción en una lista, añadirla a la cola o descargarla.
- **Reproductor**: botón de reproducir/pausa que se transforma, tirador de la barra que aparece al acercar el ratón, burbuja con el tiempo al que saltarías, tramo A–B visible, aviso flotante de volumen y saltos de ±5 s (Ctrl+↑/↓ cambia el volumen), icono de volumen por niveles, cuenta atrás del temporizador, portada con fundido, título que se desplaza si no cabe, visualizador que sigue la música de verdad (envolvente de graves/medios/agudos calculada una vez por canción), anillo de progreso en el mini reproductor.
- **Letras**: la frase que suena se rellena de izquierda a derecha y crece un poco, las siguientes se apagan según lo lejos que están, el desplazamiento empieza un poco antes, puntos en las pausas instrumentales, fondo con la portada desenfocada, aurora lenta opcional y, en pantalla completa, los controles y el cursor se ocultan solos.
- **Pantalla completa «Ahora suena»** (F11 o botón del panel): portada grande, controles, barra de tiempo y letra.
- **Listas y tarjetas**: resalte con transición, indicador de «sonando» de tres barras, botón de descarga que se vuelve anillo y luego ✓, esqueletos de carga, portadas con fundido y de relleno, mosaicos de portadas, zoom y luz al pasar el ratón, pestañas con indicador deslizante, rueda con inercia, barras de desplazamiento finas, botón «volver arriba», barra pegajosa con el nombre de la lista y ▶, filas que se funden al quitarlas, arrastre con contador, coincidencias de la búsqueda resaltadas.
- **Descargas y avisos**: progreso suavizado con el color del tema, pasos visibles (Buscando › Descargando › Preparando › Lista), anillo de progreso en el botón Descargas y en el icono de la barra de tareas (con marca al terminar), avisos con icono, barra de tiempo, pausa con el ratón y apilados, errores con sacudida del campo, «Volvió la conexión» y tarjetas que se apagan/encienden en cascada, confeti en hitos (copia de seguridad, listas grandes, 100 canciones).
- **Primeras impresiones**: pantalla de arranque instantánea y ventana que aparece con fundido, foco del recorrido que se desliza, asistente con pasos deslizantes, «Seguir escuchando» en Inicio, interruptores en Ajustes, ayudas propias con el atajo de teclado, anillo de foco para quien usa el teclado, «¿Se ve bien?» con cuenta atrás al cambiar el alto contraste, «Colores que cambian con la canción» (opcional).
- **Windows**: barra de título del color del tema, botones anterior/reproducir/siguiente en la miniatura de la barra de tareas y progreso de descargas en su icono.
- Pruebas nuevas: `prueba_fundido.py` (aleatorio y fundido cruzado con audio real) y `prueba_animaciones.py` (niveles, reposo, efectos, controles, visualizador, avisos).

## 1.10.0
**Descargas**
- Elige la versión correcta: compara las duraciones de varios resultados de YouTube y comprueba el archivo descargado; si no es lo esperado (otra versión, archivo dañado o no disponible) prueba solo con otra (hasta 3 intentos) y, si ninguna coincide, se queda con la más parecida y lo avisa.
- Cola de descargas con pausa, reanudar y cancelar; las descargas nuevas se suman a la cola en vez de reiniciarla.
- Aviso antes de descargar mucho o con poco espacio en el disco (con el tamaño estimado).
- Organización opcional de las canciones: todas juntas (por defecto), por artista, o por artista y álbum.

**Letras**
- Poner el tiempo a una letra pegada: el sistema escucha la canción y encaja tu texto (error mediano de 0,4 s en las pruebas), o márcalos tú con la barra espaciadora mientras suena.

**Actualizaciones**
- El motor de descargas (yt-dlp) se actualiza por separado desde Ayuda (huella SHA-256 comprobada; automático una vez al día si quieres) y la app avisa si hay una versión nueva.
- yt-dlp se carga solo cuando hace falta (≈ 27 MB menos de memoria y 0,3 s de CPU al abrir).

**Proyecto**
- Publicación automática de versiones con GitHub Actions (compila el `.exe`, lo comprueba y lo sube a Releases).
- El programa compilado pesa ≈ 270 MB (antes 481 MB). Medido con el `.exe`: ≈ 1,3 s de CPU en total al arrancar y 0 % en reposo.
- Arreglo en las pruebas: ya no mueven los datos de la carpeta del proyecto a su carpeta temporal.
- Limpieza de carpetas antiguas del proyecto (copias de seguridad y restos de desarrollo archivados en un .zip fuera del repositorio).

## 1.9.0
**Más cómoda**
- Deshacer: al quitar una canción de una lista, quitar de favoritas, dejar de seguir a un artista o eliminar una lista, aparece «Deshacer» (también Ctrl+Z durante 90 s). Ya no hay que confirmar.
- Borrar una canción la manda a la papelera de Windows (recuperable).
- Arrastrar y soltar: canciones sobre una lista de la barra lateral, enlaces de YouTube/Spotify sobre la ventana y archivos de audio para añadirlos a tu música. Ctrl+V pega un enlace en cualquier sitio.
- Teclado en las listas: ↑ ↓ mueven, Intro reproduce, Supr quita de la playlist, Esc quita la selección.
- Accesibilidad: tamaño de la aplicación (100/115/130 %), alto contraste y nombres para lectores de pantalla.
- La biblioteca invita a crear tu primera lista.

**Reproductor**
- Botón del reloj en la barra: temporizador para dormir (con bajada gradual del volumen y «al terminar la canción»), velocidad, repetir un tramo A-B y fundido entre canciones.
- Igualar el volumen entre canciones (se mide una vez con FFmpeg y se guarda).
- Control multimedia de Windows (título y portada en el panel del sistema; botones de auriculares y teclados) y controles en la bandeja (opción de seguir sonando al cerrar).
- Nuevos ajustes del ecualizador: Auriculares y Noche.

**Biblioteca**
- Selección múltiple (Ctrl/Mayús + clic) con barra de acciones: añadir a una lista, reproducir a continuación, descargar, quitar, papelera. Se pueden arrastrar varias a la vez.
- Arrastrar canciones dentro de una playlist para reordenarlas.
- Listas automáticas: añadidas esta semana, canciones largas, lo más escuchado, aún sin escuchar, sin artista/álbum.
- «Lo más escuchado» y «Redescubre» en Inicio (estadísticas locales; no se envía nada).
- «Buscar canciones repetidas» y «Mejorar los datos (artista, álbum y portada)» en Mis descargas.

## 1.8.0
**Datos seguros y copia de seguridad**
- Tus datos ahora viven en `%APPDATA%\Descargador de Música` (antes, junto al `.exe`): actualizar o mover el programa nunca los borra. La primera vez se traen solos desde la carpeta antigua.
- Copia de seguridad en un clic (Ajustes) y restauración; además, copia automática semanal (las 5 últimas).
- Informe de problemas sin datos personales y botón «Reparar la aplicación» (Ayuda).
- «Liberar espacio»: Ajustes muestra cuánto ocupa cada cosa y deja vaciar lo que se reconstruye solo.

**Seguir donde lo dejaste**
- Se recuerdan el volumen, la canción (y el punto en que iba), la cola, la lista abierta, aleatorio/repetir, el panel y el tamaño de la ventana.

**Sin conexión**
- La aplicación detecta si hay internet (sin gastar recursos) y avisa con un banner; se recupera sola al volver.
- Sin conexión, las canciones no descargadas se oscurecen y no se pueden seleccionar; «siguiente» solo salta a las descargadas.
- Inicio sin conexión: aviso amable, tus listas, «Mixes de tu música» y recientes. La búsqueda pasa a buscar solo en tu música.
- Las listas muestran «N de M disponibles sin conexión» y empiezan viendo solo lo descargado.
- Artistas y álbumes sin conexión abren tus canciones de ese artista o álbum.
- Las descargas pedidas sin conexión (o que fallan por la red) quedan pendientes y se reanudan solas al volver internet.
- Las letras y la información de los artistas ya vistos se guardan para verlos sin conexión; la letra viaja dentro del archivo de cada canción descargada.
- Modo sin conexión manual en Ajustes.

**Mucho menos consumo**
- Una sesión web compartida con conexiones reutilizadas: el arranque pasa de ≈ 20-40 s de CPU a ≈ 1,7 s (12-24 veces menos).
- Índice de la biblioteca en SQLite (más rápido y ligero con miles de canciones); lee género y año.
- Tareas pesadas de una en una, procesos hijos (ffmpeg…) con prioridad baja, caché de imágenes con tope de memoria y limpieza de memoria al minimizar o tras el arranque.
- Minimizada, la aplicación deja de animar. Con batería baja o datos medidos no pide recomendaciones nuevas solas.
- En equipos modestos (≤ 4 GB o ≤ 2 núcleos) las descargas van de una en una y el visualizador empieza apagado (opción en Ajustes).
- El programa compilado ya no incluye ffprobe (≈ 145 MB menos).

**Más sencilla**
- Asistente de bienvenida de 3 pasos y recorrido guiado por la aplicación; botón «Ayuda» con atajos de teclado.
- La calidad de música se explica con lo que ocupa una canción; nueva opción «Ahorrar espacio» (128 kbps).
- Pantallas vacías con un botón para empezar.

## 1.7.0
- «Generar con el sistema»: ahora se ve que trabaja (barra con porcentaje y segundos transcurridos) y los avisos salen dentro de la ventana de letras (antes quedaban escondidos detrás de ella).
- Las letras generadas se dividen en frases más cortas (máx. ~40 letras por línea) repartiendo el tiempo.
- Editor de letras más sencillo: un campo de tiempo, otro de frase y «Añadir»; lista editable con doble clic, «Tiempo actual», «Pegar una letra».
- Ventana de letras: botón de pantalla completa arriba a la derecha (F11; Esc para salir) y botón de maximizar del sistema; la letra crece con la ventana.

## 1.6.0
- Letra: las frases ya leídas se oscurecen, la que está bajo el ratón se subraya y al pulsarla la canción salta a ese momento (panel lateral y ventana de letras).
- Canciones sin letra: botón «Generar con el sistema» (solo descargadas; reconocimiento de voz local con whisper.cpp, se descarga la primera vez con permiso) y «Escribir la letra yo». Las generadas se marcan como tales.
- Editor de letras dentro de la app (con «Poner el tiempo actual»), letra propia con prioridad y opción de volver a la original.
- La barra lateral izquierda (Inicio, Abrir carpeta, Ajustes y tus listas) se ilumina bien al pasar el ratón.

## 1.5.0
- Las tarjetas (mixes, canciones, artistas, géneros, accesos rápidos, listas de la barra lateral) se iluminan y se marcan al pasar el ratón, igual que las filas de las listas. Antes su fondo no se llegaba a pintar.
- Arreglo de letras: ya no se muestra la letra de otro artista con el mismo título de la canción (ej. «Cosas pendientes» de Dib salía con la de Maluma). Si no hay letra del artista correcto, se avisa de que no se encontró.

## 1.4.0
- Ventana de letras al estilo Spotify: fondo con el color de la portada, texto grande que crece con la ventana, siempre una sola ventana y se actualiza sola al cambiar de canción.
- Arreglo: al elegir otra canción con el panel «En reproducción» abierto, la canción se quedaba en pausa aunque el botón dijera «Reproduciendo» (y la letra no seguía).
- Versión visible en Ajustes y en el título de la ventana; archivo `version.py` y este historial.

## 1.3.0
- Letra del panel lateral con el color de la portada, texto grande y desplazamiento automático (la rueda no la mueve).

## 1.2.0
- Botón «+» para guardar en listas (✓ verde si ya está guardada) con la listita de «Guardar en…».
- Un clic sobre el play de la fila reproduce; columna de «descargada».
- El panel «En reproducción» se abre solo al reproducir; barra inferior reorganizada.

## 1.1.0
- Filas de lista estilo Spotify (número ▸ play, selección, menú de tres puntos, ir al artista / álbum).
- Panel lateral derecho «En reproducción».
- Ecualizador siempre activo y en 0 por defecto.

## 1.0.0
- Versión inicial publicada: reproductor, descargas (yt-dlp + ffmpeg), listas, favoritos, artistas, recomendaciones, temas, modo ahorro.
