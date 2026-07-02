"""
legacy_show.py — Configuración y render hard-codeados de "El Taser de Mamá Remix"
(ANALYSIS hallazgo 10). Extraído de `show_engine.py` para que el CORE no tenga
defaults específicos de una canción/rig.

Contiene:
  - BARS              : IPs estáticas + universos Art-Net del rig de 10 barras WLED.
  - _beat_env         : envelope de beat (helper exclusivo de render_stub).
  - render_stub       : renderer per-LED en Python puro con el mapa de secciones de
                        El Taser. Es el PATH LEGACY (use_effects=False); el path
                        actual es numpy (effects_engine). Se mantiene como fallback.
  - SECTION_RENDERERS : lista de renderers por sección.

`ShowEngine` lo importa de forma perezosa (en __init__ / send_artnet) para evitar
el import circular, ya que aquí se importan primitivas del propio show_engine.
"""
import math

from src.core.show_engine import LEDS, NUM_BARS, hsv

BARS = [
    # 10 barras WLED — IPs estáticas + universes Art-Net contiguos (1-10)
    # Las 7 originales:
    ('192.168.1.201', 1), ('192.168.1.202', 2), ('192.168.1.203', 3),
    ('192.168.1.204', 4), ('192.168.1.205', 5), ('192.168.1.206', 6),
    ('192.168.1.207', 7),
    # 3 nuevas, todas con IP estática + gateway/subnet correctos:
    ('192.168.1.208', 8),
    ('192.168.1.209', 9),
    ('192.168.1.210', 10),
]


def _beat_env(t, state, decay=0.12):
    """Envelope de beat: 1.0 justo en el beat, decae a 0 en `decay` segundos."""
    if state.beatmap and state.beatmap.n > 0:
        idx = state.beatmap.beat_at(t)
        if idx >= 0:
            dt = state.beatmap.time_in_beat(t, idx)
            return max(0.0, 1.0 - dt / decay)
    return 0.0


