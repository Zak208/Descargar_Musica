# Motor de audio del modo DJ (fases 9 y 10)

Qué motor se eligió, con qué mediciones, qué límites tiene y qué tendrá que cablear la interfaz. El código está en
`src/services/audio_engine.py` (clase `MixEngine`) y sus pruebas en `pruebas/prueba_motor_audio.py`.

## Decisión (fase 9): híbrido

El plan proponía dos opciones. Se elige una tercera que toma lo mejor de cada una:

| | Opción 1: tiempo real (numpy + sounddevice) | Opción 2: todo por adelantado con ffmpeg | **Híbrido (elegido)** |
|---|---|---|---|
| Dónde se mezcla | En la llamada de audio, muestra a muestra | En ffmpeg, a un archivo o tubería | En numpy, en un hilo de trabajo, antes de que haga falta |
| Qué hace la llamada de audio | Mezclar dos platos, ecualizar, estirar | Nada (lo toca QMediaPlayer) | Copiar trozos ya hechos y aplicar una ganancia |
| Riesgo de cortes | Alto: Python con el GIL en tiempo real | Bajo | Bajo: la llamada dura 0,02 ms de media |
| Precisión entre canción y transición | Exacta | Mala: QMediaPlayer no encadena archivos sin hueco | Exacta (a la muestra) |
| Flexibilidad (EQ, cambio de graves, efectos) | Total | La de los filtros de ffmpeg | Total (numpy), con rubberband de ffmpeg para el tempo |
| Saltar, pausar | Inmediato | Hay que regenerar archivos | Inmediato (fundido de 15 ms) |

Por qué no la opción 1 pura: hacer el ecualizador y el estiramiento dentro de la llamada de audio obliga a que Python
termine cada bloque a tiempo con el GIL compartido con la interfaz; cualquier pausa del recolector de basura o una tarea de
Qt larga se oiría. Por qué no la opción 2 pura: ffmpeg prepara bien una transición (0,35 s medidos, abajo), pero luego
hay que tocar «cuerpo de A, transición, cuerpo de B» sin hueco, y QMediaPlayer no lo garantiza; además cada salto o cambio
de planes obliga a regenerar archivos.

Reparto en el híbrido:
- `pcm_loader` (otro módulo): decodifica con ffmpeg a float32 estéreo a 44.100 Hz y estira el tempo con `rubberband`.
- `dj_dsp.render_transition`: ecualizador de 3 bandas y cambio de graves sobre arrays.
- `audio_engine.MixEngine`: toca segmentos uno detrás de otro, sin huecos ni solapes, en un flujo continuo de sounddevice.

## Mediciones (equipo del usuario, Windows 11, «Altavoces (Realtek USB Audio)»)

Todas en silencio (ganancia maestra 0 y contenido a -80 dB; el medidor de pico de la salida dio 0,0 en todas). La CPU
estaba compartida con otros cuatro procesos de trabajo, así que los tiempos absolutos son pesimistas.

Llamada de audio, 3 s por caso:

| API de Windows | latencia pedida | bloque | latencia real | llamada máx. | llamada media | subdesbordamientos |
|---|---|---|---|---|---|---|
| MME (predeterminada) | high | 1024 | 186 ms | 0,12 ms | 0,020 ms | 0 |
| MME | low | 1024 | 93 ms | 0,07 ms | 0,021 ms | 0 |
| MME | low | 512 | 93 ms | 0,07 ms | 0,015 ms | 0 |
| DirectSound | low | 512 | 120 ms | 0,13 ms | 0,026 ms | 0 |
| WASAPI compartido (`auto_convert`) | low | 512 | 23,5 ms | 0,14 ms | 0,022 ms | 0 |
| WASAPI compartido (`auto_convert`) | high | 1024 | 46 ms | 0,06 ms | 0,025 ms | 0 |

El presupuesto de cada llamada es 23,2 ms con bloque 1024 (11,6 ms con 512): la llamada usa menos del 1 %. WASAPI sin
`auto_convert` no abre (el mezclador de Windows de este equipo va a 48.000 Hz y el motor a 44.100 Hz).

Prueba de resistencia de 10 minutos (configuración predeterminada: MME, latencia «high», bloque 1024), alimentando el
motor como lo haría el DJ: canciones sintéticas de 40 a 70 s, transiciones de 16 s hechas con `dj_dsp.render_transition`
en un hilo de trabajo, un salto cada 90 s, una pausa de 1 s cada 2 min, y un hilo «de interfaz» que recoge notificaciones
cada 50 ms y gasta 5 ms de Python puro en cada vuelta (sostiene el GIL):

