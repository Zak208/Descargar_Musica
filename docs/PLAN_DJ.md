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

### Fase 4 · Análisis de cada canción (12 a 20 h)
- Guardar en el índice: BPM, confianza del BPM, energía media, duración de intro y de final.
- Se analiza una vez en segundo plano (con `heavy_task`) y se guarda; solo se repite si cambia el archivo.
- Barra de progreso «Analizando 34 de 100».
- **Puerta**: el BPM es correcto en al menos 90 de 100 canciones (comprobado a mano con unas cuantas).

### Fase 5 · Corregir BPM a mano (4 a 6 h)
- En reguetón, drill y trap el BPM sale a veces a la mitad o al doble (95 frente a 190).
- Regla de rango plausible por género y, en la página DJ, botones «×2» y «÷2» y escribir el BPM.
- **Puerta**: ninguna canción de tu carpeta con BPM claramente mal.

### Fase 6 · Tonalidad (8 a 14 h)
- Detectar la tonalidad y pasarla a la rueda Camelot (8A, 9B...).
- Nueva dependencia (essentia o librosa). Ver «Empaquetado» más abajo: puede pesar mucho.
- **Puerta**: la tonalidad coincide con la de una web de referencia en al menos 70 de 100. En música urbana falla más.

### Fase 7 · Orden inteligente (10 a 16 h)
- La siguiente canción se elige por compatibilidad: BPM cercano, tonalidad compatible, energía y género.
- Curva de energía de fiesta: calentar, subir, picos, bajar y volver a subir.
- **Puerta**: a ciegas, prefieres el orden inteligente al aleatorio en 7 de 10 sesiones cortas.

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
