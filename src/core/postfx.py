"""
postfx.py — Cadena de post-procesado: pista + master (Fase B2, ROADMAP v2).

Puro numpy, sin imports de red/UI/proyecto (invariante I4: vectorizado, cero
bucles Python por LED).

Orden canónico en compute_frame:
    timeline_render → [capa live C1] → apply_track_chain × pista → apply_master

Parámetros de chain:
    brightness  0..1      (1 = sin cambio)
    gamma       0.5..2.2  (1 = sin cambio; <1 oscurece sombras, >1 aclara)
    hue_shift   -180..180 (0 = sin cambio; gira el hue en grados)
    white_limit 0..1      (1 = sin límite; <1 recorta blancos)

El master añade:
    blackout_fade 0..1    (1 = paso libre; 0 = negro total; animable con A2)

Parity invariante: brightness=1, gamma=1, hue_shift=0, white_limit=1
                   → frame byte-exacto al original (fast path, cero alloc).
"""
from __future__ import annotations

import numpy as np

# ── Funciones públicas ────────────────────────────────────────────────────────

def apply_track_chain(frame_bar: np.ndarray, chain: dict) -> np.ndarray:
    """Aplica la cadena de post-procesado a UNA barra (shape LEDS×3 uint8).

    chain = {brightness, gamma, hue_shift, white_limit} — todos opcionales.
    Fast path: parámetros identidad → devuelve frame_bar sin copiar (I4).
    """
    brightness = float(chain.get('brightness', 1.0))
    gamma      = float(chain.get('gamma', 1.0))
    hue_shift  = float(chain.get('hue_shift', 0.0))
    white_limit = float(chain.get('white_limit', 1.0))

    if brightness == 1.0 and gamma == 1.0 and hue_shift == 0.0 and white_limit == 1.0:
        return frame_bar

    f = frame_bar.astype(np.float32) * (1.0 / 255.0)
    f = _apply_chain_ops(f, brightness, gamma, hue_shift, white_limit)
    return (np.clip(f, 0.0, 1.0) * 255.0).astype(np.uint8)


def apply_master(frame: np.ndarray, master: dict) -> np.ndarray:
    """Aplica brightness/gamma/hue_shift/white_limit + blackout_fade al frame
    completo (shape NUM_BARS×LEDS×3 uint8).

    blackout_fade=0 → negro total; blackout_fade=1 → paso libre.
    Fast path cuando todos los parámetros son identidad.
    """
    blackout_fade = float(master.get('blackout_fade', 1.0))
    brightness    = float(master.get('brightness', 1.0))
    gamma         = float(master.get('gamma', 1.0))
    hue_shift     = float(master.get('hue_shift', 0.0))
    white_limit   = float(master.get('white_limit', 1.0))

    if (blackout_fade == 1.0 and brightness == 1.0 and gamma == 1.0
            and hue_shift == 0.0 and white_limit == 1.0):
        return frame

    f = frame.astype(np.float32) * (1.0 / 255.0)
    f = _apply_chain_ops(f, brightness, gamma, hue_shift, white_limit)
    if blackout_fade != 1.0:
        f = f * blackout_fade
    return (np.clip(f, 0.0, 1.0) * 255.0).astype(np.uint8)


# ── Internos ────────────────────────────────────────────────────────────────

def _apply_chain_ops(f: np.ndarray,
                     brightness: float, gamma: float,
                     hue_shift: float, white_limit: float) -> np.ndarray:
    """Aplica brightness, gamma, hue_shift y white_limit sobre float32 [0..1].

    Compartido por apply_track_chain y apply_master.
    """
    if brightness != 1.0:
        f = f * brightness

    if gamma != 1.0:
        f = np.power(np.clip(f, 0.0, 1.0), 1.0 / gamma)

    if hue_shift != 0.0:
        f = _shift_hue(f, hue_shift)

    if white_limit != 1.0:
        f = np.clip(f, 0.0, white_limit)

    return f


def _shift_hue(f: np.ndarray, degrees: float) -> np.ndarray:
    """Rota el hue en grados sobre un array float32 [0..1] de cualquier shape.

    Totalmente vectorizado: RGB → HSV → shift H → RGB sin bucles Python por LED
    (invariante I4). Shape arbitraria preservada.
    """
    sh = f.shape
    flat = f.reshape(-1, 3)
    r, g, b = flat[:, 0], flat[:, 1], flat[:, 2]

    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin

    # Hue en [0..360) — evitar div/0 con safe_d
    safe_d = np.where(delta > 0, delta, 1.0)
    h = np.where(
        delta == 0, 0.0,
        np.where(
            cmax == r, 60.0 * (((g - b) / safe_d) % 6),
            np.where(
                cmax == g, 60.0 * ((b - r) / safe_d + 2.0),
                60.0 * ((r - g) / safe_d + 4.0),
            ),
        ),
    ) % 360.0

    s = np.where(cmax > 0, delta / cmax, 0.0).astype(np.float32)
    v = cmax.astype(np.float32)

    # Shift del hue
    h = (h + degrees) % 360.0

    # HSV → RGB (sectores sin bucles por pixel)
    h6      = (h / 60.0).astype(np.float32)
    i_sec   = h6.astype(np.int32) % 6
    ff      = (h6 - np.floor(h6)).astype(np.float32)
    p_v     = (v * (1.0 - s)).astype(np.float32)
    q_v     = (v * (1.0 - s * ff)).astype(np.float32)
    t_v     = (v * (1.0 - s * (1.0 - ff))).astype(np.float32)

    # Tabla sector → (R, G, B): apilada para indexar con i_sec
    # sector 0→(v,t,p) 1→(q,v,p) 2→(p,v,t) 3→(p,q,v) 4→(t,p,v) 5→(v,p,q)
    all_r = np.stack([v,   q_v, p_v, p_v, t_v, v  ])  # (6, N)
    all_g = np.stack([t_v, v,   v,   q_v, p_v, p_v])
    all_b = np.stack([p_v, p_v, t_v, v,   v,   q_v])

    n = len(flat)
    idx = np.arange(n)
    out = np.stack([all_r[i_sec, idx],
                    all_g[i_sec, idx],
                    all_b[i_sec, idx]], axis=-1)

    return np.clip(out, 0.0, 1.0).astype(np.float32).reshape(sh)
