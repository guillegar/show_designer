"""
plugin_template.py — Plantilla para crear un efecto pixel custom (SDK H1).

Copia este archivo como plugins/effects/mi_efecto.py, cambia los campos marcados
con "# CAMBIAR", implementa render(), y reinicia el server.

Más info: docs/dev/plugin-sdk.md
"""
import numpy as np
from typing import ClassVar, Dict, Any

from src.core.effects_engine import Effect, EffectScope, LEDS_PER_BAR


class TemplateEffect(Effect):
    # ── Metadatos del efecto ─────────────────────────────────────
    name        = "template_effect"      # CAMBIAR: slug único snake_case
    family      = "custom"              # CAMBIAR: "color", "movement", "rhythm", etc.
    duration_ms = 2000                  # CAMBIAR: duración de un ciclo completo (ms)
    scope       = EffectScope.PER_BAR   # PER_BAR → (1,93,3)  |  ALL_BARS → (10,93,3)
    description = "Efecto de plantilla" # CAMBIAR: descripción breve

    # ── Parámetros de la UI (PARAM_SCHEMA — F2) ──────────────────
    # La UI auto-genera controles para cada entrada.
    # Quita los que no necesites; añade los tuyos siguiendo el mismo formato.
    PARAM_SCHEMA: ClassVar[Dict[str, dict]] = {
        "speed": {
            "type": "float", "min": 0.1, "max": 5.0, "step": 0.1,
            "default": 1.0, "label": "Velocidad", "unit": "ciclos/s",
        },
        # Color RGB — la UI los agrupa en un color picker automáticamente
        "r": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 255, "label": "Rojo"},
        "g": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 0,   "label": "Verde"},
        "b": {"type": "int", "min": 0, "max": 255, "step": 1, "default": 128, "label": "Azul"},
        # Ejemplo de enum
        "mode": {
            "type": "enum", "options": ["fade", "flash", "solid"],
            "default": "fade", "label": "Modo",
        },
    }

    # ── Render ────────────────────────────────────────────────────
    def render(
        self,
        elapsed_time: float,         # ms desde el inicio del clip
        bars_state: np.ndarray,      # (10,93,3) uint8 — frame anterior (solo lectura)
        audio_context: Dict[str, Any],  # {"rms", "energy", "bpm", "norm": {...}}
        **params
    ) -> np.ndarray:
        """Devuelve un frame RGB según el scope:
          - PER_BAR  → (1, 93, 3) uint8
          - ALL_BARS → (10, 93, 3) uint8
        """
        t = elapsed_time / 1000.0              # convierte ms → segundos
        speed = float(params.get("speed", 1.0))
        r = int(params.get("r", 255))
        g = int(params.get("g", 0))
        b = int(params.get("b", 128))

        # CAMBIAR: implementa tu lógica aquí
        # Ejemplo: barra que pulsa con el tiempo
        brightness = (np.sin(2 * np.pi * speed * t) * 0.5 + 0.5)  # 0..1
        out = np.zeros((1, LEDS_PER_BAR, 3), dtype=np.uint8)
        out[0, :, 0] = int(r * brightness)
        out[0, :, 1] = int(g * brightness)
        out[0, :, 2] = int(b * brightness)
        return out


# ── Registro del plugin ───────────────────────────────────────────────────────
# El loader detecta este dict al arrancar. Usa IDs >= 1000; los <1000 son del core.
# CAMBIAR: elige un ID libre (mira plugins/effects/ para ver cuáles están en uso).
PLUGIN_EFFECTS = {
    2000: TemplateEffect(),
}
