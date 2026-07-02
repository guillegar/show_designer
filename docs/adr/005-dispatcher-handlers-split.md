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
5. [ ] Resto de dominios (cues, live, autovj, markers, mixer, export, …) — incremental, un commit
   por dominio, suite verde tras cada uno.
6. [ ] Al terminar: retirar re-exports de compat y actualizar imports de tests.
