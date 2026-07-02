# ADR-005: Despiece de `dispatcher.py` en `server/handlers/` por dominio

**Status:** Accepted
**Date:** 2026-07-01
**Deciders:** Guille (owner)

## Context

`server/dispatcher.py` alcanzó **~4.5k líneas con 145 handlers** en ~40 secciones (una por fase
del roadmap). Añadir un handler exige navegar un monolito; los helpers de cada dominio conviven
con los de todos los demás. Restricciones: (1) NO cambiar la API JSON-RPC (la web y el compat MCP
:9876 dependen de los mismos nombres); (2) muchos tests importan `_h_*` **directamente desde
`server.dispatcher`**; (3) los 1063 tests deben seguir verdes en cada paso.

## Decision

Patrón **strangler**: paquete `server/handlers/` con un módulo por dominio. Cada módulo define sus
`_h_*` + helpers privados y termina con `HANDLERS = {nombre: fn}` (+ sets `TIMELINE_MUTATORS`/
`RIG_MUTATORS` locales — la declaración de mutador vive junto al handler). `dispatcher.py` llama a
`handlers.load_all()`, mergea `LOCAL` en `_LOCAL` y **re-exporta los nombres movidos** (compat con
tests/web). La migración es **incremental**: se mueven dominios cohesivos de uno en uno, corriendo
la suite tras cada movimiento.

## Options Considered

### Option A: Strangler por dominios con registro dict + re-exports (elegida)
| Dimension | Assessment |
|-----------|------------|
| Complejidad | Baja por paso (mover bloque + registro) |
| Riesgo | Bajo — API y nombres import-compatibles; tests tras cada paso |
| Resultado | dispatcher queda como fachada (auth, undo-snapshot, gesture-log, dispatch) |

**Pros:** cero breaking changes; commits pequeños verificables; el patrón dict ya es el del código.
**Cons:** convivencia temporal de dominios movidos y sin mover; re-exports de compat hasta migrar tests.

### Option B: Big-bang (mover los 145 de golpe)
**Pros:** estado final inmediato. **Cons:** diff gigante imposible de revisar; alto riesgo de romper
imports de tests; contradice "checkpoints = git, un commit por fase".

### Option C: Clase Dispatcher con métodos por dominio (mixins)
**Pros:** todo en objetos. **Cons:** cambia la forma de registrar/llamar handlers (hoy funciones
puras `f(session, params)` — también las consume el bridge); más churn sin beneficio claro.

## Consequences

- Más fácil: localizar/añadir handlers por dominio; tests por módulo; revisar diffs.
- Más difícil (temporal): saber si un handler ya migró (mitigado: `_LOCAL` mergea y la fachada
  re-exporta; `grep` del nombre funciona igual).
- Revisitar: cuando todos los dominios migren, `_LOCAL` queda solo con handlers "core" (clips/
  undo/transport) y los re-exports podrán retirarse actualizando los imports de los tests.

## Action Items
1. [x] Infra: `server/handlers/__init__.py` (registro + `load_all()` + decorador para nuevos).
2. [x] Mover dominio **waveform** (B1) → `handlers/waveform.py`.
3. [x] Mover dominio **proyectos** (galería/componentes/crear/copiar) → `handlers/projects.py`.
4. [x] Mover dominio **patch/fixture editor** (v4 + Patch UX) → `handlers/patch.py`.
5. [x] Tanda 2 (2026-07-01): **live** (C1+C2+I1), **markers** (I2+I3), **autovj** (D1+D2),
   **cues** (E1).
6. [x] Tanda 3 (2026-07-01): **mixer**, **render_export** (B3+E3+I5+export csv/qlc), **autosave**,
   **osc**, **movers** (G3+G4), **switch** (H3), **tempo** (G2+M1). Incluye el FIX de los paths
   `Path(__file__).parent.parent` rotos por el movimiento (anclados a `PROJECT_DIR`).
7. [x] Tanda 4 (2026-07-01): **patch_visual** (J1+J2), **gdtf** (J3), **output_test** (E4+J4 +
   strays del rango K2), **webhooks_config** (L2), **viewer3d** (K1), **pixelmap** (K2),
   **showgen** (M2+M3), **bundle_market** (N1+N2). `load_all()` pasa a **autodescubrimiento**
   (pkgutil) — la lista hardcodeada se quedó obsoleta en silencio y costó 14 tests.
8. [x] Tanda 5 (2026-07-01): **clips_edit** (efecto/preset/duplicar/partir + A5 rangos + A4
   micro-eventos), **feedback**, **presets**, **automation** (A2+A1), **patterns** (A3).
   **SPLIT COMPLETO**: `dispatcher.py` = **508 líneas no vacías (−89% desde 4517)** — fachada
   pura: transporte/undo/list_clips/schema/preview + auth + gesture-log + dispatch + merge.
9. [x] **Decisión sobre los re-exports de compat (item 7 original): SE QUEDAN.** Son la superficie
   estable que importan ~15 ficheros de tests (`from server.dispatcher import _h_*`); retirarlos
   sería churn puro en tests sin ganancia de comportamiento. Regla para código nuevo: importar
   SIEMPRE de `server.handlers.<dominio>`; los re-exports son solo compat de tests legacy.

## Lecciones del proceso (para futuros splits)
- La **posición física** manda sobre el comentario de sección: aparecieron 5 handlers "strays"
  (pan_tilt, toggle_baked, test_universe, blackout, get_output_status, list_clips) fuera de su
  sección lógica.
- `Path(__file__).parent.parent` se rompe al mover código a otra profundidad → anclar SIEMPRE a
  `src._paths.PROJECT_DIR`.
- Cortes por marcador de texto: **top-down** (el marcador final de un corte es el inicial del
  siguiente).
- Los `mock.patch("server.dispatcher.X")` de los tests deben apuntar al módulo NUEVO donde se usa
  el símbolo (pasó con `Path` de OSC, `_get_artnet_ip_for_universe`, `_ensure_waveform_cached`).
- Registro por **autodescubrimiento** > lista mantenida a mano.
