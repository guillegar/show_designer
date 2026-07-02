# Profesionalización — log de pasos

Registro de las mejoras de madurez de ingeniería aplicadas (evaluación `/architecture`).
Cada paso: qué, por qué, resultado. Un commit por bloque.

Leyenda: ✅ hecho · 🟡 parcial (patrón establecido + resto documentado) · ⏳ pendiente

## P0 — Guardarraíles (tooling + CI)
- [x] **#1 `pyproject.toml`** — metadata + deps (core/dev/audio) + entry point + config ruff/mypy.
- [x] **#2 Ruff** — lint con línea 120; **1054 autofixes**; `ruff check` **verde**.
- [x] **#3 CI de Python** — `.github/workflows/python-ci.yml` (ruff bloqueante + mypy informativo).
- [x] **#4 pre-commit** — `.pre-commit-config.yaml` (ruff --fix + hygiene hooks).

## P1 — Salud del código
- [ ] **#8 mypy gradual** — config lenient, en CI (no bloqueante al principio).
- [ ] **#7 Dispatch async** — el WS handler ejecuta `dispatcher.handle` fuera del event loop.
- [ ] **#6 print → logger** — migración de los ~143 `print()` restantes (empezando por `server/`).
- [ ] **#5 Despiece de `dispatcher.py`** — patrón `handlers/` por dominio (establecer + documentar).

## P2 — Pulido y operabilidad
- [ ] **#9 Despiece de `Timeline.tsx`** — subcomponentes (establecer + documentar).
- [ ] **#10 Code-splitting frontend** — lazy-load de vistas pesadas.
- [ ] **#11 Higiene de config/secretos** — documentar `LUCES_*`; secretos de `output_targets.json`.
- [ ] **#12 Releases** — `CHANGELOG.md` + deploy MkDocs a GitHub Pages.
- [ ] **#13** — gitignorear `web/public/v3d/rig_layout.json` (generado).

---

## Bitácora

### 2026-07-01 · P0 — guardarraíles de tooling
- **#1** `pyproject.toml`: metadata, deps runtime (espejo de `requirements.txt`), extras `dev`
  (pytest, pytest-cov, pytest-asyncio, ruff, mypy) y `audio` (demucs); entry point
  `show-designer = server.main:main`; packaging `server`/`src`/`plugins`. `pip install -e .` OK.
- **#2** Ruff 0.15: config en pyproject (select E,F,I,W,UP,B; línea 120; ignores graduales +
  per-file para el bootstrap de `sys.path` y los probes de deps opcionales). `ruff check --fix`
  aplicó **1054 fixes** (orden/limpieza de imports) en ~100 ficheros; `ruff check` = **verde**.
- **#3** `python-ci.yml`: job lint (ruff bloqueante + `mypy || true`). Los tests aún NO corren en CI
  (dependen de audio/proyectos locales no versionados) → pendiente: fixtures sintéticos.
- **#4** `.pre-commit-config.yaml`: ruff `--fix` + trailing-whitespace/EOF/yaml/json/large-files.
- **Deuda saldada:** los **17 tests pre-existentes en rojo** → **verde**. `pytest-asyncio`
  (+ `asyncio_mode=auto`) arregla 10 async; `Pillow` arregla 6 de PIL; el bench
  `test_bench_compute_frame_…` (faltaba `session._recording` al construir la sesión con
  `object.__new__`) arregla 1. **Suite completa: 1063 tests, 0 fallos.**
- **mypy baseline:** 95 errores en 17 ficheros (gradual, no bloqueante) — deuda a reducir.

