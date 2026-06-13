# ROADMAP v3 — "El Escenario" (En planificación)

**Objetivo**: elevar Show Designer del nivel "secuenciador completo" al nivel "herramienta
profesional de producción" — lista para el bolo real, con banco de efectos de categoría,
soporte de hardware ampliado y un ecosistema sostenible a largo plazo.

**Punto de partida**: v1.10 · 700 tests verdes · bloques A–D completos · tag `v1.10-roadmap-v2`.

**Modelo de ejecución**: mismo que v2 (ver §Reglas del juego en `ROADMAP.md`). Las reglas
de la casa, los invariantes I1–I5 y el checklist de cierre siguen vigentes sin excepción.
Este doc añade convenciones v3 si las hay; en lo demás, hereda ROADMAP.md §0.

**Audiencia**: equipo mid/junior. Cada fase tiene el PORQUÉ, el CÓMO y el criterio de
aceptación redactados para que no haya que asumir nada. Si algo no se entiende, preguntar
ANTES de programar.

---

## Mapa de los cuatro bloques

| Bloque | Quién lo usa | Qué añade |
|--------|-------------|-----------|
| **E — PRODUCCIÓN** | El operador la noche del bolo | Cues, OSC, blackout, identificar fixtures, export de preview |
| **F — EFECTOS** | El diseñador llenando el show | 10 efectos nuevos, UI auto-generada, presets curados, live preview |
| **G — HARDWARE** | El técnico conectando el rig | sACN, Ableton Link, moving heads en el timeline, DMX USB |
| **H — PLATAFORMA** | El equipo (y futuros usuarios) | SDK de plugins, instalador Windows, multi-show, rendimiento a escala |

### Grafo de dependencias v3

```
F1 ──→ F2 ──→ F3
              │
              └──→ F4 (live preview necesita PARAM_SCHEMA de F2)
E1 (independiente de E2/E3/E4)
E2 depende de que E1 exista (usa go_cue por OSC)
G1, G2, G3, G4: independientes entre sí (solo necesitan tener F0–D2 estable)
H1 depende de F2 (el SDK documenta PARAM_SCHEMA)
H2, H3, H4: independientes
```

---

# BLOQUE E — PRODUCCIÓN

> *Llevar el show al escenario con confianza.*

## E1 — Sistema de Cues profesional ✅ APLICADA 2026-06-13

**Qué**: los `CuePoint` del timeline son marcadores pasivos. Necesitamos una lista de cues
ACCIONABLE — Cue 1 → GO → Cue 2 — como en QLab o grandMA, para poder operar el show con
precisión sin improvisar el timing.

**Por qué ahora**: tenemos render offline (B3), autosave (B4), playback fiable. El siguiente
cuello de botella en producción es el operador que no puede "esperar el GO" entre escenas.

### Modelo (extender `src/core/timeline_model.py`)

```python
@dataclass
class CueEntry:
    uid: str              # uuid4 hex[:12]
    number: float         # 1, 1.5, 2… (decimal para insertar entre cues)
    name: str
    t_ms: int             # instante del timeline al que salta
    fade_in_ms: int = 0   # crossfade de entrada (0 = corte seco)
    hold_ms: int = -1     # -1 = esperar GO manual; ≥0 = auto-follow tras N ms
    auto_follow: bool = False  # True si hold_ms >= 0

@dataclass
class CueList:
    entries: List[CueEntry]   # ordenadas por number
    active_uid: Optional[str] = None  # cue actualmente en reproducción
```

- `CueList` vive en `Timeline.cue_list` (contenedor nuevo en show.json → subir `version`
  a 4, migración tolerante: si falta, `cue_list = CueList(entries=[])`).
- **No borrar** los `CuePoint` existentes (son marcadores del timeline) — `CueEntry` es la
  entidad de la lista; internamente puede referenciar un `CuePoint` por t_ms, pero es un
  concepto separado.

### Backend

Handlers en `dispatcher.py`:
- `cue_add(name, t_ms, fade_in_ms=0, hold_ms=-1)` → devuelve `CueEntry` (I3).
- `cue_update(uid, **fields)` → idem.
- `cue_delete(uid)`.
- `cue_reorder(uid, new_number)` → reordena la lista.
- `go_cue(uid?)` → si `uid` es None, avanza al siguiente; salta a `entry.t_ms` con
  crossfade de `fade_in_ms` ms (interpolar `master.blackout_fade` vía una lane efímera de A2
  que vive solo durante el fade — reusa la infraestructura, no reinventes el crossfade).
  Auto-follow: si `hold_ms >= 0`, programa un `asyncio.get_event_loop().call_later` para el
  GO automático. Emite `cue_changed` event al stream.
- `get_cue_state()` → `{active_uid, entries}`.

**Modo timecoded**: si la sesión está en playback normal (no parada), detectar
automáticamente cuando `t_ms` pasa el `t_ms` de la siguiente cue y ejecutar el GO. Esto hace
que el show "funcione solo" si el técnico no toca nada. Toggle: `cue_list.timecoded: bool`.

**Undo (I1)**: `cue_list` entra en el snapshot desde el día 1.

### Frontend

- Panel `CueList` en `Live.tsx` (sección fija, no plegable): tabla con columnas
  número / nombre / t_ms / fade / hold / auto-follow. La fila activa resaltada.
- Botón **GO** grande (verde, `Space` o `Enter`), botón ← PREV, icono de auto-follow.
- Clic en fila → go_cue(uid) directo.
- En el timeline: los `CueEntry` se pintan como triángulos en la regla (distintos de los
  `CuePoint` actuales que son rombos — usar color diferente).

### Tests

`tests/test_cuelist.py`:
- go_cue avanza al instante correcto.
- auto-follow dispara tras hold_ms (mock del event loop con `asyncio.get_event_loop()`).
- crossfade frame-exacto: en t=fade_in_ms/2 el master.blackout_fade está a 0.5.
- show v3 (sin cue_list) migra a v4 sin pérdida.
- undo/redo de cue_add.

**Aceptación**: con el show parado en t=0, presiono GO → salta a Cue 1; vuelvo a presionar
→ salta a Cue 2 con fade. Configuro hold_ms=3000 en Cue 2 → avanza solo a Cue 3 tras 3 s.
**Commit**: `roadmap-v3 fase E1: sistema de cues profesional`.

---

## E2 — OSC: entrada y salida ✅ APLICADA 2026-06-13

**Qué**: protocolo Open Sound Control para integrarse con QLab, Resolume, LiveProgrammer,
TouchOSC, etc. — el estándar de facto para comunicación entre softwares de espectáculo.

### Backend (`server/osc_bridge.py` — NUEVO)

```python
from pythonosc import dispatcher as osc_dispatcher, osc_server
# Librería: python-osc (PyPI, asyncio compatible)

class OscBridge:
    """Servidor UDP OSC + emitter OSC OUT. Instanciado en session."""

    def __init__(self, session, port_in: int = 8001, port_out: int = 8002):
        ...

    async def start(self): ...   # asyncio DatagramProtocol, no bloquea
    async def stop(self): ...
```