| Cifra | Resultado |
|---|---|
| Llamadas de audio | 25.852 (las esperadas en 600 s: 25.853) |
| Subdesbordamientos, otros avisos, errores | 0, 0, 0 |
| Duración de la llamada | máxima 0,46 ms, media 0,0145 ms (presupuesto 23,2 ms) |
| Hueco máximo entre dos llamadas | 70 ms (MME las agrupa; el colchón es de 186 ms; ninguna por encima de 100 ms) |
| CPU del proceso entero | 10,1 % de un núcleo, casi todo del simulador (los 5 ms de cada 55 ms del hilo «de interfaz», unos 9 %, y las canciones sintéticas); la llamada de audio sola: 0,0145 ms × 43 por segundo, un 0,06 % |
| Trabajo hecho | 18 transiciones (la más lenta, 0,12 s), 6 saltos, 4 pausas, 32 inicios de segmento notificados, ninguna cola vacía |
| Pico de la salida | 0,0 (no salió sonido) |

Preparación (canciones reales de la biblioteca, mp3 de 4 a 4,5 min, con la CPU compartida):

| Paso | Tiempo |
|---|---|
| Decodificar una canción entera a float32 con ffmpeg | 0,28 a 0,30 s |
| rubberband (tempo 1,04) de 20 s de B, incluida la decodificación | 0,37 s |
| rubberband de una canción entera | 4,0 s |
| `dj_dsp.render_transition` de 16 s | 0,10 s |
| Opción 2: la misma transición con un grafo de ffmpeg (decodifica A y B, recorta, filtra, funde) | 0,35 s |

Preparar una transición cuesta menos de 1 s: basta con empezar a prepararla 30 s antes de que haga falta.

La **puerta de la fase 9** (30 minutos con sonido real sin cortes ni chasquidos) la tiene que pasar el usuario de oído;
lo de arriba solo demuestra que el motor no se queda sin datos ni tarda en la llamada.

## Límites conocidos

- **Memoria.** Una canción de 4 min en float32 estéreo a 44.100 Hz ocupa unos 85 MB (medido: 88 a 92 MB las de 4,1 a 4,4 min).
  Política propuesta: en memoria solo la canción que suena (A) y la siguiente (B), más la transición ya hecha (16 s = 5,6 MB).
  Pico: unos 270 MB mientras se decodifica B y A aún suena entera. A se suelta cuando empieza la transición: el motor deja de
  referenciar su cuerpo al acabarlo y la sesión debe soltar su array (si no, se queda). Canciones muy largas (sesiones o mixes
  de más de 15 min, más de 300 MB): no mezclarlas, o decodificar solo el principio y el final que hacen falta.
- Los segmentos que se encolan **no se copian** si ya son float32 contiguos (n, 2): un trozo `cancion[a:b]` no gasta memoria
  aparte. No hay que modificar un array después de encolarlo.
- **Latencia.** Con la configuración predeterminada (MME, «high») lo que se oye va 186 ms por detrás de `position_frames`;
  la interfaz debe restar `output_latency_s` al mostrar la posición. Pausar o saltar tarda eso en oírse; para un DJ automático
  es aceptable. Si molesta, WASAPI con `extra_settings=sd.WasapiSettings(auto_convert=True)` baja a 23 a 46 ms (medido sin
  cortes en 3 s, falta la prueba larga).
- **GIL.** La llamada de audio es Python: si otro hilo sostiene el GIL más tiempo que la latencia (186 ms), habrá corte. Lo
  pesado de numpy y la decodificación (proceso aparte) sueltan el GIL; los bucles largos en Python puro no. No hacer trabajo
  pesado en Python puro mientras suena el DJ.
- **Dispositivo desconectado** (auriculares USB, Bluetooth): el flujo se para y llega `on_stream_finished`. El motor no
  reabre solo; la sesión debe llamar a `stop()` y `start()` (con otro dispositivo o el predeterminado nuevo).
- **Saturación.** El motor lleva un limitador suave de salida (ver «Limitador de salida» abajo): nada sale por encima de ±1,0
  y por debajo de 0,9 no se toca nada.
- Un segundo salto antes de que acabe el fundido del primero (15 ms) corta en seco ese resto de fundido.
- ASIO: la rueda de sounddevice trae también una PortAudio con ASIO (`libportaudio64bit-asio.dll`), que solo se usa con la
  variable de entorno `SD_ENABLE_ASIO`; no se ha probado.

