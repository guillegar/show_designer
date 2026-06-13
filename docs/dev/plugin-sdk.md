# Plugin SDK — Show Designer Pro

Guía para crear efectos pixel custom sin tocar el core.

## Estructura mínima

```python
# plugins/effects/my_effect.py
import numpy as np
from typing import ClassVar, Dict, Any
from src.core.effects_engine import Effect, EffectScope, LEDS_PER_BAR

class MyEffect(Effect):
    name        = "my_effect"       # slug único (snake_case)
    family      = "custom"
    duration_ms = 2000
    scope       = EffectScope.PER_BAR
    description = "Breve descripción del efecto"

    PARAM_SCHEMA: ClassVar[Dict[str, dict]] = {
        "speed": {
            "type": "float", "min": 0.1, "max": 5.0, "step": 0.1,
            "default": 1.0, "label": "Velocidad", "unit": "ciclos/s",
        },
        "r": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 255, "label": "Rojo"},
        "g": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 0,   "label": "Verde"},
        "b": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 128, "label": "Azul"},
    }

    def render(self, elapsed_time: float, bars_state: np.ndarray,
               audio_context: Dict[str, Any], **params) -> np.ndarray:
        # elapsed_time : ms desde el inicio del clip
        # bars_state   : (NUM_BARS, 93, 3) uint8 — frame anterior
        # audio_context: dict con actx['norm'] etc.
        # params       : valores actuales (ya modulados por A1/A2/C2)
        t = elapsed_time / 1000.0
        speed = float(params.get("speed", 1.0))
        r = int(params.get("r", 255))
        g = int(params.get("g", 0))
        b = int(params.get("b", 128))

        out = np.zeros((1, LEDS_PER_BAR, 3), dtype=np.uint8)
        # ... tu render aquí ...
        return out

PLUGIN_EFFECTS = {
    2000: MyEffect(),   # IDs >= 1000; elige uno libre
}
```

## PARAM_SCHEMA — tipos y campos

| Campo     | Obligatorio | Descripción |
|-----------|-------------|-------------|
| `type`    | ✓           | `"float"`, `"int"`, `"bool"`, `"enum"` |
| `label`   | recomendado | Texto que muestra la UI |
| `default` | recomendado | Valor por defecto |
| `min`     | float/int   | Mínimo inclusive |
| `max`     | float/int   | Máximo inclusive |
| `step`    | float/int   | Paso del slider |
| `options` | enum        | Lista de strings válidos |
| `unit`    | opcional    | Unidad mostrada junto al valor (ej. `"Hz"`, `"px"`) |

### Tipos de control generados

- **`float` / `int`** → `<input type="range">` + campo numérico editable + unidad.
- **`bool`** → toggle checkbox.
- **`enum`** → `<select>` con las opciones.
- **Sin schema** → `<input type="text">` genérico (sin regresión para efectos legacy).

### Convención de color

La UI detecta automáticamente grupos de componentes RGB y los agrupa en un color picker:

| Claves en schema       | Color picker mostrado |
|------------------------|-----------------------|
| `r`, `g`, `b`          | "Color"               |
| `color1_r/g/b`         | "Color 1"             |
| `color2_r/g/b`         | "Color 2"             |
| `r_low/g_low/b_low`    | "Color bajo"          |
| `r_high/g_high/b_high` | "Color alto"          |
| `hue_r/g/b`            | "Tono"                |

Cada componente debe definirse como `type="int"` con `min=0`, `max=255`.

Ejemplo para un efecto con un solo color:
```python
PARAM_SCHEMA = {
    "r": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 255, "label": "Rojo"},
    "g": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 255, "label": "Verde"},
    "b": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 255, "label": "Azul"},
}
```

## Reglas del contrato

1. **Shape de salida**:
   - `PER_BAR` → `(1, 93, 3)` uint8
   - `ALL_BARS` / `GLOBAL` → `(10, 93, 3)` uint8

2. **Sin efectos secundarios en `render()`**: no modificar `bars_state` ni estado global.
   La excepción justificada son los efectos con estado causal (fuego, VU meter) que
   documentan explícitamente el trade-off.

3. **IDs en rango ≥ 1000**: los IDs 0-999 están reservados para efectos base del core.

4. **PARAM_SCHEMA = {}** en la base → compatibilidad: la UI muestra inputs genéricos,
   la validación de `validate_params_against_schema` pasa sin error.

## Validación automática

Al asignar un preset o al llamar `set_clip_effect` con params, el backend llama
`validate_params_against_schema(params, PARAM_SCHEMA)` y devuelve un error si algún
valor está fuera de rango o no es una opción válida. No es necesario validar en `render()`.

## Cargar el plugin

Coloca el archivo `.py` en `plugins/effects/`. El loader lo detecta al arrancar.
No se requiere ninguna otra configuración.

## Testear con el harness

El harness (`tests/plugin_test_harness.py`) verifica automáticamente que tu efecto cumple el contrato:

```python
# En tu test o en el REPL
from tests.plugin_test_harness import assert_valid_plugin_effect
from plugins.effects.mi_efecto import MyEffect

assert_valid_plugin_effect(MyEffect())  # lanza AssertionError si algo falla
```

Qué comprueba el harness:
- Shape y dtype correctos en t=0, 500, 1000 ms.
- Valores en [0, 255].
- No muta `bars_state` (invariante de pureza).
- `PARAM_SCHEMA` coherente: tipos válidos, default dentro de [min, max], enum con options.

Tests de ejemplo en `tests/test_sdk_harness.py`.

## Punto de partida

Copia `plugins/effects/plugin_template.py` como base — tiene comentarios en cada campo
explicando las convenciones. El template pasa el harness de serie.
