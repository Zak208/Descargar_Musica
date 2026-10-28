# Plan del modo DJ

Objetivo: que el Descargador de Música mezcle solo las canciones de una carpeta como lo haría un DJ (orden con criterio,
ritmo igualado, cambio de graves, mezclas por frases, efectos) y que mejore con el uso.

Las horas son estimaciones sin medir: sirven para planificar, no son una promesa. Cada fase termina en algo que se puede
probar y tiene una **puerta**: si no se cumple, se arregla antes de seguir (o se para).

## Lo que ya tiene la aplicación y se aprovecha

| Pieza que ya existe | Dónde | Para qué sirve en el DJ |
|---|---|---|
| Dos reproductores con fundido cruzado | `ui/playback_options.py` | Base de la mezcla hasta tener motor propio |
| Tempo (BPM) a partir de la envolvente | `services/tempo.py` | Primer análisis de ritmo, sin dependencias nuevas |
| Volumen medido (LUFS) | `services/loudness_service.py` | Igualar volumen entre canciones |
| Ecualizador con ffmpeg | `services/equalizer_service.py` | Idea de partida para procesar audio fuera de tiempo real |
| Envolvente de graves, medios y agudos | `services/envelope.py` | Energía de cada tramo, intros y finales |
| Tareas pesadas de una en una | `services/heavy.py` | Analizar canciones sin bloquear el equipo |
| Índice SQLite de la biblioteca | `services/library_db.py` | Guardar el análisis de cada canción una sola vez |

## Límite técnico importante

`QMediaPlayer` (lo que suena ahora) no deja tocar el audio muestra a muestra: no hay ecualizador por bandas en directo,
ni sincronía exacta de golpes, ni efectos. Hasta la **fase 9** el DJ se apoya en el fundido actual; a partir de ahí hace
falta un **motor de audio propio** (numpy + sounddevice) o mezclar por adelantado con ffmpeg. Es la decisión técnica más
grande del proyecto.

---

## Bloque A · Base (sin cambiar el motor de audio)

### Fase 1 · Menú DJ y carpeta ✅ hecho
- Botón **DJ** arriba a la izquierda.
- Elegir la carpeta general; elegir qué suena: toda la carpeta con subcarpetas, solo la carpeta general o una subcarpeta.
- Lectura de la carpeta en segundo plano, con límite de 20.000 archivos.
- Acepta mp3, mp4, m4a, wav, flac, ogg y wma.
- **Puerta**: prueba `pruebas/prueba_dj.py` en verde.

### Fase 2 · Sesión DJ básica ✅ hecho (versión mínima)
- «Empezar a pinchar»: orden aleatorio y fundido que iguala el ritmo (si estaba apagado se pone a 8 s).
- **Puerta**: una hora seguida sonando sin cortes ni errores con tu carpeta real. *(Pendiente de probar por ti.)*

### Fase 3 · Página DJ ✅ hecho (pendiente de que la pruebes)
- Una página propia: canción que suena, la siguiente, cuánto falta para la mezcla, lista de la sesión.
- Botones: saltar, «esta no», bloquear canción para que no vuelva a salir, volver a barajar, desbloquear todas.
- Si pones otra lista o un álbum, la sesión DJ se da por terminada y la página vuelve a «Empezar a pinchar».
- **Puerta**: se puede llevar una sesión entera solo desde esa página. Prueba `pruebas/prueba_dj_pagina.py` en verde.

### Fase 4 · Análisis de cada canción ✅ hecho (pendiente de que lo pruebes)
- Se guarda en el índice (tabla `analysis`): BPM, confianza del BPM, energía, duración de la intro y del final.
- Sale de la envolvente que ya se guardaba para el visualizador (`services/track_analysis.py`): si la canción ya sonó,
  no se vuelve a escuchar el audio. Se analiza una vez en segundo plano y solo se repite si cambia el archivo.
- La página DJ enseña «Analizando canciones: 34 de 100…» y el BPM, la intro y el final de cada canción.
- El fundido aprovecha el BPM ya calculado.
- Limitación conocida: la **energía** se calcula sobre una envolvente normalizada por canción, así que no sirve para
  comparar canciones entre sí. Antes de la fase 7 (orden inteligente) hay que medirla en absoluto (por ejemplo con el
  volumen LUFS que ya se calcula).