## API de `MixEngine`

```python
available() -> bool                                      # numpy + sounddevice + dispositivo de salida
output_device_info(device=None) -> dict | None
MixEngine(sample_rate=44100, blocksize=1024, device=None, latency="high", master_gain=1.0, fade_ms=15.0,
          meter=False, extra_settings=None)              # RuntimeError si falta numpy
.start() -> bool / .stop(fade=True) / .stream_active / .output_latency_s / .last_error
.queue(array, label=None) -> seg_id | None               # (n, 2) o (n,) mono; vacío = no se encola
.replace_queue(segments) -> [seg_id]                     # cambia el futuro; lo que suena acaba entero
.clear_queue() -> int
.replace(segments=(), fade=True) -> [seg_id]             # salta ya, con fundido cruzado de 15 ms
.play(fade=True) / .pause(fade=True) / .is_playing
.set_master_gain(g, ramp_ms=50) / .master_gain           # 0 a 1, rampa lineal
.position_frames / .position_s / .current() / .remaining_frames / .queued_count
.poll_events() -> [tuplas] / .dispatch_events() -> int
.on_segment_start(label, seg_id, start_frame) / .on_queue_empty(position_frames) / .on_stream_finished(motivo)
.pull(frames) -> array (frames, 2)                       # lo mismo que la llamada de audio, sin dispositivo
.stats() -> {callbacks, underflows, other_status, errors, max_ms, mean_ms, budget_ms, latency_s, peak_out}
```

Cuando no hay nada que tocar o está en pausa, sale silencio; la llamada de audio nunca lanza una excepción (si algo
falla dentro, sale silencio y se cuenta en `errors`).

## Contrato para la integración en la interfaz (fase 10)

Lo que tendrá que hacer la sesión DJ (`dj_mixin` / `dj_service`), sin tocar el motor:

1. **Arrancar.** Si `audio_engine.available()` es False, seguir con el fundido de QMediaPlayer de siempre. Si es True,
   crear un `MixEngine`, `start()`, pausar QMediaPlayer (no deben sonar los dos) y un `QTimer` de 50 ms que llame a
   `dispatch_events()` en el hilo de la interfaz.
2. **Cargar.** En un hilo de trabajo (`services/heavy.py` o un `QThread`), decodificar A con `pcm_loader` y encolar su
   cuerpo: `queue(A[intro:inicio_mezcla], ("cuerpo", pista_A))`. La etiqueta puede ser cualquier objeto; conviene que diga qué
   pista es y desde qué segundo de ella empieza el segmento.
3. **Planificar y prerenderizar la siguiente** cuando `remaining_frames` baje de unos 30 s (o nada más encolar el cuerpo):
   `dj_planner` da el `TransitionPlan`; `pcm_loader` trae B estirada lo justo; `dj_dsp.render_transition(trozo_A, trozo_B, plan)`
   hace la transición; se encolan la transición y el cuerpo de B. Con el tempo de B cambiado, el cuerpo de B sigue en su
   tiempo original desde `plan.b_start_s + plan.length_s * plan.tempo_ratio_b`.
4. **Cambiar de planes** (el usuario reordena, vota o cambia la siguiente): `replace_queue([...])` con lo nuevo; lo que
   suena acaba entero, sin corte.
5. **Saltar** (botón siguiente): `replace([(cuerpo_de_B, etiqueta)])` corta con fundido de 15 ms; mejor aún, planificar un
   corte en el siguiente compás (`TransitionPlan(kind=KIND_CUT)`) y usar `replace` con ese corte. **Buscar** dentro de la
   canción: `replace([A[nueva_pos:fin_cuerpo], ...])` y volver a encolar la transición.
6. **Pausa y volumen:** `pause()` / `play()`; el control de volumen de la barra llama a `set_master_gain` (la curva de
   volumen percibido la pone la interfaz).
7. **Mostrar la posición:** con `current()` (etiqueta, seg_id, muestras tocadas del segmento, total) y la etiqueta, la
   sesión sabe la pista y el segundo: inicio del segmento en la pista + tocadas / 44.100 (× tempo si el segmento está
   estirado) - `output_latency_s`. La barra de reproducción, la letra y el control multimedia de Windows (SMTC) se
   alimentan de eso en vez de QMediaPlayer.