**OSC IN** (mensajes recibidos → handlers del dispatcher):
- `/show/go_cue <cue_uid_or_number>` → `go_cue()`
- `/macro/brightness <0..1>` → `set_macro('brightness_mul', v*2)`
- `/macro/strobe <hz>` → `set_macro('strobe_rate', hz)`
- `/live/trigger <slot>` → `live_trigger(slot)`
- `/live/stop_all` → `live_stop_all()`
- `/show/goto_t <ms>` → seek del playback

**OSC OUT** (emitido en el tick, throttled a 10 Hz):
- `/show/t_ms <ms>` — posición actual del playback.
- `/show/section <nombre>` — sección de análisis en curso (string, si hay análisis).
- `/show/beat <n>` — número de beat desde el inicio.
- `/show/rms <0..1>` — RMS del frame actual.
Solo emitir si `osc_bridge.clients_out` no vacío (evitar broadcast vacío — I4).
Clientes OUT: lista de `(ip, port)` configurada en `output_targets.json` bajo clave `"osc"`.

### Frontend (panel en `Patch.tsx`)

- Sección "OSC" en la vista Patch: puerto IN (editable), puerto OUT, toggle enable/disable,
  tabla de clientes OUT (ip:port, botón +/×), log de últimos 20 mensajes recibidos
  (tipo, args, timestamp).
- Handler `osc_get_state()` / `osc_set_config(port_in, port_out, clients_out)`.

### Tests

`tests/test_osc_bridge.py` — sin red real (loopback UDP):
- mensaje OSC `/live/trigger 3` → llama `live_trigger(3)`.
- mensaje malformado → log + no-crash (no lanza).
- throttle OUT: emitir 100 frames → solo ≤10 paquetes enviados.
- `start`/`stop` no bloquean el event loop (I4).

**Aceptación**: desde TouchOSC en el móvil mando `/show/go_cue 1` y el show salta. QLab
recibe `/show/t_ms` en sync con el playback.
**Commit**: `roadmap-v3 fase E2: OSC entrada y salida`.

---

## E3 — Export de video preview ✅ APLICADA 2026-06-13

**Qué**: reutilizar `render.npz` (B3) para generar un MP4 o GIF de preview del show — útil
para enviar al cliente o verificar el timing en pantalla.

### Backend (`server/video_export.py` — NUEVO)

```python
def export_video(
    npz_path: str,
    output_path: str,
    format: Literal["mp4", "gif"] = "mp4",
    scale: int = 4,          # píxeles por LED
    fps: int = 30,
    progress_cb=None,        # callback(pct: float)
) -> str:                    # retorna la ruta del archivo generado
```

- Frame del npz: `(10, 93, 3)` uint8. Cada frame de video = imagen `(10*scale, 93*scale, 3)`
  (las 10 barras como filas, los 93 LEDs como columnas — imagen honesta del show sin escena 3D).
  `np.kron` hace el scale sin loop.
- **Con ffmpeg en PATH**: exportar frames a un directorio temporal → `ffmpeg -framerate {fps}
  -i frame_%06d.png -vf scale=... output.mp4`. Limpiar tmpdir al terminar.
- **Sin ffmpeg**: exportar GIF animado con Pillow (`PIL.Image`, dependencia ya probable vía
  `librosa` → `imageio`; si no: `pip install Pillow` ya en requirements). Paleta adaptativa
  con `Image.quantize(colors=256, method=Image.Quantize.LIBIMAGEQUANT)` (fallback a FASTOCTREE).
  Throttle: escalar a máx 10 FPS para GIFs (reducir frames interpolando).
- Output: `projects/<slug>/preview.mp4` (o `.gif`). Guardado atómico (`.tmp` + `os.replace`).
- Correr en executor (I4) — igual que B3; progresar con callback inyectable.

Handler: `export_video(format="mp4", scale=4)` → `{status: "started"}` + eventos de progreso
`{type: "video_export_progress", pct: float}` por el stream.

### Frontend

- Botón "Export preview…" en el `RenderPanel` de `Live.tsx` (aparece solo si `baked_frames`
  disponibles). Dropdown mp4/gif + slider de scale. Barra de progreso reutilizando la de B3.
  Al terminar: enlace de descarga `<a href="/download/preview.mp4">`.
- Handler `download_preview()` → sirve el archivo via endpoint estático o streaming response.

### Tests

`tests/test_video_export.py`:
- Sin ffmpeg → genera GIF (mock de `shutil.which` devolviendo None).
- Con ffmpeg mock → llama `subprocess.run` con los args correctos (spy).
- Scale=2: shape de cada frame PIL = `(20, 186, 3)`.
- Progreso: callback llamado al menos cada 10%.

**Aceptación**: con render.npz disponible, exporto GIF en ≤30 s para el show de referencia
(el_taser, 273 s → GIF de 10 FPS ≈ 2730 frames de gif ≈ 27 MB, aceptable).
**Commit**: `roadmap-v3 fase E3: export de video preview`.

---

## E4 — Test de output y patch visual ✅ APLICADA 2026-06-13

**Qué**: herramientas imprescindibles la noche del bolo para verificar el rig físico y
reaccionar rápido si un universo no responde.

### Backend

Cuatro herramientas nuevas (handlers en `dispatcher.py`):

1. **Identify fixture** — `identify_fixture(fixture_id: str)`:
   Enciende ese fixture a blanco puro (r=255,g=255,b=255) durante 2 s, luego apaga.
   Sin tocar el timeline (estado efímero en la sesión: `session._identify = {fixture_id,
   expires_t}`). `compute_frame` aplica el identify como override de última capa (posterior
   a postfx/master, igual que el strobe de C2 — formalizar el orden).

2. **Test de universo** — `test_universe(universe: int, r: int, g: int, b: int)`:
   Llena los 512 bytes de ese universo con el color dado. Toggle: segunda llamada con el
   mismo universo apaga. Useful para verificar conexión nodo a nodo antes del show.

3. **Blackout total** — `blackout(enabled: bool)`:
   Override de `master.brightness` a 0 cuando `enabled=True`. Formalizar como
   `session.blackout: bool` (estado live, no documento) — B2 ya tenía `blackout_fade` en
   el mixer pero no era un botón duro de pánico. El blackout duro es INSTANTÁNEO (no fade),
   tiene prioridad sobre todo, incluso el identify.

4. **Flash de universo** — `flash_universe(universe: int, color, duration_ms: int = 500)`:
   Igual que test_universe pero auto-apaga tras duration_ms. Útil para verificar cables
   rápido durante el prueba de sonido.

### Frontend (mejorar `Patch.tsx`)

- **Mapa visual de barras**: sustituir la tabla actual por un grid de 10 fixtures con:
  - Miniatura de color actual (cuadrado 30×30 px, color del frame live o gris si apagado).
  - Nombre + IP del fixture.
  - Botón "Identify" (icono de bombilla) → `identify_fixture(id)`.
  - Indicador de "test activo" (borde pulsante mientras `test_universe` activo).
