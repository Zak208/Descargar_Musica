# Historial de versiones

Formato: `MAYOR.MENOR.PARCHE`. MAYOR = cambios que rompen datos o uso, MENOR = funciones nuevas, PARCHE = arreglos.
Cada versión subida a GitHub tiene su etiqueta `vX.Y.Z` (pestaña *Releases/Tags*).

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