8. **Notificaciones:** `on_segment_start` sirve para cambiar el título «sonando» (al empezar la transición o a su mitad)
   y apuntar la reproducción; `on_queue_empty` significa que no se preparó a tiempo (o fin de la sesión);
   `on_stream_finished`, que se perdió el dispositivo.
9. **Cerrar:** `stop()` en el cierre de la ventana (hace el fundido y cierra el flujo). Soltar los arrays de las pistas.
10. **Empaquetado:** PyInstaller tiene que llevar `_sounddevice_data/portaudio-binaries/libportaudio64bit.dll` (unos 300 KB);
    el gancho de `pyinstaller-hooks-contrib` para sounddevice lo hace, pero hay que comprobarlo en el `.spec` y en el
    instalador (no se ha probado).

## Sesión del DJ: arreglos e integración de los módulos (fases 0 a 6 de la integración)

Lo que la sesión (`dj_engine.EngineSession`) hace además de la mezcla larga y el corte limpio. Las pruebas están en
`pruebas/prueba_motor_dj_arreglos.py` y en las que se citan en cada punto.

### Arreglos (fase 0)

- **Redondeo del plan.** `mix_points.plan` redondea el principio y la longitud de la mezcla a milésimas por separado y la suma
  se podía pasar hasta 44 muestras del final de A: la mezcla se rechazaba y caía a corte (casi la mitad de las canciones sin
  análisis). Ahora se admite un exceso de hasta 50 ms (`FIT_TOL_S`); lo que falta de A se rellena con silencio con la rampa de
  5 ms de `render_transition` (A ya está casi a cero al final de la mezcla).
- **Canciones cortas.** Con trozos de 15 s, en una canción de 20 s el primer trozo ya sonaba pasado el punto de mezcla y toda
  transición era un «plan tardío». `MixEngine.truncate_current(seg_id, frames, guard)` acorta el segmento que suena (solo si
  lo tocado más 0,25 s de margen no llega al nuevo final) y la sesión lo usa para que el punto de mezcla caiga dentro del
  trozo que suena. El corte tardío queda solo para cuando lo que suena ya pasó el punto de mezcla.
- **B muy corta.** `mix_planner` limitaba la mezcla por frases solo por A: con B de 25 s salía una mezcla de 32 s que el motor
  rechazaba. Ahora la frase se parte hasta que mide como mucho un tercio de B (como la fase 8) y deja al menos 1 s de cuerpo
  de B. Si aun así la mezcla no se puede hacer, el corte va al compás de donde la mezcla habría acabado, no a su principio.
- **Carga que se quedaba en «cargando».** Si fallaba el cálculo de la ganancia de la canción pedida, la sesión no salía nunca
  de «loading». Ahora queda «stopped» con el error.
- **Canciones de más de 8 min.** `pcm_loader.MAX_SECONDS` (480 s) corta sin avisar. La sesión lo detecta (lo cargado llega al
  tope y el análisis dice que dura más) y la transición es un corte limpio en el último compás antes del tope, con su motivo,
  en vez de una mezcla de outro sobre un final que no existe. El tope no se ha subido (`pcm_loader` no es de este cambio): una
  canción de 12 min serían 254 MB, y con A y B en memoria se pasaría del medio giga.

### Limitador de salida (fase 1)

Dos canciones igualadas a -14 LUFS sumadas en una mezcla pasan de 1,0 (el grabador midió picos de 1,93) y los mp3 reales ya
pasan de 1,0 en un 0,1 a 0,3 % de las muestras. `MixEngine` aplica al final de cada bloque (después de las ganancias de pausa
y maestra) una rodilla suave, estática y por muestra:

    |x| <= 0,9  ->  sin cambios (idéntica, muestra a muestra)
    |x| >  0,9  ->  signo(x) · (0,9 + 0,1 · tanh((|x| - 0,9) / 0,1))      (pendiente 1 en 0,9, nunca llega a 1,0)

No tiene memoria entre bloques, así que no puede crear saltos en las uniones. NaN e infinitos salen como 0 y ±1. Se puede
apagar con `MixEngine(limit=False)` (las pruebas que comparan muestras numeradas mayores que 1 lo hacen). `stats()` cuenta
en `limited_blocks` los bloques en los que tuvo que redondear algún pico. No es un limitador con ataque y relajación: redondea
los picos que pasan de 0,9 (algo de distorsión armónica en ellos, mucho menos que el recorte duro del dispositivo); que suene
transparente en música real es una hipótesis que hay que comprobar de oído.