- **Drag para reordenar** fixtures en el mapa (reordena solo el rig_layout.json, no el
  Art-Net universe — documentarlo con tooltip para no confundir al técnico).
- **Botón Blackout** — grande, rojo, siempre visible en el topbar (igual que el STOP de
  Ableton en live). Estado sincronizado vía el stream (`{type: "blackout_changed", enabled}`).
- Panel "Test por universo": dropdown 1-10 + color picker + botones Test/Flash/Apagar.

### Tests

`tests/test_output_tools.py`:
- identify: durante los 2 s, `compute_frame` devuelve blanco en las barras del fixture.
- identify expira: pasados 2 s, el frame vuelve al normal.
- test_universe: bytes Art-Net del universo = color especificado (×93 LEDs).
- blackout duro: tiene prioridad sobre identify.
- test_universe toggle: segunda llamada apaga.

**Aceptación**: con el rig conectado, hago clic en "Identify" en barra 5 → se enciende en
blanco 2 s, se apaga sola. Pulso el botón rojo Blackout → todo a negro inmediato; vuelvo a
pulsar → recupera el show.
**Commit**: `roadmap-v3 fase E4: test de output y patch visual`.

---

# BLOQUE F — EFECTOS

> *El banco de efectos es el corazón del sistema: sin un banco rico, el diseñador trabaja
> con las manos atadas.*

## F1 — 10 efectos built-in nuevos ✅ APLICADA 2026-06-13

**Qué**: los 4 plugins actuales (`solid_color`, `waving_flag`, `spanish_flag`, `example`)
son insuficientes para producción. Añadir un banco de efectos de calidad en `plugins/effects/`
que cubra los géneros principales de espectáculo: pop, electrónica, teatro, corporativo.

**IDs**: 1006-1015 (los 1000-1005 están ocupados; reservar 1016+ para F3 y futuros plugins).

### Los 10 efectos (un archivo por efecto, PER_BAR scope salvo donde se indique)

**`gradient_sweep.py`** — id 1006, `GradientSweepEffect`
Gradiente de color que barre de izquierda a derecha (o inverso). Útil para transiciones suaves.
Params: `color1 (r,g,b)`, `color2 (r,g,b)`, `speed` (0.1..5.0, ciclos/s), `width` (0.1..1.0,
fracción del LED strip que cubre el gradiente en cada instante).
Scope: PER_BAR. Render: posición del frente = `(t*speed) % 1.0`; mezcla lineal color1/color2.

**`pixel_chase.py`** — id 1007, `PixelChaseEffect`
Píxeles individuales que corren a lo largo de la barra. El clásico "vu meter corriendo".
Params: `color (r,g,b)`, `speed` (LEDs/s), `density` (0..1, fracción de LEDs encendidos),
`direction` (1 o -1), `trail` (0..20, píxeles de estela con fade).
Scope: PER_BAR.

**`theater_chase.py`** — id 1008, `TheaterChaseEffect`
LEDs en grupos alternos que se desplazan: el clásico de marquesinas de teatro (1-encendido,
2-apagados, ciclo). Params: `color (r,g,b)`, `group_size` (1..8), `gap_size` (1..8),
`speed` (grupos/s), `direction` (1/-1).
Scope: PER_BAR.

**`twinkle.py`** — id 1009, `TwinkleEffect`
Destellos aleatorios por la barra: cada LED tiene probabilidad de encenderse un instante con
brillo aleatorio. Semilla determinista por (bar_index, led_index) para reproducibilidad.
Params: `color (r,g,b)`, `density` (0..1), `speed` (actualizaciones/s), `brightness_min`
(0..255, piso de brillo de los destellos).
Scope: PER_BAR.

**`fire.py`** — id 1010, `FireEffect`
Simulación de llama por barra: el favorito de los espectáculos. Usa el algoritmo clásico
FastLED Fire2012 (cooling/sparking). Paleta naranja-rojo-amarillo.
Params: `intensity` (0..1, multiplica el sparking), `cooling` (20..100), `sparking` (20..200),
`palette` (`"fire"` | `"ice"` | `"green"` — mapear hue).
Scope: PER_BAR. Cada instancia tiene su propio array de estado (inicializado en `__init__`
del clip — ver nota de estado de efecto a continuación).
> **Nota de estado**: los efectos no deben tener estado mutable entre renders (el motor puede
> llamar a `render()` con any t, out-of-order). `FireEffect` es una excepción justificada
> (el fuego necesita estado): usar `elapsed_time` como seed determinista de la PRNG para
> reproducibilidad. Documentar este trade-off.

**`strobe_color.py`** — id 1011, `StrobeColorEffect`
Estrobo con color configurable (el estrobo blanco ya lo cubre el macro de C2; este añade
color y es por-barra). Params: `color (r,g,b)`, `rate_hz` (0.5..60), `duty_cycle` (0.1..0.9,
fracción del ciclo encendida), `phase` (0..1, para desfasar entre barras).
Scope: PER_BAR.

**`vu_meter.py`** — id 1012, `VuMeterEffect`
Barra de nivel que sube con el RMS del audio. Lee `audio_context['norm']['rms']`.
Params: `color_low (r,g,b)`, `color_high (r,g,b)`, `smoothing` (0..0.95, EMA en el render),
`peak_hold_ms` (0..2000, cuánto aguanta el pico).
Scope: PER_BAR. El estado de `smoothing` (valor suavizado anterior) se maneja igual que
FireEffect: seed con `elapsed_time` no es posible (el suavizado es causal); alternativa:
pasar el frame anterior como `bars_state` (ya disponible en la firma de `render`).

**`rainbow_wave.py`** — id 1013, `RainbowWaveEffect`
Arcoíris animado que viaja por las barras. ALL_BARS scope para que la ola tenga coherencia
entre barras. Params: `speed` (ciclos/s), `saturation` (0..1), `width` (1..10, LEDs por
color del arcoíris), `direction` (1/-1).
Scope: ALL_BARS.

**`scanner.py`** — id 1014, `ScannerEffect`
Spot luminoso que oscila de punta a punta de la barra (evoca un scanner o Moving Light en 1D).
Params: `color (r,g,b)`, `speed` (ciclos/s), `width` (1..20 píxeles, ancho del spot),
`mode` (`"sin"` | `"bounce"` — bounce = lineal ida y vuelta, sin = suave), `trail` (0..30).
Scope: PER_BAR.

**`breathing.py`** — id 1015, `BreathingEffect`
Fade suave in/out (respiro), opcionalmente audio-reactivo.
Params: `color (r,g,b)`, `rate` (ciclos/s), `audio_reactive` (bool, si True modula rate con
`actx['norm']['rms']`), `min_brightness` (0..255).
Scope: PER_BAR.

### Criterios transversales

- Cada efecto: `PER_BAR` scope (salvo `rainbow_wave`), `expected_output_shape` declarado,
  `PARAM_SCHEMA = {}` (F2 lo llenará — dejar el dict vacío aquí, sin lógica basada en él).