- **Puerta**: el BPM es correcto en al menos 90 de 100 canciones (compruébalo con la página DJ con unas cuantas).
  Prueba `pruebas/prueba_analisis.py` en verde.

### Fase 5 · Corregir BPM a mano ✅ hecho (pendiente de que lo pruebes)
- Regla automática por género (`tempo.GENRE_WINDOWS`): reguetón y urbano llevan el tempo a la ventana 80 a 160, trap y
  drill a 100 a 200 (doblándolo o partiéndolo por la mitad). Los demás géneros no se tocan. Es una convención de pinchar,
  no una medida: si no te cuadra, se corrige a mano.
- Botones en la página DJ para la canción que suena: **BPM ÷2**, **BPM ×2**, **Escribir BPM…** y **Automático**. Con el
  botón derecho sobre cualquier canción de «Lo que queda» salen las mismas opciones.
- Lo corregido se guarda (ajustes) y gana sobre el análisis; se ve «128 BPM (a mano)» y el fundido usa ese tempo.
  Se aceptan tempos de 40 a 300.
- **Puerta**: ninguna canción de tu carpeta con BPM claramente mal. Prueba `pruebas/prueba_dj_pagina.py` y
  `pruebas/prueba_analisis.py` en verde.

### Fase 6 · Tonalidad ✅ hecho (pendiente de que la compruebes)
- El tono sale en notación Camelot (`8A` = la menor, `8B` = do mayor...) junto al BPM en la página DJ: «128 BPM · 8A · intro
  0:12 · final 0:20». Con «?» si no está claro (confianza menor de 0,55).
- Cómo se calcula (`services/key_detect.py`, una vez por canción, en segundo plano): FFmpeg decodifica el audio, numpy saca
  las notas que suenan (transformada de Fourier, afinación corregida) y se comparan con los 24 perfiles de tonalidad de
  Krumhansl y Kessler. Unos 0,3 s por canción.
- Si el archivo trae el tono en sus etiquetas (ID3 `TKEY`, `initialkey` de FLAC o MP4: Mixed In Key y las tiendas lo
  escriben), se usa ese sin calcular nada.
