# Historial de versiones

Formato: `MAYOR.MENOR.PARCHE`. MAYOR = cambios que rompen datos o uso, MENOR = funciones nuevas, PARCHE = arreglos.
Cada versión subida a GitHub tiene su etiqueta `vX.Y.Z` (pestaña *Releases/Tags*).

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