def render_stub(t, bar_idx, state, rms_val, flux_val, bpm_norm=1.0):
    """
    Show LA SANTA 0-65s — 5 efectos, beat-synced + tempo-adaptive.

    bpm_norm: factor de tempo local (1.0 = 136 BPM base).
              Cuando la cancion se acelera, bpm_norm > 1 y todas las
              velocidades de animacion escalan proporcionalmente.

    E1  0-13s : PULSO VIOLETA    — onda violeta con flash en cada beat
    E2 13-26s : CHASE BEATS      — spotlight salta de barra en barra en cada beat
    E3 26-39s : LASERES ROJO/BLANCO — barras alternas con haces escaneando
    E4 39-52s : FLASH AZUL BEAT  — explosion azul en cada beat
    E5 52-65s : FINALE STROBE    — rojo/blanco invierten en cada beat
    """
    rgb       = bytearray(LEDS * 3)
    flux_norm = min(1.0, flux_val)
    beat_e    = _beat_env(t, state, decay=0.12)
    beat_slow = _beat_env(t, state, decay=0.25)
    spd       = bpm_norm          # factor de velocidad: >1 = mas rapido

    # Mapeo seccion → efecto (adaptado a El Taser de Mama Remix, 8 secciones)
    # Sec 0  (0-52s)   : E1 pulso violeta (intro largo)
    # Sec 1  (52-76s)  : E2 chase beats
    # Sec 2  (76-86s)  : E3 laseres rojo/blanco (corto intenso)
    # Sec 3  (86-183s) : E3 laseres rojo/blanco (cuerpo principal)
    # Sec 4  (183-193s): E2 chase beats (transicion)
    # Sec 5  (193-213s): E4 flash azul
    # Sec 6  (213-218s): E5 strobe (muy corto, intenso)
    # Sec 7  (218-273s): E5 finale
    _sec = state.section_at(t)
    _sec_map = {0: 1, 1: 2, 2: 3, 3: 3, 4: 2, 5: 4, 6: 5, 7: 5}
    seg = _sec_map.get(_sec, 1)

    # ------------------------------------------------------------------ #
    # E1 — PULSO VIOLETA  (0-13s)                                        #
    # ------------------------------------------------------------------ #
    if seg == 1:
        hue      = (0.73 + (bar_idx - NUM_BARS/2.0) * 0.013) % 1.0
        wave_spd = (1.2 + rms_val * 1.5) * spd          # escala con tempo
        bar_ph   = bar_idx * (math.pi * 2.0 / NUM_BARS)
        base_int = 0.15 + rms_val * 0.40 + beat_slow * 0.45
        for led in range(LEDS):
            w   = math.sin((led / LEDS) * math.pi * 3 + t * wave_spd + bar_ph)
            ins = max(0.0, min(1.0, base_int * (1.0 + w * 0.30)))
            r, g, b = hsv(hue, 1.0, ins)
            i = led * 3;  rgb[i] = r;  rgb[i+1] = g;  rgb[i+2] = b

    # ------------------------------------------------------------------ #
    # E2 — CHASE BEATS  (13-26s)                                         #
    # ------------------------------------------------------------------ #
    elif seg == 2:
        beat_idx   = state.beatmap.beat_at(t) if state.beatmap else 0
        active_bar = beat_idx % NUM_BARS if beat_idx >= 0 else 0
        prev_bar   = (active_bar - 1) % NUM_BARS
        is_active  = (bar_idx == active_bar)
        is_prev    = (bar_idx == prev_bar)

        # Onda en la barra activa se mueve mas rapido cuando hay mas tempo
        wave_spd = (2.0 + rms_val * 2.0) * spd
        bar_ph   = bar_idx * 0.8

        for led in range(LEDS):
            w = math.sin((led / LEDS) * math.pi * 4 + t * wave_spd + bar_ph)
            wf = 0.8 + w * 0.2
            if is_active:
                bright = (0.50 + beat_e * 0.50) * wf
                r, g, b_v = int(bright*255), int(bright*255), int(bright*255)
            elif is_prev:
                bright = beat_slow * 0.50 * wf
                r, g, b_v = int(bright*255), 0, 0
            else:
                r, g, b_v = int(rms_val * 30), 0, 0
            i = led * 3;  rgb[i] = r;  rgb[i+1] = g;  rgb[i+2] = b_v

    # ------------------------------------------------------------------ #
    # E3 — LASERES ROJO / BLANCO  (26-39s)                               #
    # ------------------------------------------------------------------ #
    elif seg == 3:
        # El chase rojo/blanco se acelera con el tempo
        chase_freq  = 2.16 * spd
        chase_phase = int(t * chase_freq + bar_idx) % 2
        is_red = (chase_phase == 0)

        bg        = 0.04 + rms_val * 0.05
        peak_bri  = 0.65 + rms_val * 0.15 + beat_e   * 0.35
        peak_bri2 = 0.20 + rms_val * 0.10 + beat_slow * 0.15
        bw1 = 3.5 + beat_e * 18.0
        bw2 = 2.0 + beat_e *  9.0

        # Haces se mueven mas rapido cuando sube el tempo
        spd1 = (0.9 + rms_val * 2.5) * spd
        spd2 = (1.4 + rms_val * 1.8) * spd
        pos1 = (math.sin(t * spd1 + bar_idx * 1.1) * 0.5 + 0.5) * (LEDS - 1)
        pos2 = (math.sin(t * spd2 + bar_idx * 0.7 + math.pi) * 0.5 + 0.5) * (LEDS - 1)

        for led in range(LEDS):
            d1 = abs(led - pos1);  d2 = abs(led - pos2)
            b1 = max(0.0, (1.0 - d1/bw1) * peak_bri)  if d1 < bw1 else 0.0
            b2 = max(0.0, (1.0 - d2/bw2) * peak_bri2) if d2 < bw2 else 0.0
            bright = max(bg, min(1.0, b1 + b2))
            if is_red:
                r, g, b_v = int(bright*255), 0, 0
            else:
                r, g, b_v = int(bright*255), int(bright*235), int(bright*210)
            i = led * 3;  rgb[i] = r;  rgb[i+1] = g;  rgb[i+2] = b_v

    # ------------------------------------------------------------------ #
    # E4 — FLASH AZUL ELECTRICO  (39-52s)                                #
    # ------------------------------------------------------------------ #
    elif seg == 4:
        # Onda interna mas rapida conforme sube el tempo
        wave_spd = (2.0 + rms_val * 2.0) * spd
        bar_ph   = bar_idx * (math.pi * 2.0 / NUM_BARS)

        for led in range(LEDS):
            w      = math.sin((led / LEDS) * math.pi * 4 + t * wave_spd + bar_ph)
            wave_f = 0.5 + w * 0.5
            beat_bri = beat_e * (0.80 + wave_f * 0.20)
            base_bri = (0.08 + rms_val * 0.15) * wave_f
            bri = max(base_bri, beat_bri)
            if beat_e > 0.4:
                r = int(bri * beat_e * 120)
                g = int(bri * beat_e * 160)
                b_v = int(bri * 255)
            else:
                r = 0
                g = int(bri * 80)
                b_v = int(bri * 255)
            i = led * 3;  rgb[i] = r;  rgb[i+1] = g;  rgb[i+2] = b_v

    # ------------------------------------------------------------------ #
    # E5 — FINALE STROBE  (52-65s)                                       #
    # Aceleracion muy pronunciada + BLACKOUT instantaneo al frenar        #
    # ------------------------------------------------------------------ #
    else:
        # --- Curva de velocidad exponencial: 5x amplificacion del exceso ---
        # Esto hace que el 16% de aceleracion real se traduzca en ~2x en pantalla
        # Solo amplificamos el exceso sobre 1.0; los drops ruidosos (<1.0) quedan en 1.0
        exceso = max(0.0, bpm_norm - 1.0)
        # Curva cuadratica: despegue lento al principio, disparo al final
        # Referencia: exceso maximo = 0.226 (167 BPM) → x5
        exceso_norm = min(1.0, exceso / 0.226)   # 0→1 normalizado al pico
        spd_finale = 1.0 + exceso_norm ** 2 * 4.0
        # Resultado:
        #   144 BPM (norm 1.056, exceso_n=0.25) -> spd 1.25x
        #   152 BPM (norm 1.118, exceso_n=0.52) -> spd 2.08x
        #   161 BPM (norm 1.187, exceso_n=0.83) -> spd 3.76x
        #   167 BPM (norm 1.226, exceso_n=1.00) -> spd 5.00x  ← pico

        beat_idx  = state.beatmap.beat_at(t) if state.beatmap else 0
        inversion = (beat_idx % 2) if beat_idx >= 0 else 0
        is_white  = ((bar_idx + inversion) % 2 == 0)

        wave_spd = (2.5 + rms_val * 3.0) * spd_finale
        bar_ph   = bar_idx * (math.pi / NUM_BARS)

        for led in range(LEDS):
            w      = math.sin((led / LEDS) * math.pi * 5 + t * wave_spd + bar_ph)
            wave_f = 1.0 + w * 0.25
            bright = max(0.25 + rms_val * 0.35, beat_e * 1.0) * wave_f
            bright = max(0.0, min(1.0, bright))
            if is_white:
                r, g, b_v = int(bright*255), int(bright*255), int(bright*255)
            else:
                r, g, b_v = int(bright*255), 0, 0
            i = led * 3;  rgb[i] = r;  rgb[i+1] = g;  rgb[i+2] = b_v

    return rgb


SECTION_RENDERERS = [render_stub] * 16  # cubrir hasta 16 secciones