Coste medido (pruebas/prueba_motor_audio.py, bloque 1024, sin dispositivo, CPU compartida): media 0,0024 ms si nada pasa del
umbral (dos reducciones; 0,0011 ms sin limitador) y 0,015 ms si todo el bloque pasa (presupuesto 23,2 ms). Con el
dispositivo real la media siguió en 0,022 a 0,028 ms y la máxima en 0,1 ms.

### Tipos de transición (fase 2, `EngineSession(typed=True)`, activo por defecto)

`_blend`, `_cut` y `_late_cut_locked` piden el tipo a `transition_types.choose_type(ficha A, ficha B, plan, BPM de A)` y lo
renderizan con `render_typed_parts` (la mezcla larga y el corte limpio siguen saliendo de `render_transition` tal cual). La
regla de seguridad de `choose_type` manda: con rejillas de confianza menor de 0,4 o un cambio de tempo de más del 5 % nunca
hay mezcla larga de graves (corte en el compás, o mezcla si ya era corta). Detalles de la integración:

- La mezcla mide lo mismo en todos los tipos y B no se desplaza: el cuerpo de B, el empalme del tramo estirado y las
  posiciones no cambian.
- Con cut_bar y echo_out B suena sola desde el corte (`bass_swap_at`): la mezcla se parte ahí, no en la mitad, y `advanced`
  sale cuando entra B.
- La cola del eco se SUMA al principio del cuerpo de B, en una copia (los trozos del cuerpo son vistas): se encola un trozo
  «entry» con el empalme del tramo estirado (si lo hay) seguido del cuerpo de B desde `b_body`, con la cola encima, y el
  cuerpo normal sigue tras él. Si B se acaba antes que la cola, la cola baja a cero en 50 ms.
- En la práctica la cola solo aparece en cortes (plan de corte por tempos lejanos, corte tardío o por mezcla imposible): en
  una mezcla, el corte cae hacia la mitad y el eco (unos 3,9 s a 120 BPM) se apaga dentro.
- El tipo se ve en el motivo del plan («...; tipo: eco de salida: ...») y en el estado de `tick()` (`transition_type`).
- `typed=False` da exactamente la mezcla de antes (`pruebas/prueba_motor_dj.py` la usa para comparar muestra a muestra).
- Coste: el filtro tarda 1 s con 30 s de mezcla (los demás, unas centésimas); va en el hilo de trabajo.

Pruebas: `pruebas/prueba_motor_tipos.py` (cada tipo en su sitio y con la longitud exacta, sin clic, cola sumada, `advanced`,
posiciones, seek, replan, memoria, corte tardío con eco y `typed=False`). Que cada tipo suene bien en su caso es una
hipótesis: no se ha oído.

### Puntuador como red de seguridad (fase 3, `EngineSession(audio_check="light")`, activo por defecto)

Todo en el hilo de trabajo, nunca en la llamada de audio.

1. **Antes de renderizar** una mezcla, `transition_scorer.score_plan(ficha A, ficha B, plan)` (microsegundos). Si dice
   «descartar» (cambio de tempo de más del 8 %, la mezcla no cabe en alguna de las dos...), se pasa a corte limpio en el
   compás donde la mezcla habría acabado, con el motivo en `plan.reason` («corte limpio: el puntuador descartó la mezcla
   (...)»), sin estirar ni renderizar nada.
2. **Después de renderizar** una mezcla en la que suenan las dos (mezcla, filtro o eco de salida; el corte en el compás no se
   mide: es ya lo más seguro), se buscan los fallos que un corte en el compás arregla: clic, recorte, hueco de silencio o
   salto de volumen. Si hay alguno, la mezcla NO se retoca: se vuelve a renderizar como corte en el compás (`cut_bar`), con el
   motivo en el plan («tipo: corte en el compás: el puntuador descartó «blend» (...)»). Los veredictos de gusto (golpes
   desfasados, graves dobles, voces, tonos) no cambian nada aquí: los usa la elección del tipo y quedan para el diagnóstico.

Umbrales (los de `transition_scorer`, sin tocar): clic si un salto entre muestras es 10 veces el normal de sus 50 ms de
alrededor y 1,5 veces lo que ya tenían A y B; recorte si la mezcla añade un 0,1 % de muestras por encima de 1,0; hueco si hay
500 ms por debajo de -60 dBFS; salto de volumen si el nivel a corto plazo (400 ms) cambia 8 dB más de lo que traían A y B
(con los 2 s de antes y de después). **Son de criterio, no están calibrados con el oído**; cuando haya votos (fase 24) habrá
que ajustarlos.

