# Contribuir a Show Designer Pro

¡Gracias por tu interés en contribuir! Este documento te guía en el proceso.

## Código de conducta

Sé respetuoso y constructivo. Este es un proyecto abierto para todos.

## Cómo reportar bugs

1. **Busca si el bug ya existe** en [Issues](https://github.com/guillegar/show_designer/issues)
2. **Abre un issue nuevo** con:
   - Título claro: `[BUG] Descripción breve`
   - Versión de Python y OS
   - Pasos para reproducir
   - Comportamiento esperado vs. actual
   - Logs/capturas si aplica

## Cómo proponer features

1. **Abre una Discussion** (no Issue) si es una idea grande
2. **Describe el problema que resuelve**
3. **Sugiere una solución** (no es obligatoria)
4. El autor decidirá si es in-scope

## Cómo hacer pull requests

### Antes de empezar

- Clona el repo: `git clone https://github.com/guillegar/show_designer.git`
- Crea una rama: `git checkout -b feature/mi-feature` o `git checkout -b fix/mi-bug`
- Instala dependencias: `pip install -r requirements.txt`

### Durante el desarrollo

- **Tests**: asegúrate de que `pytest tests/ -v` pase (363 tests)
- **Cobertura**: target mínimo 60%, ideal 92%+ (run con `pytest --cov`)
- **Formato**: sin formatters configurados, pero:
  - Máximo 120 caracteres por línea
  - Sin imports muertos
  - Docstrings solo donde sea no-obvio
- **Commits**: mensajes claros, ej. `Fix: builder crashes on empty section`

### Pull request

1. **Push a tu rama**: `git push origin feature/mi-feature`
2. **Abre PR en GitHub** con:
   - Título: `[FEATURE]` o `[FIX]` + descripción breve
   - Descripción: qué cambia y por qué
   - Tests: menciona si hay tests nuevos
   - Links: referencia a issues relacionados (`Closes #123`)
3. **Espera review** del autor
4. **Responde feedback** en los comentarios

## Estructura de tests

```powershell
# Todos los tests
pytest tests/ -v

# Un archivo
pytest tests/test_timeline_model.py -v

# Con cobertura
pytest tests/ --cov=src --cov-report=html
```

Tests nuevos deben:
- Estar en `tests/test_*.py`
- Usar fixtures en `conftest.py`
- Incluir docstring breve
- Tener un assert claro

## Decisiones arquitectónicas

Cambios grandes (que afecten a múltiples módulos):
- Documenta en el PR: por qué y qué se gana
- Sé consciente de acoplamientos (lee `CLAUDE.md` sección "Decisiones tomadas")
- Prueba en el visualizador 3D y en los tests

## Release workflow (solo author)

1. **Finaliza la feature** (tests verdes, PR merged)
2. **Crea versión checkpoint** en `versions/vX.Y_pN_xxx/` con:
   - Snapshot de archivos críticos
   - `CHANGELOG.md` detallado
   - SHA-256 de archivos clave
   - Comando de rollback
3. **Taguea en git**: `git tag v1.9-F2`
4. **Pushea**: `git push origin --tags`

## Preguntas?

- Lee [CLAUDE.md](CLAUDE.md) para arquitectura profunda
- Lee [STRUCTURE.md](STRUCTURE.md) para organización del código
- Abre una [Discussion](https://github.com/guillegar/show_designer/discussions)

---

**¡Gracias por contribuir a Show Designer Pro!** 🎨✨
