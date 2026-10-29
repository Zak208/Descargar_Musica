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
- **Saturación.** El motor no recorta: si la mezcla pasa de ±1,0 lo recorta el dispositivo. El margen (o un limitador) va en
  la preparación de la transición.
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