Coste. `score_audio` entero cuesta 0,12 s con 8 s de mezcla y 0,41 s con 32 s (medido), por encima de lo que se quería
gastar (0,1 s). Por eso el modo por defecto, «light», usa las mismas funciones y umbrales del puntuador pero solo para esas
cuatro medidas, y el clic solo en ±50 ms alrededor de cada unión (principio de la mezcla con el cuerpo de A, final con lo que
sigue de B y, en el eco de salida, el corte): son los únicos sitios donde el motor puede crear un salto, porque dentro de la
mezcla todo es una combinación lineal suave de A y B. Medido: 55 a 60 ms con 16 s de mezcla y 108 ms con 32 s. Limitación:
un clic en mitad de la mezcla (un fallo del render) solo lo ve `audio_check="full"`, que llama a `score_audio` entero.
`audio_check=None` no puntúa nada. Lo que dijo el puntuador queda en `_Pair.check` (veredicto del plan, motivos del audio,
tipo descartado y segundos).

Pruebas: `pruebas/prueba_motor_puntuador.py`.

### Bucles (fase 4, `EngineSession(loops=True)`, APAGADO por defecto)

Cómo se integra (`loops.needs_loop` + `loops.extend_body`, siguiendo lo que pide `loops.py`):

- Tras preparar una mezcla, si `needs_loop(ficha A, ficha B, plan, rejilla A, rejilla B)` pide 4 u 8 compases, A se alarga
  repitiendo sus 4 compases de antes del punto de mezcla M: suena su cuerpo hasta L = M - 4 compases, luego las repeticiones
  (segmentos con rol «loop», etiquetados en el tiempo de A de la región, así que la posición vuelve atrás en cada vuelta) y
  luego la mezcla, la misma de siempre y desde la misma muestra M de A. `_Pair` guarda `loop_segs`, `loop_start`, `loop_id` y
  `loop_bars`; el plan lleva el motivo («; bucle de 8 compases: ...») y el estado de `tick()`, `loop_bars`.
- `_from_frame_locked`: cuerpo hasta L y bucle; desde dentro de la región [L, M) (un seek), el resto de la primera vuelta y
  las demás. `_future_locked`: tras una vuelta, la siguiente; el trozo del cuerpo que suena se acorta en L (no en M).
  `_late_cut_locked`: si lo que suena ya pasó M, corte tardío sin bucle, como siempre. `_seek_locked`: como antes.
- `_locked_in_locked`: con el bucle sonando, B ya no se cambia (el bucle va derecho a la mezcla). Si se dejara a medias, el
  final de una vuelta que no es la última está doblado hacia el principio de la siguiente (el fundido de la unión de
  `loops.repeat`) y saltar de ahí al cuerpo de A en M haría un medio escalón (posible clic).
- `needs_loop` solo lee `intro_s`; la sesión le pasa la intro de B en segundos aunque la ficha la traiga en milisegundos (el
  análisis de la aplicación usa `intro_ms`: sin esto el bucle no se pediría nunca).

Por qué queda apagado (decisión, no un fallo de las pruebas, que pasan: `pruebas/prueba_motor_bucles.py`, con carrera
contra la llamada de audio):

1. El motivo que más se da en la práctica (la intro de B no está hecha al acabar la mezcla) solo **retrasa** la mezcla: B
   entra con el mismo `b_start_s` (lo avisa `needs_loop`), así que el bucle no arregla lo que mide; es A sonando 8 compases
   más. Para que sirva habría que recalcular la entrada de B (que B empiece antes, por debajo del bucle), y eso es otra mezcla.
2. El otro motivo (mezcla a 4 compases de una frase) casi nunca se da: con rejillas el planificador ya empieza la mezcla en
   un comienzo de frase de 8 o 16 compases.
3. Mientras suena el bucle (hasta 16 s) no se puede cambiar la siguiente.
4. La interfaz calcula la cuenta atrás de la mezcla con `plan.a_start_s - posición`: con el bucle, la posición vuelve atrás
   y la cuenta atrás sube y baja. Habría que darle a la página los segundos de salida que faltan (no es de este cambio:
   `ui/dj_mixin.py` lo lleva otra sesión).
5. No se ha oído: que la repetición suene natural en música real es una hipótesis.