- Test de render en `tests/test_effects_nuevos.py`:
  `assert out.shape == expected_shape`, `dtype == np.uint8`, `0 ≤ out ≤ 255`.
  Para los 10 efectos × 3 casos (t=0, t=500, t=1000 ms): 30 asserts básicos.
- No duplicar lógica de los 51 efectos de `effects_engine.py`; si el core ya tiene algo
  similar, importar y envolver.

**Aceptación**: cargo `el_taser`, pinto 10 clips consecutivos uno por efecto, reproduzco —
los 10 se ven distintos y ninguno lanza excepción.
**Commit**: `roadmap-v3 fase F1: 10 efectos built-in nuevos`.

---

## F2 — Plugin UI auto-generada ✅ APLICADA 2026-06-13

**Qué**: hoy el `ClipInspector` muestra los params como inputs genéricos (un `<input
type="text">` por cada key del dict). Con tipos declarados, la UI puede ser mucho mejor:
sliders con rangos, color pickers, toggles y dropdowns.

### Modelo (añadir a `src/core/effects_engine.py`)

```python
# En la clase base Effect:
PARAM_SCHEMA: ClassVar[Dict[str, dict]] = {}
# Formato de cada entrada:
# { "type": "float"|"int"|"color"|"bool"|"enum",
#   "min": ..., "max": ..., "step": ...,   # float/int
#   "options": ["a","b"],                  # enum
#   "default": ...,
#   "label": "Velocidad",                  # nombre en la UI
#   "unit": "ciclos/s" }                   # opcional
```

Los 10 efectos de F1 definen su `PARAM_SCHEMA` completo. Los 4 plugins existentes lo añaden
también (backwards-compatible: `PARAM_SCHEMA = {}` en la base = UI genérica como antes).

### Backend

- Handler `get_effect_schema(effect_id: int)` → devuelve `PARAM_SCHEMA` del efecto.
  Registrado en `_LOCAL` del dispatcher.
- `server/validators.py`: función `validate_params_against_schema(params, schema)` —
  rechaza valores fuera de `min/max`, tipo incorrecto, enum no listado. Reutilizar en
  `set_clip_effect` y `set_clip_preset`.

### Frontend (`ClipInspector.tsx`)

Generar dinámicamente según el tipo de cada param:
- **`float` / `int`** → `<input type="range" min max step>` con label + valor numérico
  editable + unidad (`"ciclos/s"`, `"px"`, etc.).
- **`color`** → color picker: `<input type="color">` (hex) + preview swatch de 24×24 px.
  Internamente los params siguen siendo `r,g,b` 0-255; la UI convierte.
  > Convención: si `PARAM_SCHEMA` tiene una entrada con `type="color"` y `key="color"`,
  > la UI entiende que hay params `{color_r, color_g, color_b}` (o simplemente `r,g,b`).
  > Definir la convención en `docs/dev/plugin-sdk.md`.
- **`bool`** → toggle switch (`<input type="checkbox">` estilizado).
- **`enum`** → `<select>` con las `options`.
- Param sin schema → input de texto genérico (como hoy, sin regresión).
- Llamar a `get_effect_schema` al abrir el inspector (una vez por efecto). Cachear por
  `effect_id` en el store.

### Tests

`tests/test_param_schema.py`:
- `SolidColorEffect.PARAM_SCHEMA['r']['type'] == 'int'` etc.
- `validate_params_against_schema` rechaza `r=300` (fuera de `max=255`).
- `validate_params_against_schema` rechaza `mode="diagonal"` si `options=["sin","bounce"]`.
- Schema vacío → pasa sin error (backwards-compat).

`web/src/api/schema.test.ts` (Vitest):
- `hexToRgb("#ff8800")` → `{r:255, g:136, b:0}`.
- `rgbToHex({r:255,g:0,b:0})` → `"#ff0000"`.

**Aceptación**: abro el inspector de un `scanner` clip → veo un slider de speed con unidad
"ciclos/s", un color picker para color, un dropdown para mode. Cambio el color en el picker
y las barras cambian al instante.
**Commit**: `roadmap-v3 fase F2: plugin UI auto-generada`.

---

## F3 — Biblioteca de presets curados ✅ APLICADA 2026-06-13

**Qué**: tener efectos no basta si el diseñador tiene que inventar los params desde cero cada
vez. Una biblioteca de presets curados (30+) permite arrancar en segundos.

**Por qué**: ya tenemos el sistema de presets (presets en el servidor, `list_presets`,
`set_clip_preset`). Solo falta poblar la biblioteca con presets de calidad para los nuevos
efectos y añadir la asociación efecto→presets relevantes en el ClipInspector.

### Contenido

Archivo `server/preset_library.py` (o ampliar el existente): 3 presets por cada efecto de F1
(= 30 presets nuevos) con nombres descriptivos:
- `gradient_sweep`: "Aurora Boreal", "Amanecer", "Crepúsculo".
- `pixel_chase`: "Hormiga Roja", "Luz de Policía", "Lluvia de Neon".
- `fire`: "Hoguera", "Llama Azul", "Infierno Verde".
- etc. — nombres sugerentes, no técnicos.

Cada preset incluye A1 modulación preconfigurada donde tiene sentido:
- `breathing/audio_reactive=True` + link `rate ← rms` ya incluido en el preset.
- `vu_meter` ya reacciona al audio por diseño, no necesita link adicional.

Handler `list_presets(effect_id?)` (ya existe) — ampliar para filtrar por efecto.

### Frontend

En el `ClipInspector`: sección "Presets sugeridos" que muestra los 3 presets del efecto
activo como chips clickables. Clic → `set_clip_preset(clip_id, preset_id)`.

### Tests

`tests/test_preset_library.py` (ampliación):
- Cada preset nuevo tiene effect_id válido.
- `set_clip_preset` aplica los params del preset (test de roundtrip).
- Los presets con A1 links incluyen `param_links` válidos en el snapshot.