- `services/camelot.py`: la rueda, nombres musicales, lectura de tonos escritos de otras formas («F#m», «Bb», «C major») y
  `score(a, b)` (1,0 igual; 0,8 relativo o un paso por la rueda; 0,5 diagonal o dos pasos; 0,0 chocan) para el orden
  inteligente de la fase 7.
- **Nueva dependencia: numpy** (BSD). Medido compilando el `.exe`: añade 27 MB sin comprimir (6 MB de numpy y 20 MB de la
  librería de cálculo que lleva dentro), y el `.exe` compilado calcula el tono bien (autocomprobación). Sin numpy el
  programa funciona igual, sin tono. Ojo: una compilación local mete también el `ffmpeg.exe` de tu carpeta `bin`
  (138 MB; es cosa del `spec`, no de numpy); la compilación automática de GitHub no lo incluye.
- Lo que está comprobado: los 24 tonos con audio sintético (también desafinado 35 centésimas y con ruido), y en tus 22
  canciones, subir o bajar de tono con FFmpeg mueve el tono detectado lo que debe en el 91 % de los casos.
- **Lo que NO está comprobado: el acierto real.** No hay tonos de referencia en tus archivos. Puerta: compara en la
  página DJ unas 20 o 30 canciones con una web de tonos (Tunebat, Mixed In Key...) y cuenta cuántas coinciden (basta con
  70 de 100; ojo, mayor frente a su relativo menor, por ejemplo `8B` y `8A`, mezclan igual de bien).
- Limitaciones: música sin armonía clara (solo ritmo o bajo) da un tono poco fiable; el modo (mayor o menor) cambia a
  veces según el tramo analizado. (La energía en absoluto, que estaba pendiente, se hizo en la fase 7.)
- Posible mejora si el acierto no llega: corregir el tono a mano (como el BPM) y probar otros perfiles de tonalidad.

### Fase 7 · Orden inteligente ✅ hecho (pendiente de que lo pruebes)
- **«Empezar a pinchar» ya no baraja al azar:** el orden lo decide `services/dj_planner.py`. En el menú DJ, «Orden de las
  canciones» deja elegir entre **Inteligente** (por defecto) y **Aleatorio**; la página dice cuál está activo. Con el
  inteligente se apaga el aleatorio del reproductor (lo desharía) y «Barajar» pasa a reordenar lo que queda con el mismo criterio.
- **Cómo elige** (un DJ lo hace así): primero decide **qué nivel de energía toca** (curva de fiesta: calentar, subir, pico,
  respiro y volver a subir, una vuelta cada 80 canciones) y solo mira las de ese nivel (±0,2); entre ellas elige por **ritmo**
  (BPM parecido, la mitad o el doble cuentan igual), **tono** compatible en la rueda Camelot (menos peso si el tono es dudoso),
  **género** y que no sea el mismo **artista** que la anterior (si en ese nivel solo quedan de ese artista, se repite). Un poco
  de azar hace que cada sesión salga distinta.
- **La energía se compara por posición** (percentil entre las canciones de la sesión) y las posiciones se recalculan en cada
  paso con lo que queda; sin eso, los picos agotaban las canciones fuertes y la sesión terminaba con las sobras.
- **Energía en absoluto** (`services/audio_features.py`, la pendiente de la fase 6): mezcla de volumen (45 %), brillo del espectro
  (25 %) y actividad del espectro (30 %), medidas con el mismo audio que ya se decodifica para el tono (0,06 s por canción). Se
  guarda en el índice junto al género y al artista de las etiquetas, y se ve en la página DJ como «energía 7» (de 1 a 10).
- Si al empezar hay canciones sin analizar, la sesión arranca ya y se **reordena una vez al terminar el análisis**.
- Va muy rápido: 20.000 canciones se ordenan en 0,1 s (solo se ordenan las 400 primeras, el resto detrás).
- **Medido con datos sintéticos** (100 canciones al azar): el encaje de ritmo pasa de 0,28 al azar a 0,78 y el de tono de 0,23 a
  0,52, y la energía sigue la curva con correlación 0,88. **Con tus 22 canciones**: ritmo 0,25 → 0,42, tono 0,25 → 0,37, curva
  0,87; mejora menos porque con 22 canciones y una ventana de energía quedan pocas opciones por paso.
- **Lo que NO está comprobado:** que el resultado suene mejor a un oído humano. La puerta es subjetiva: a ciegas, prefieres el
  orden inteligente al aleatorio en 7 de 10 sesiones cortas. Los pesos de la energía (volumen, brillo, actividad) y los de la
  puntuación son una elección razonable, no un dato medido.
- Limitaciones: el género y el tono dudosos pesan poco a propósito; el voraz no encuentra el mejor orden posible, solo uno bueno;
  una sesión con muy pocas canciones apenas deja margen; la energía mezcla tres medidas y puede no coincidir con tu idea de
  «energía» en algún género (si pasa, ajustar `audio_features.WEIGHTS`).

### Fase 8 · Punto de mezcla (12 a 20 h)
- Detectar dónde acaba la intro y dónde empieza el final de cada canción.
- La mezcla empieza al principio del final de la que suena y la nueva entra por su intro (no por el segundo 0 si tiene silencio).
- **Puerta**: escuchas 10 transiciones y al menos 6 suenan aceptables. **Si no se cumple, se para aquí y se revisa el análisis**: la IA no lo arreglará.

---

## Bloque B · Motor de audio propio (mezcla de verdad)

### Fase 9 · Decidir el motor (4 a 8 h de pruebas)
- Opción 1: motor en tiempo real con numpy y sounddevice (dos platos, mezcla muestra a muestra).
- Opción 2: preparar cada transición por adelantado con ffmpeg (más simple, menos flexible).
- Prueba pequeña con las dos y elegir.
- **Puerta**: el motor elegido suena sin cortes ni chasquidos durante 30 minutos en tu equipo.

### Fase 10 · Motor de dos platos (30 a 50 h)
- Reproducir dos canciones a la vez con volumen, posición y pausa propios.
- Que el resto de la aplicación (barra de reproducción, letra, control de Windows) siga funcionando.
- **Puerta**: todas las pruebas de reproducción en verde con el motor nuevo.

### Fase 11 · Rejilla de golpes (beatgrid) (12 a 20 h)
- Saber dónde cae cada golpe y cada compás, no solo el BPM.
- **Puerta**: el primer golpe de cada compás está bien en 85 de 100 canciones.

### Fase 12 · Sincronía de golpes (12 a 20 h)
- Cambiar el tempo sin cambiar el tono (rubberband) para que los golpes de las dos canciones caigan juntos.
- Límite de ±8 %: más allá suena artificial; entonces corte limpio en vez de mezcla larga.
- **Puerta**: en 10 transiciones no se oye «galope» (golpes desfasados).

### Fase 13 · Mezcla por frases (10 a 16 h)
- Las mezclas empiezan y acaban en frases de 16 o 32 compases.
- **Puerta**: las entradas suenan «en su sitio» en 8 de 10 transiciones.

### Fase 14 · Cambio de graves y ecualizador de 3 bandas (10 a 16 h)
- Durante la mezcla se quitan los graves de la que entra y, en un golpe, se pasan de una a otra (swap de graves).
- **Puerta**: nunca suenan dos bombos y dos bajos a la vez.

### Fase 15 · Volumen igualado (4 a 6 h)
- Usar el LUFS que ya se mide para que ninguna canción suene más alta o más baja.
- **Puerta**: sin saltos de volumen en una sesión de una hora.

### Fase 16 · Tipos de transición (12 a 20 h)
- Mezcla larga, corte en el compás, eco de salida, filtro paso alto/bajo.
- Regla de seguridad: si hay dudas (BPM poco fiable, tonos que chocan), transición corta y limpia.
- **Puerta**: en una hora ninguna transición suena a desastre.

### Fase 17 · Grabar el mix (6 a 10 h)
- Guardar la sesión en un mp3, con la lista de canciones y tiempos.
- Sirve para escucharlo después y para votar transiciones.

---

## Bloque C · Nivel festival (estructura de las canciones)

### Fase 18 · Drops y build-ups (20 a 40 h)
- Detectar subidas y caídas de energía.
- El drop de la que entra coincide con el final de la subida de la que sale; nunca dos drops a la vez.
- Más difícil en reguetón y drill (drops menos marcados).

### Fase 19 · Voces (20 a 30 h)
- Separar voz, batería, bajo y resto con Demucs (pesado: mejor con tarjeta gráfica).
- Evitar que dos voces suenen a la vez.
- Los stems de 100 canciones ocupan varios GB: guardarlos en una caché que se pueda borrar.

### Fase 20 · Efectos (20 a 30 h)
- Reverb, eco, filtros con barrido, risers, cortes (stutter).
- Elegidos por reglas al principio y por la IA más adelante.

### Fase 21 · Loops (10 a 20 h)
- Repetir 4 u 8 compases para alargar una parte buena o esperar a que la siguiente esté en su punto.

### Fase 22 · Mashups (30 a 50 h)
- La voz de una canción sobre la música de otra, con tonalidad y tempo compatibles.
- Solo suena bien en una parte de las parejas (calculo 30 a 40 %): la IA decide cuándo intentarlo.

### Fase 23 · Tres y cuatro platos (20 a 40 h)
- Más de dos canciones a la vez (por ejemplo, voz de una, batería de otra y melodía de una tercera).

---

## Bloque D · Inteligencia artificial

### Fase 24 · Votos (8 a 12 h)
- Botones 👍 / 👎 en cada transición (en directo o al escuchar un mix grabado).
- Se guarda qué dos canciones, en qué punto, con qué tipo de transición y qué parámetros.

### Fase 25 · Puntuador automático (20 a 40 h)
- Nota sin humanos: desfase de golpes, voces solapadas, graves que chocan, tonos que desentonan, saltos de volumen.
- Descarta lo malo a velocidad de máquina.
- **Puerta**: descarta las mismas transiciones que descartarías tú en 8 de 10 casos.

### Fase 26 · Modelo que aprende tu gusto (30 a 50 h)
- Representaciones de audio ya entrenadas (MERT, CLAP o parecidas) + un modelo pequeño entrenado con tus votos.
- **Puerta**: acierta tus votos en más del 75 % de transiciones que no ha visto.

### Fase 27 · Aprendizaje activo (10 a 20 h)
- La IA prepara muchas transiciones y solo te enseña las que más duda: cada voto vale mucho más.

### Fase 28 · Autojuego con la tarjeta gráfica (50 a 100 h)
- Genera miles de mezclas con tus canciones, las puntúa con las fases 25 y 26 y ajusta sus parámetros.
- **Puerta**: a ciegas, prefieres los mixes nuevos a los de la fase 16.

### Fase 29 · Aprender de mixes de DJs (60 a 120 h + 20 a 50 h de tarjeta gráfica)
- Piloto primero: 10 a 20 mixes de reguetón o urbano con lista de canciones en la descripción.
- Identificar cada canción, encontrar cada transición y deducir qué hizo el DJ (duración, tempo, ecualizador).
- **Puerta**: salen al menos 150 a 300 transiciones limpias del piloto. Si el 80 % sale con ruido, se para.

---

## Bloque E · Fiesta en directo

### Fase 30 · Modo fiesta (20 a 40 h)
- Pantalla con botones grandes: siguiente, más energía, menos energía, pausa.
- Nunca se cae: si algo falla, sigue sonando con un fundido simple.
- **Puerta**: 3 horas seguidas sin fallos en tu equipo.

### Fase 31 · Votos del público (10 a 20 h)
- Botón 👍 en el móvil de los invitados o contar saltos de canción.

### Fase 32 · Leer la sala (opcional, 40 a 80 h, sin garantía)
- Micrófono (volumen, palmas, gritos) o cámara (movimiento). Es investigación: puede no funcionar bien.

### Fase 33 · Luces (opcional, 30 a 60 h)
- Enviar el ritmo y los drops a luces por DMX o MIDI.

---

## Cuántos votos harán falta

| Votos acumulados | Qué se consigue | Tiempo de escucha |
|---|---|---|
| 100 | Solo detecta lo claramente malo | 1 h |
| 300 a 500 | Modelo usable de tu gusto con tus canciones | 3 a 5 h |
| 1.000 a 1.500 | Bueno: elige parejas y duración de mezcla con criterio | 10 a 15 h |
| 3.000 o más | Mejora muy poco | 30 h o más |

- Cada voto lleva unos 35 s (20 a 30 s de transición más el voto). Con aprendizaje activo hace falta más o menos la mitad.
- Para elegir **qué canción va detrás de cuál**: otros 200 a 400 votos.
- Si votas siempre con las mismas 100 canciones, el modelo aprende esas canciones. Para que sirva con otras, unos 300
  votos por cada colección distinta (2 o 3 colecciones).
- Vota en sesiones cortas (30 a 40 min): cansado se vota distinto y el modelo se confunde.

## Esfuerzo total

| Bloque | Horas |
|---|---|
| A · Base | 60 a 100 |
| B · Motor propio | 110 a 190 |
| C · Nivel festival | 120 a 210 |
| D · IA | 180 a 340 |
| E · Fiesta en directo | 30 a 200 (según opcionales) |
| **Total** | **500 a 1.000 horas** |

Como proyecto de fines de semana: de 1 a 2 años. Los bloques A y B solos ya dan un DJ automático mejor que la mezcla
automática de Spotify.

## Problemas que vendrán

**De audio**
- BPM a la mitad o al doble en música urbana (fase 5).
- Canciones con tempo variable o grabadas en directo: la rejilla de golpes se desfasa.
- Cambiar el tempo más de un 8 % suena artificial.
- Tonalidad poco fiable en canciones con pocas armonías.
- Voces solapadas: es el fallo que más se nota en una fiesta.
- Masterizados distintos: sin igualar volumen, los saltos estropean la mezcla.
- mp4 con audio de baja calidad.

**Del motor y de Windows**
- Latencia y cortes de audio: un tirón de CPU se oye. Puede hacer falta un controlador ASIO.
- El motor propio tiene que convivir con lo que ya existe (barra de reproducción, letras, control multimedia de Windows).

**De empaquetado (importante para el instalador)**
- Hoy el instalador pesa unos 85 MB. numpy y librosa añaden bastante; PyTorch (para Demucs y la IA) puede añadir
  **más de 1 GB**. Solución probable: que las partes pesadas (voces, IA) se descarguen aparte solo si se activan, igual
  que ya se hace con ffmpeg.

**De la IA**
- Que aprenda a engañar al puntuador automático en vez de sonar mejor (por eso tus votos son el árbitro).
- Que aprenda solo tus 100 canciones.
- Tu gusto no es el del público.
- Medir si mejora es difícil: hay que comparar siempre a ciegas.

**Legales**
- Poner música comercial en un evento público requiere pagar derechos (SGAE en España).
- Descargar mixes de YouTube para entrenar va contra sus condiciones aunque sea para uso personal.

## Lo que no se va a conseguir (para no llevarse sorpresas)
- Un DJ de festival de verdad: la creatividad, las ediciones propias y la lectura de la sala no se automatizan bien.
- Que no falle nunca. La meta realista es que **nunca suene a desastre**: si duda, transición corta y limpia.