**Aceptación**: pinto un clip con `fire`, veo tres chips en el inspector ("Hoguera", "Llama
Azul", "Infierno Verde"), hago clic en "Hoguera" y el clip adopta los params y modulaciones.
**Commit**: `roadmap-v3 fase F3: biblioteca de presets curados`.

---

## F4 — Live preview en el inspector ✅ APLICADA 2026-06-13

**Qué**: en el `ClipInspector`, mostrar una miniatura animada del efecto mientras el usuario
ajusta params — sin tener que reproducir el show completo para ver el resultado.

**Por qué**: hoy los cambios de params se ven en las barras solo durante la reproducción.
Si el show está parado, el diseñador trabaja a ciegas. Una miniatura elimina este pain.

### Backend

Handler `preview_effect_frame(effect_id, params, t_ms=0)`:
- Crea un `bars_state` sintético (10×93×3 ceros), llama a `EffectLibrary.get_effect(effect_id).render(...)`.
- Devuelve el frame como PNG base64 (10×93 px, escala 1:1) usando `Pillow.Image.fromarray`.
- Si `LUCES_NO_PILLOW=1`, devuelve el array raw como JSON (fallback).
- Sin estado en la sesión, sin tocar el timeline. Tiempo de respuesta < 50 ms (sync OK).
- Registrado en `_LOCAL` del dispatcher.

### Frontend (`ClipInspector.tsx`)

- Miniatura 186×40 px (2× escala) en la parte superior del inspector, renderizada como
  `<img src="data:image/png;base64,...">`.
- Re-fetch con debounce de 200 ms cada vez que cambia un param (throttle de requests I4).
- `t_ms` slider debajo de la miniatura (0..2000 ms) para previsualizar la animación del efecto.
- Si el efecto es PER_BAR, mostrar solo la fila 0; si es ALL_BARS, mostrar las 10.

### Tests

`tests/test_preview_effect.py`:
- `preview_effect_frame(1004, {r:255,g:0,b:0})` → imagen PNG válida, primer pixel = rojo.
- Efecto inexistente → error limpio (no 500).
- Sin Pillow (mock) → JSON array raw.

**Aceptación**: abro el inspector de un clip `rainbow_wave`, muevo el slider de speed → la
miniatura cambia al instante (debounce 200 ms) sin reproducir el show.
**Commit**: `roadmap-v3 fase F4: live preview en el inspector`.

---

# BLOQUE G — HARDWARE & PROTOCOLOS

> *Las 10 barras WLED son el punto de partida, no el límite.*

## ✅ G1 — sACN (E1.31) como protocolo adicional (~2 días, Sonnet) — APLICADA 2026-06-13

**Qué**: Art-Net no es el único estándar en el mercado. sACN (Streaming ACN, ANSI E1.31) es
más moderno y preferido por muchos nodos y consolas. Añadirlo como opción en `OutputRouter`.

**Librería**: `sacn` (PyPI, `pip install sacn`). Asyncio-compatible via executor.

### Backend (`src/io/output_router.py`)

Nueva clase de target:

```python
class SacnNodeTarget(OutputTarget):
    """Envía universo DMX vía sACN (E1.31 unicast o multicast)."""
    protocol = "sacn"

    def __init__(self, universe: int, ip: str, port: int = 5568,
                 multicast: bool = False):
        ...

    def send(self, universe: int, data: bytes):   # 512 bytes
        ...
```

- `output_targets.json` acepta entradas con `"protocol": "sacn"`.
- Retrocompatible: si no hay entradas sACN, el comportamiento es idéntico al actual.
- `SacnNodeTarget` instancia el sender una sola vez y lo reutiliza (como hace `ArtnetNodeTarget`).
- `close()` para el cleanup al cerrar el server.

Handler `set_output_target(fixture_id, protocol, ip, port, ...)` (ya existe como `_RIG_MUTATORS`
— extender para aceptar `"sacn"` como protocol).

### Tests

`tests/test_sacn.py` (sin red real, mock de la librería `sacn`):
- `SacnNodeTarget.send` llama al sender con el universo y los 512 bytes correctos.
- Cierre limpio: `close()` detiene el sender.
- `OutputRouter` con entrada sACN en el JSON lo instancia correctamente.
- Coexistencia: un fixture Art-Net + un fixture sACN en el mismo router.

**Aceptación**: añado `{"protocol":"sacn","universe":1,"ip":"192.168.1.50"}` en
`output_targets.json`, conecto un nodo sACN, reproduzco — las luces responden.
**Commit**: `roadmap-v3 fase G1: sACN (E1.31) como protocolo adicional`.

---

## ✅ G2 — Ableton Link / MIDI Clock sync de tempo (~2 días, Sonnet) — APLICADA 2026-06-13

**Qué**: sincronizar el BPM de Show Designer con el DJ (Ableton, Traktor, Serato, rekordbox)
via Ableton Link (LAN) o MIDI Clock (cable/USB). El Auto-VJ (D1) se vuelve milimétrico
cuando el tempo es correcto.

**Librería Link**: `pylinkbpm` (wrapper Python de Ableton Link) — o, si la librería no está
disponible en Windows, implementar MIDI Clock (más simple, menos preciso, ampliamente compatible).

### Backend (`server/tempo_sync.py` — NUEVO)

```python
class TempoSyncService:
    """Sincroniza BPM vía Ableton Link o MIDI Clock.
    Expone un BPM en vivo que session.compute_frame puede consultar."""

    mode: Literal["off", "link", "midi_clock"]
    bpm: float             # 0.0 si no hay sync
    beat_phase: float      # 0.0..1.0, posición dentro del beat actual

    async def start(self, mode, ...): ...
    async def stop(self): ...
```

- **Ableton Link**: `pylinkbpm.AbletonLink` en hilo separado (Link usa C++ threads).
  Lectura del BPM + phase vía `link.clock()` en cada tick.
- **MIDI Clock**: 24 pulsos/beat recibidos por MIDI (usar `mido` o el mismo `python-rtmidi`
  que pudiera haber). Calcular BPM por mediana de inter-pulse intervals (igual que D2 para
  la entrada de audio, reutilizar el patrón).
- `session.tempo_sync: TempoSyncService`; cuando `mode != "off"`, `_get_audio_context`
  inyecta el BPM de sync en el contexto de análisis (sobre-escribe el calculado por D2).
  El Auto-VJ de D1 usa este BPM para las cuantizaciones — no hay que cambiar D1.

Handler: `tempo_sync_get_state()`, `tempo_sync_set_mode(mode, device?)`.

### Frontend

- Sección "Sync" en `Live.tsx` (junto a la MacroStrip):
  - Indicador de BPM en tiempo real (grande, actualizado cada 200 ms por el stream).
  - Selector de modo: Off / Ableton Link / MIDI Clock.
  - Si MIDI Clock: dropdown de dispositivo MIDI (reusar la lista de C3).
  - Chip de estado: verde = sincronizado, naranja = buscando, gris = off.

### Tests

`tests/test_tempo_sync.py` (sin hardware):
- MIDI Clock: 24 pulsos a 500 ms de intervalo → BPM = 120.
- Link (mock): `bpm = 128.5` → `session.tempo_sync.bpm == 128.5`.
- `mode="off"` → no afecta al audio context del análisis (parity con D2).

**Aceptación**: con Ableton corriendo a 128 BPM en la misma LAN, activo Link → el indicador
de BPM en Show Designer muestra "128.0" y el Auto-VJ dispara en beat.
**Commit**: `roadmap-v3 fase G2: Ableton Link / MIDI Clock sync`.

---

## G3 — Moving heads: pan/tilt en el timeline (~3 días, Opus)

**Qué**: las barras WLED son el hardware actual, pero el sistema ya tiene ChannelEffects y
soporte GDTF. Falta exponer pan/tilt/gobo/color_wheel como dimensiones editables en el
timeline — con curvas de automatización (A2) y efectos de movimiento.

**Por qué Opus**: la semántica de "cómo se mezclan pan/tilt de múltiples clips en el mismo
instante" es sutil y errores aquí producen comportamiento extraño en el fixture físico.

### Modelo

```python
# Ampliar src/core/channel_effects.py (o nuevo mover_effects.py):

class PanTiltWaveEffect(ChannelEffect):
    """Oscilación continua de pan/tilt (círculo, figura 8, bounce)."""
    PARAM_SCHEMA = {
        "pan_center": {"type":"float","min":-1.0,"max":1.0,"default":0.0,"label":"Pan centro"},
        "tilt_center": {"type":"float","min":-1.0,"max":1.0,"default":0.0,"label":"Tilt centro"},
        "pan_range":   {"type":"float","min":0,"max":1.0,"default":0.5,"label":"Amplitud pan"},
        "tilt_range":  {"type":"float","min":0,"max":1.0,"default":0.5,"label":"Amplitud tilt"},
        "speed":       {"type":"float","min":0.1,"max":4.0,"default":1.0,"label":"Velocidad","unit":"Hz"},
        "mode":        {"type":"enum","options":["circle","fig8","bounce_pan","bounce_tilt"],"default":"circle"},
    }
```

- Un clip puede tener `channel_effects: List[ChannelEffectConfig]` en su dict (ya existe el
  concepto de ChannelEffect en el core). Ampliar `Clip.to_dict/from_dict` para incluirlo.
- `MixingPolicy` para múltiples clips que afectan al mismo canal del mismo fixture:
  `LAST_WINS` (el clip de layer más alto manda). Documentar en un mini-ADR (ADR-004).
- Handlers: `set_clip_channel_effect(clip_id, channel_effect_config)`,
  `delete_clip_channel_effect(clip_id, channel_name)`, `list_channel_effects()`.

### Frontend

- Tab "Movimiento" en el `ClipInspector` (junto al tab de "Params" y "Modulación"):
  - Dropdown de efecto de movimiento (PanTiltWave, CirclePulse, etc.).
  - Params del efecto (reutilizar UI de F2).
  - Preview 2D: círculo que muestra la trayectoria del spot en los próximos 2 s.
- En la vista Patch: cada moving head muestra su posición pan/tilt actual como un punto
  sobre un círculo (feedback visual del frame en curso).

### Tests

`tests/test_mover_effects.py`:
- `PanTiltWaveEffect` en mode circle: en t=0 pan=center+range, en t=T/4 tilt=center+range.
- `MixingPolicy.LAST_WINS`: dos clips en layers distintos → el de layer más alto gana.
- Persistencia roundtrip de `channel_effects` en show.json.
- `compute_frame` con un fixture mover produce valores de canal 0..1 para pan/tilt.

**Aceptación**: conecto un moving head GDTF, le añado un clip con `PanTiltWaveEffect` en
mode "circle" → el spot dibuja círculos durante el show. La curva de pan/tilt se ve en la
vista Patch (posición en tiempo real).
**Commit**: `roadmap-v3 fase G3: moving heads pan/tilt en el timeline`.

---

## G4 — Salida DMX USB directa (~2 días, Haiku)

**Qué**: hoy la salida es Art-Net o WLED (requiere nodo/switch en LAN). Añadir salida DMX
USB directa (interfaz ENTTEC Open DMX / USB Pro compatible) para instalaciones donde no
hay red, o como backup cuando falla la LAN.

**Librería**: `pyserial` (ya probable en deps) + protocolo ENTTEC Open DMX (512 bytes por
universo con framing específico). Alternativamente: driver OLA (Open Lighting Architecture)
si está instalado — más robusto pero requiere instalar OLA.

### Backend

```python
class DmxUsbTarget(OutputTarget):
    """Salida DMX vía ENTTEC Open DMX USB (puerto serie).
    Instancia una vez, reutiliza la conexión serie. Thread-safe."""
    protocol = "dmx_usb"

    def __init__(self, port: str, universe: int):
        # port: "COM3" en Windows, "/dev/ttyUSB0" en Linux
        ...

    def send(self, universe: int, data: bytes): ...
    def list_ports() -> List[str]: ...  # classmethod
```

- El framing ENTTEC Open DMX: BREAK (88µs), MAB (8µs), START CODE (0x00), 512 bytes.
  Implementar con `serial.Serial` + `time.sleep` en executor (no bloquear I4).
- En `output_targets.json`: `{"protocol":"dmx_usb","port":"COM3","universe":1}`.

Handler: `list_dmx_ports()` → lista de puertos serie disponibles con nombre.
En UI de Patch: dropdown de puerto COM al seleccionar `"dmx_usb"` como protocolo de salida.

### Tests

`tests/test_dmx_usb.py` (mock de `serial.Serial`):
- `send` escribe el framing correcto (BREAK + datos) al puerto serie.
- Cierre limpio de `serial.Serial` en `close()`.
- `list_ports()` devuelve lista (puede ser vacía).
- Error de puerto inexistente → log + no-crash.

**Aceptación**: conecto ENTTEC Open DMX USB, selecciono el puerto COM en Patch, reproduzco
→ el analizador DMX externo muestra datos. Sin LAN necesaria.
**Commit**: `roadmap-v3 fase G4: salida DMX USB directa`.

---

# BLOQUE H — PLATAFORMA & ECOSISTEMA

> *Construir un software de espectáculo sostenible: fácil de instalar, fácil de extender,
> capaz de crecer sin ralentizarse.*

## H1 — SDK de plugins público (~2 días, Sonnet)

**Qué**: hoy crear un plugin requiere leer el código fuente para entender las convenciones.
Un SDK documentado con testing harness permite que terceros (y el propio equipo) creen efectos
de calidad sin atarse al core.

### Contenido

`docs/dev/plugin-sdk.md` — guía completa:
- Estructura de un plugin válido: subclasear `Effect`, definir `PARAM_SCHEMA`, devolver la
  shape correcta, ID en rango 1000+.
- Convenciones de `PARAM_SCHEMA` (F2): tipos, color picker, enum.
- Cómo cargar el plugin: colocar en `plugins/effects/`, el loader lo detecta al arrancar.
- Cómo testear: usar `tests/plugin_test_harness.py` (NUEVO).

`tests/plugin_test_harness.py` — harness reutilizable:
```python
def assert_valid_plugin_effect(effect: Effect, params: dict = None):
    """Comprueba shape, dtype, rango de valores, PARAM_SCHEMA coherente.
    Llama al render en 3 instantes (0, 500, 1000 ms) con audio_context vacío."""
```

- Los tests de F1 (`test_effects_nuevos.py`) ya usan este harness (no duplican).
- Los 4 plugins existentes también pasan por él (añadir a `test_effects_render.py`).

`plugins/effects/plugin_template.py` — template con comentarios explicando cada campo:
```python
class MyEffect(Effect):
    name = "my_effect"          # slug único (snake_case)
    family = "custom"
    duration_ms = 2000
    scope = EffectScope.PER_BAR
    PARAM_SCHEMA = {
        "speed": {"type":"float","min":0.1,"max":5.0,"default":1.0,"label":"Velocidad","unit":"Hz"},
        "color": {"type":"color","default":[255,0,128],"label":"Color"},
    }

    def render(self, elapsed_time, bars_state, audio_context, **params):
        # elapsed_time: float (ms desde el inicio del clip)
        # bars_state: np.ndarray (10,93,3) uint8 — frame anterior
        # audio_context: dict con actx['norm'] etc.
        # params: dict con los valores actuales (ya modulados por A1/A2/C2)
        out = np.zeros((1, LEDS_PER_BAR, 3), dtype=np.uint8)
        return out
```

### Tests

`tests/test_sdk_harness.py`:
- `plugin_template.py` pasa el harness.
- Efecto con shape incorrecta (devuelve `(2, 93, 3)` en PER_BAR) → harness falla con mensaje claro.
- Efecto con `PARAM_SCHEMA` incoherente (tipo "int" con default float) → harness avisa.

**Aceptación**: un desarrollador externo puede crear un efecto nuevo siguiendo solo `plugin-sdk.md`
(sin leer el core) y testearlo con el harness en ≤15 min.
**Commit**: `roadmap-v3 fase H1: SDK de plugins público`.

---

## H2 — Instalador Windows (~2 días, Haiku)

**Qué**: hoy arrancar el proyecto requiere Python 3.11, venv, `pip install`, y saber usar
PowerShell. Un instalador `.exe` reduce la barrera de entrada a cero para usuarios técnicos
de iluminación (no desarrolladores).

### Estrategia

**PyInstaller** para empaquetar Python + dependencias en un directorio autocontenido:
```powershell
pyinstaller --noconfirm --onedir --name "ShowDesigner" `
  --add-data "web/dist;web/dist" `
  --add-data "plugins;plugins" `
  --add-data "projects;projects" `
  server/main.py
```

- Excluir dependencias de desarrollo (pytest, etc.) via `--exclude-module`.
- El directorio `dist/ShowDesigner/` contiene el ejecutable + todas las DLLs.
- **Inno Setup** (si disponible) para empaquetar en un `ShowDesigner_setup.exe`.
  Script `.iss` incluido en el repo.

`scripts/build_installer.ps1` — script de build reproducible:
1. `npm run build` en `web/` → genera `web/dist/`.
2. `pyinstaller showdesigner.spec`.
3. Opcionalmente: `iscc ShowDesigner.iss`.

`Luces.bat` actualizado para detectar si está corriendo desde PyInstaller (`sys.frozen`)
o desde venv, y elegir el comando correcto.

### Limitaciones documentadas

- `sounddevice` requiere VC++ Redistributable (incluir en el instalador o documentar).
- `librosa` → `llvmlite` puede ser pesado (~100 MB extra). Documentar.
- El instalador NO incluye FFmpeg (E3 lo detecta via PATH).

### Tests

`tests/test_build.py` (opcional, solo correr en CI con Windows):
- El spec de PyInstaller no tiene errores de import (`python -m PyInstaller --dry-run`).
- `build_installer.ps1` completa sin errores en una máquina limpia.

**Aceptación**: instalo desde el `.exe` en una máquina sin Python → abro `Luces.bat` →
el server arranca → la web funciona en `:8000`.
**Commit**: `roadmap-v3 fase H2: instalador Windows`.

---

## H3 — Multi-show en vivo: quick-switch entre proyectos (~2 días, Sonnet)

**Qué**: hoy cambiar de proyecto (`LUCES_PROJECT`) requiere reiniciar el server. En un
contexto de producción (varios artistas, misma noche, mismo rig) se necesita cargar otro
show sin perder la conexión del navegador.

### Backend

```python
# En ShowSession:
async def switch_project(self, new_slug: str) -> None:
    """Cambia el proyecto activo sin reiniciar el server.
    1. Para el autosave del proyecto actual.
    2. Guarda el estado actual (autosave inmediato).
    3. Carga el nuevo proyecto (timeline, audio, analysis).
    4. Resetea el playback a t=0.
    5. Emite 'project_changed' al stream con el nuevo nombre.
    """
```

- `audio_player.stop()` → `audio_player.load(new_audio_path)` (HeadlessAudioPlayer ya
  soporta cambiar de archivo? Si no, reiniciarlo limpiamente).
- `baked_frames = None` (invalidar el render offline del proyecto anterior).
- Live engine: `live_stop_all()` antes del cambio para no dejar slots huérfanos.
- Handler `switch_project(slug: str)` + `list_projects()` (ya existe via project_manager).

### Frontend

- Selector de proyecto en el Topbar (dropdown, no solo en la ruta de arranque).
- Al cambiar: spinner "Cargando proyecto X…" mientras llega el evento `project_changed`.
- En `Live.tsx`: el `RenderPanel` se resetea al recibir `project_changed` (el render baked
  del proyecto anterior es inválido para el nuevo).
- Timeline: refetch completo de clips, patterns, cues al recibir `project_changed`.

### Tests

`tests/test_switch_project.py`:
- `switch_project` carga el show.json del nuevo slug.
- Los clips del proyecto anterior no aparecen después del switch.
- El live engine queda limpio (sin slots armados).
- `project_changed` se emite al stream.
- Switch a slug inexistente → error limpio (no deja la sesión en estado parcial).

**Aceptación**: con `el_taser` corriendo, hago switch a `himno_espana` desde el dropdown
del Topbar → en 2 s el timeline muestra los 10 clips de la bandera, el audio cambia, el
viewer 3D mantiene la conexión.
**Commit**: `roadmap-v3 fase H3: multi-show quick-switch`.

---

## H4 — Rendimiento a escala (~3 días, Sonnet)

**Qué**: el bench de referencia actual usa el_taser (1358 clips, 30 FPS). Documentar el
comportamiento a mayor escala y resolver los cuellos de botella que aparezcan.

**Invariante I5 actualizado para v3**: `compute_frame` p95 < 33 ms para 100 clips activos
simultáneos (sin cambios desde v2). **Nuevo objetivo v3**: el timeline puede tener hasta
5000 clips sin que la carga/save/refetch se sienta lenta (< 500 ms para cada operación).

### Trabajo concreto

1. **Bench de carga**: `tests/test_bench_scale.py` — crear show sintético de 5000 clips,
   medir `Timeline.to_dict()`, `Timeline.from_dict()`, `list_clips()` handler, envío del
   snapshot por WS. Falla si cualquiera supera 500 ms.

2. **Paginación de `list_clips`**: si hay > 1000 clips, el handler devuelve un cursor
   (`offset, limit`) en lugar de los N clips en un solo JSON (que puede ser 1 MB+).
   Frontend: cargar el viewport visible primero, resto lazy. Reutilizar el bucket index
   para saber qué clips están visibles en el scroll actual.

3. **Diff en `model_changed`**: en vez de re-fetchear TODOS los clips al mutar uno, el
   backend emite el diff mínimo (`{changed: [clip_dict], deleted: [uid]}`) y el frontend
   actualiza el store parcialmente. Generalizar el patrón optimista de I3 a nivel de
   protocolo. (Invariante I3 explicitado en el protocolo.)

4. **`compute_frame` profile con 200 clips activos**: si el p95 supera 60 ms, investigar y
   optimizar (candidatos: bucket index con muchos clips por bucket, GC de arrays temporales,
   postfx con muchas pistas).

5. **GC pressure**: añadir `tracemalloc` snapshot en el bench y verificar que el número de
   objetos no crece indefinidamente tras 100 frames (sin leaks visibles en el ciclo principal).

### Tests

`tests/test_bench_scale.py` (marcados con `@pytest.mark.bench`):
- 5000 clips: `to_dict` < 200 ms, `from_dict` < 200 ms.
- 5000 clips: `list_clips` (handler) < 500 ms.
- 200 clips activos: `compute_frame` p95 < 60 ms.
- Sin leaks: `tracemalloc` tras 100 iteraciones no crece > 1 MB.

**Aceptación**: cargo un show de 2000 clips en el timeline, el scroll es fluido (sin janks
de >100 ms al hacer scroll), añado un clip y el store se actualiza vía diff parcial (sin
refetch de los 2000).
**Commit**: `roadmap-v3 fase H4: rendimiento a escala`.

---

## Resumen de esfuerzo y orden recomendado

| # | Fase | Días | Modelo | Depende de |
|---|------|------|--------|-----------|
| 1 | E1 Cues profesional | 3 | Sonnet | — |
| 2 | E2 OSC in/out | 2 | Sonnet | E1 (go_cue via OSC) |
| 3 | E3 Export video preview | 2 | Haiku | B3 (render.npz) |
| 4 | E4 Test de output y patch | 2 | Sonnet | — |
| 5 | F1 10 efectos nuevos | 3 | Sonnet | — |
| 6 | F2 Plugin UI auto-generada | 2 | Sonnet | F1 (PARAM_SCHEMA en los nuevos) |
| 7 | F3 Presets curados | 1 | Haiku | F1, F2 |
| 8 | F4 Live preview en inspector | 2 | Sonnet | F2 (necesita Pillow) |
| 9 | G1 sACN | 2 | Sonnet | — |
| 10 | G2 Ableton Link / MIDI Clock | 2 | Sonnet | D2 (patrón BPM) |
| 11 | G3 Moving heads pan/tilt | 3 | Opus | A2 (curvas para pan/tilt) |
| 12 | G4 DMX USB | 2 | Haiku | — |
| 13 | H1 SDK plugins | 2 | Sonnet | F2 (PARAM_SCHEMA) |
| 14 | H2 Instalador Windows | 2 | Haiku | — |
| 15 | H3 Multi-show quick-switch | 2 | Sonnet | B4 (autosave antes del switch) |
| 16 | H4 Rendimiento a escala | 3 | Sonnet | — |

**Total ≈ 35 días** de trabajo efectivo.

### Carriles de quick-wins (empezar aquí si hay tiempo limitado)

- **E4 + F1**: en 5 días el operador tiene identify + test de universo + un banco de efectos
  decente. Valor inmediato para el bolo.
- **F2 + F3**: en 3 días el ClipInspector es profesional. Sin backend nuevo.
- **G1**: en 2 días se añade un protocolo completo. Receta cerrada, riesgo bajo.

### Hitos de demo

- Tras E1+E2: "opero el show desde QLab/TouchOSC con GO de verdad".
- Tras F1+F2: "el banco de efectos tiene personalidad propia".
- Tras G3: "los movers siguen el beat sin tocar nada".
- Tras H3: "cambio de show entre artistas en 2 s, sin reiniciar nada".

---

## Asignación de modelos por fase

Mismos criterios que v2 (riesgo × ambigüedad determina el modelo):

| Fase | Modelo | Por qué |
|------|--------|---------|
| E1 Cues | Sonnet | Bien especificado; crossfade reutiliza A2 lanes |
| E2 OSC | Sonnet | Receta cerrada; la librería python-osc es simple |
| E3 Export video | **Haiku** | Bucketing + Pillow/ffmpeg; aceptación clara |
| E4 Test output | Sonnet | Estado efímero + UI patch; sin semántica sutil |
| F1 10 efectos | Sonnet | Cada efecto es independiente; matemática conocida |
| F2 Plugin UI | Sonnet | Frontend + schema; sin concurrencia |
| F3 Presets | **Haiku** | Datos curados; lógica mínima |
| F4 Live preview | Sonnet | Handler sync + debounce en UI |
| G1 sACN | Sonnet | Protocolo bien documentado; mock de librería |
| G2 Link/MIDI | Sonnet | Threading + BPM; el patrón viene de D2 |
| G3 Moving heads | **Opus** | Semántica de mezcla de canales; ADR necesario |
| G4 DMX USB | **Haiku** | Protocolo serie simple; mock de pyserial |
| H1 SDK | Sonnet | Documentación + harness; sin semántica nueva |
| H2 Instalador | **Haiku** | Script de build; sin lógica de negocio |
| H3 Multi-show | Sonnet | Estado session + transición limpia |
| H4 Escala | Sonnet | Profiling + optimización guiada por medidas |

Reparto: Opus 1 fase (~3 días), Sonnet 10 fases (~24 días), Haiku 5 fases (~11 días).
Frente a "todo con Sonnet", el ahorro estimado en tokens es del ~25%.

---

## Convenciones adicionales v3

1. **Schema v4**: E1 añade `cue_list` → subir `version` de 3 a 4. Migración en
   `Timeline.load()`. Las demás fases de v3 que añaden campos los declaran con defaults
   tolerantes (sin nueva versión de schema).

2. **ADR-004**: G3 (mixing policy de channel effects). Plantilla en `docs/adr/`.

3. **Plugin SDK**: `docs/dev/plugin-sdk.md` es el documento público de referencia. Toda
   feature de F que cambie el contrato del plugin (PARAM_SCHEMA, shape, etc.) actualiza
   este documento EN EL MISMO COMMIT.

4. **Protocolo diff**: H4 introduce `{changed, deleted}` en el stream. Documentar en
   `docs/dev/handlers.md` como `model_changed_v2` (backwards-compat: mantener también el
   evento `model_changed` sin diff para clientes legacy como el MCP bridge).

---

## Checklist de cierre de CADA fase (heredado de ROADMAP.md §Checklist)

```
[ ] Suite pytest verde (sin saltarse tests)
[ ] Tests nuevos del módulo escritos y pasando
[ ] Test de parity si la fase toca el camino del frame
[ ] npx tsc --noEmit limpio + cd web && npm run build (si toca web)
[ ] show.json viejo carga sin pérdida (si toca persistencia)
[ ] Sin imports prohibidos (core no importa server/web/fastapi)
[ ] Handlers nuevos documentados en docs/dev/handlers.md
[ ] ROADMAP_v3.md: fase marcada APLICADA con fecha y notas
[ ] CLAUDE.md actualizado si cambia arquitectura o comandos
[ ] plugin-sdk.md actualizado si cambia el contrato de plugin (F, H1)
[ ] Un commit con mensaje "roadmap-v3 fase <ID>: <resumen>"
[ ] Probado A MANO el criterio de aceptación (no solo los tests)
```
