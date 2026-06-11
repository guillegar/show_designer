"""
SHOW ENGINE - Calcula estados RGB para barras WLED en tiempo real

Encapsula la lógica de show_lola_santa.py para usarse como módulo
desde feedback_app_with_show.py.

v2.0: Integración con EffectLibrary y TimelineScheduler para multi-capa de efectos.
"""
import json
import numpy as np
import socket
import struct
import math
import colorsys
from bisect import bisect_left, bisect_right
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum

try:
    from src.core.effects_engine import EffectLibrary, Effect
    HAS_EFFECTS_ENGINE = True
except ImportError:
    HAS_EFFECTS_ENGINE = False

from src._paths import PROJECT_DIR, ANALIZADAS_DIR
ANALYSIS_FILE = ANALIZADAS_DIR / 'el_taser_de_mama_remix' / 'analysis.json'
TIMESERIES_FILE = ANALIZADAS_DIR / 'el_taser_de_mama_remix' / 'timeseries.npz'

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
NUM_BARS = len(BARS)        # 10 barras físicas
CENTER_BAR = NUM_BARS // 2  # 5 = centro de las 10
LEDS = 93
TOP_LED = LEDS - 1

# v2.3: Los 51 efectos ahora retornan shape (NUM_BARS, 93, 3) = (10, 93, 3) nativamente.
# Mapeo 1:1 (sin espejo) — se mantiene la constante por compatibilidad con código que la importa.
EFFECT_OUTPUT_BARS = NUM_BARS
PHYSICAL_TO_EFFECT_MAP = list(range(NUM_BARS))


class BeatMap:
    def __init__(self, beats):
        self.beats = np.array(beats, dtype=float)
        self.n = len(self.beats)

    def beat_at(self, t):
        i = bisect_right(self.beats, t) - 1
        return i if i >= 0 else -1

    def is_downbeat(self, beat_idx):
        return beat_idx >= 0 and (beat_idx % 4) == 0

    def time_in_beat(self, t, beat_idx):
        if beat_idx < 0: return 0
        return t - self.beats[beat_idx]

    def time_in_downbeat(self, t, beat_idx):
        if beat_idx < 0: return 0
        db_idx = (beat_idx // 4) * 4
        return t - self.beats[db_idx]

    def time_in_phrase(self, t, beat_idx):
        if beat_idx < 0: return 0
        ph_idx = (beat_idx // 16) * 16
        return t - self.beats[ph_idx]


class ShowState:
    def __init__(self, beatmap, sections, piano_notes):
        self.beatmap = beatmap
        self.sections = sections
        self.piano_notes = piano_notes
        self.piano_starts = np.array([n['start'] for n in piano_notes]) if piano_notes else np.array([])

    def section_at(self, t):
        for i, s in enumerate(self.sections):
            if s['start'] <= t <= s['end']:
                return i
        return 0

    def section_progress(self, t, idx):
        s = self.sections[idx]
        return (t - s['start']) / max(0.001, s['end'] - s['start'])


@dataclass
class TemporalEvent:
    """Representa un disparo temporal de efecto."""
    time_sec: float
    effect_id: int  # 0-49
    scope: str  # "per_bar" | "global"
    bar_indices: List[int] = field(default_factory=list)  # Si per_bar, cuáles barras
    parameters: Dict = field(default_factory=dict)  # Dinámicos por efecto

    def is_active(self, current_time, effect_duration_ms):
        """Verifica si este evento está activo en current_time."""
        duration_sec = effect_duration_ms / 1000.0
        return self.time_sec <= current_time < (self.time_sec + duration_sec)

    def elapsed_in_event(self, current_time):
        """Retorna ms transcurridos desde el disparo del evento."""
        return max(0, (current_time - self.time_sec) * 1000)


class TimelineScheduler:
    """Planificador de eventos temporales para disparo de efectos."""

    def __init__(self):
        self.events: List[TemporalEvent] = []

    def add_beat_events(self, beats_times: List[float], effect_id: int,
                        scope: str = "global", **parameters):
        """Agrega disparadores en tiempos de beats."""
        for beat_time in beats_times:
            event = TemporalEvent(
                time_sec=beat_time,
                effect_id=effect_id,
                scope=scope,
                parameters=parameters
            )
            self.events.append(event)

    def add_onset_events(self, onsets_times: List[float], effect_id: int,
                         scope: str = "global", **parameters):
        """Agrega disparadores en tiempos de onsets."""
        for onset_time in onsets_times:
            event = TemporalEvent(
                time_sec=onset_time,
                effect_id=effect_id,
                scope=scope,
                parameters=parameters
            )
            self.events.append(event)

    def add_spectral_events(self, peaks_times: List[float], effect_id: int,
                            peak_type: str = "energy", scope: str = "global", **parameters):
        """Agrega disparadores en peaks espectrales (energía, flux, centroide)."""
        for peak_time in peaks_times:
            event = TemporalEvent(
                time_sec=peak_time,
                effect_id=effect_id,
                scope=scope,
                parameters={**parameters, "peak_type": peak_type}
            )
            self.events.append(event)

    def add_section_events(self, section_boundaries: List[float], effect_id: int,
                          scope: str = "global", **parameters):
        """Agrega disparadores en límites de secciones."""
        for section_time in section_boundaries:
            event = TemporalEvent(
                time_sec=section_time,
                effect_id=effect_id,
                scope=scope,
                parameters=parameters
            )
            self.events.append(event)

    def add_tonal_change_events(self, change_times: List[float], effect_id: int,
                                change_type: str = "chroma", scope: str = "global", **parameters):
        """Agrega disparadores en cambios tonales (chroma, mfcc)."""
        for change_time in change_times:
            event = TemporalEvent(
                time_sec=change_time,
                effect_id=effect_id,
                scope=scope,
                parameters={**parameters, "change_type": change_type}
            )
            self.events.append(event)

    def get_active_events(self, current_time: float, effect_library: 'EffectLibrary',
                         window_ms: float = 100) -> List[TemporalEvent]:
        """Retorna eventos activos en current_time (considerando su duración)."""
        active = []
        for event in self.events:
            effect = effect_library.get_effect(event.effect_id)
            if effect and event.is_active(current_time, effect.duration_ms):
                active.append(event)
        return active

    def clear(self):
        """Limpia todos los eventos."""
        self.events.clear()


def hsv(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return int(r*255), int(g*255), int(b*255)


def blend_max(rgb_buf, led, r, g, b):
    i = led * 3
    if r > rgb_buf[i]:   rgb_buf[i] = r
    if g > rgb_buf[i+1]: rgb_buf[i+1] = g
    if b > rgb_buf[i+2]: rgb_buf[i+2] = b


def fill_bar(rgb_buf, r, g, b):
    for led in range(LEDS):
        i = led * 3
        if r > rgb_buf[i]:   rgb_buf[i] = r
        if g > rgb_buf[i+1]: rgb_buf[i+1] = g
        if b > rgb_buf[i+2]: rgb_buf[i+2] = b


def env_decay(time_in, duration, shape='snap'):
    if time_in >= duration: return 0.0
    if time_in < 0: return 0.0
    p = time_in / duration
    if shape == 'snap':
        return (1 - p) ** 2
    if shape == 'linear':
        return 1 - p
    if shape == 'exp':
        return math.exp(-p * 4)
    if shape == 'pulse':
        return math.sin(p * math.pi)
    return 1 - p


def cos_window(p):
    return 0.5 - 0.5 * math.cos(p * 2 * math.pi)


def layer_flash_all(rgb_buf, color_hsv, intensity):
    if intensity <= 0: return
    r, g, b = hsv(*color_hsv[:2], color_hsv[2] * intensity)
    fill_bar(rgb_buf, r, g, b)


def layer_full_dim(rgb_buf, color_hsv, intensity):
    if intensity <= 0: return
    r, g, b = hsv(*color_hsv[:2], color_hsv[2] * intensity)
    for led in range(LEDS):
        i = led * 3
        if r > rgb_buf[i]:   rgb_buf[i] = r
        if g > rgb_buf[i+1]: rgb_buf[i+1] = g
        if b > rgb_buf[i+2]: rgb_buf[i+2] = b


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


class ShowEngine:
    def __init__(self, use_effects: bool = True, rig=None, analysis=None,
                 output_targets_path: Optional[Path] = None):
        """
        rig: FixtureRig opcional (Fase 3).
        analysis: AnalysisService opcional (Fase A v1.6). Si None se usa el
                  default_service() (El Taser). Cuando llegue multi-proyecto,
                  dual_app inyectará el servicio del proyecto activo.
        output_targets_path: Path al output_targets.json (Fase 3 v1.7). Si
                  None, usa PROJECT_DIR/'output_targets.json'. El router
                  enruta universos a wled/artnet_node/sim_only.
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.loaded = False
        self.beatmap = None
        self.state = None
        self.timeseries = None
        self.duration_s = 165.0
        self.renderers = SECTION_RENDERERS

        # Output Router (v1.7 Fase 3) — opcional para retrocompat
        # Si por lo que sea no se puede cargar, send_artnet_to() sigue siendo
        # el camino legacy para los WLED.
        self.router = None
        try:
            from ..io.outputs.router import OutputRouter
            target_path = output_targets_path or (PROJECT_DIR / 'output_targets.json')
            self.router = OutputRouter.load(target_path)
            print(f"[+] OutputRouter cargado: {len(self.router.targets)} universos enrutados")
        except Exception as e:
            print(f"[!] OutputRouter no disponible: {e}")
        self.rig = rig    # FixtureRig | None
        self.analysis = analysis  # AnalysisService | None

        # v2.0: Effects system
        self.use_effects = use_effects and HAS_EFFECTS_ENGINE
        self.effect_library = None
        self.timeline_scheduler = None

        if self.use_effects:
            try:
                self.effect_library = EffectLibrary()
                self.timeline_scheduler = TimelineScheduler()
                print("[+] Effects engine initialized")
            except Exception as e:
                print(f"[!] Error initializing effects: {e}")
                self.use_effects = False

        self._load_data()

    def _load_data(self):
        """Carga análisis y timeseries vía AnalysisService.

        Si no se inyectó un servicio, usa el default (El Taser). El servicio
        normaliza v1/v2 a v3 transparentemente; show_engine solo ve v3.
        """
        try:
            if self.analysis is None:
                # Lazy import para evitar dep circular
                try:
                    from src.analysis.analyzer_service import default_service
                    self.analysis = default_service()
                except Exception as e:
                    print(f"[!] No se pudo crear AnalysisService default: {e}")
                    self.loaded = False
                    return

            svc = self.analysis
            if not svc.has_analysis:
                print(f"[!] No analysis en {svc.analysis_dir}")
                self.loaded = False
                return

            # Forzar load del payload v3
            payload = svc.payload_v3
            self.duration_s = payload['duration_s']
            sections = payload['sections']
            beats = payload.get('beats', [])
            piano_notes = (payload.get('piano_roll') or {}).get('notes', []) or []

            # ShowState espera el shape original — mantenemos compat
            self.beatmap = BeatMap(beats)
            self.state = ShowState(self.beatmap, sections, piano_notes)

            # timeseries: el servicio lo gestiona, pero algunos consumidores
            # legacy lo leían directamente. Exponemos un dict-like compat.
            svc._load_timeseries()
            self.timeseries = svc._timeseries if svc.has_timeseries else None

            self.loaded = True
            print(f"[+] ShowEngine inicializado vía AnalysisService "
                  f"(song_id={payload.get('song_id', '?')}, "
                  f"bpm={payload['global'].get('bpm', '?')}, "
                  f"downbeats_source={payload['global'].get('downbeats_source', '?')})")

        except Exception as e:
            print(f"[!] Error cargando ShowEngine: {e}")
            import traceback
            traceback.print_exc()
            self.loaded = False

    def get_audio_context(self, elapsed_time: float) -> Dict:
        """Extrae contexto de audio en un tiempo dado para efectos espectrales.

        Si hay AnalysisService, delegar (única fuente, incluye dtempo). En
        caso contrario, fallback a la lógica antigua sobre self.timeseries.
        """
        if self.analysis is not None and self.analysis.has_timeseries:
            return self.analysis.get_audio_context(elapsed_time)

        if not self.loaded or self.timeseries is None:
            return self._default_audio_context()

        try:
            ts_times = self.timeseries['times']

            audio_context = {}

            # Helper: interpola array multidim (n_coeff, n_frames) → vector (n_coeff,)
            def interp_multidim(data_2d):
                """data_2d shape (n_coeff, n_frames). Retorna shape (n_coeff,)."""
                n_coeff = data_2d.shape[0]
                result = np.zeros(n_coeff, dtype=np.float32)
                for i in range(n_coeff):
                    result[i] = np.interp(elapsed_time, ts_times, data_2d[i], left=0, right=0)
                return result

            # MFCC (13 coeficientes × n_frames)
            if 'mfcc' in self.timeseries:
                audio_context['mfcc'] = interp_multidim(self.timeseries['mfcc'])

            # Chroma (12 notas × n_frames)
            if 'chroma' in self.timeseries:
                audio_context['chroma'] = interp_multidim(self.timeseries['chroma'])

            # Tonnetz (6 dimensiones × n_frames)
            if 'tonnetz' in self.timeseries:
                audio_context['tonnetz'] = interp_multidim(self.timeseries['tonnetz'])

            # Contrast (7 bandas × n_frames)
            if 'contrast' in self.timeseries:
                audio_context['contrast'] = interp_multidim(self.timeseries['contrast'])

            # Mel bands (8 bandas × n_frames) - extra feature
            if 'mel_bands' in self.timeseries:
                audio_context['mel_bands'] = interp_multidim(self.timeseries['mel_bands'])

            # Spectral centroid (1D)
            if 'centroid' in self.timeseries:
                audio_context['centroid'] = float(np.interp(elapsed_time, ts_times,
                                                              self.timeseries['centroid']))

            # Spectral flux (1D)
            if 'flux' in self.timeseries:
                audio_context['flux'] = float(np.interp(elapsed_time, ts_times,
                                                          self.timeseries['flux']))

            # RMS (1D)
            if 'rms' in self.timeseries:
                audio_context['rms'] = float(np.interp(elapsed_time, ts_times,
                                                         self.timeseries['rms']))

            # ZCR (1D) - extra feature
            if 'zcr' in self.timeseries:
                audio_context['zcr'] = float(np.interp(elapsed_time, ts_times,
                                                        self.timeseries['zcr']))

            # Energy: si no existe directamente, derivar de RMS
            if 'energy' in self.timeseries:
                audio_context['energy'] = float(np.interp(elapsed_time, ts_times,
                                                            self.timeseries['energy']))
            else:
                # Fallback: energy ≈ rms^2
                audio_context['energy'] = audio_context.get('rms', 0.0) ** 2

            return audio_context

        except Exception as e:
            print(f"[!] Error extracting audio context: {e}")
            import traceback
            traceback.print_exc()
            return self._default_audio_context()

    def _default_audio_context(self) -> Dict:
        """Retorna contexto de audio por defecto (cuando no hay datos)."""
        return {
            'mfcc': np.zeros(13, dtype=np.float32),
            'chroma': np.zeros(12, dtype=np.float32),
            'tonnetz': np.zeros(6, dtype=np.float32),
            'contrast': np.zeros(7, dtype=np.float32),
            'mel_bands': np.zeros(8, dtype=np.float32),
            'energy': 0.0,
            'centroid': 0.0,
            'flux': 0.0,
            'rms': 0.0,
            'zcr': 0.0,
        }

    def blend_frames(self, base_frame: np.ndarray, overlay_frame: np.ndarray,
                     alpha: float = 0.7) -> np.ndarray:
        """Mezcla dos frames RGB usando alpha blending."""
        return (base_frame * (1 - alpha) + overlay_frame * alpha).astype(np.uint8)

    def compute_frame(self, elapsed_time):
        """
        Calcula RGB para todas las barras en un tiempo dado.
        Devuelve: list[bytearray] — RGB para cada barra (0-6)

        v2.0: Usa EffectLibrary + TimelineScheduler si está disponible,
        retorna a render_stub como fallback.
        """
        if not self.loaded:
            return [bytearray(LEDS * 3) for _ in range(NUM_BARS)]

        if elapsed_time < 0 or elapsed_time > self.duration_s:
            return [bytearray(LEDS * 3) for _ in range(NUM_BARS)]

        try:
            # Si effects está disponible, usarlo; si no, fallback a render_stub
            if self.use_effects and self.effect_library and self.timeline_scheduler:
                return self._compute_frame_with_effects(elapsed_time)
            else:
                return self._compute_frame_legacy(elapsed_time)

        except Exception as e:
            print(f"[!] Error en compute_frame({elapsed_time}): {e}")
            return self._compute_frame_legacy(elapsed_time)

    def _compute_frame_with_effects(self, elapsed_time: float) -> List[bytearray]:
        """Computador de frames usando EffectLibrary y TimelineScheduler."""
        # Inicializar frames RGB para todas las barras
        frame_3d = np.zeros((NUM_BARS, LEDS, 3), dtype=np.uint8)

        # Obtener contexto de audio
        audio_context = self.get_audio_context(elapsed_time)

        # Obtener eventos activos en este tiempo
        active_events = self.timeline_scheduler.get_active_events(elapsed_time, self.effect_library)

        # Renderizar cada evento activo
        for event in active_events:
            try:
                effect = self.effect_library.get_effect(event.effect_id)
                if not effect:
                    continue

                # Tiempo transcurrido desde el disparo (en ms)
                elapsed_in_effect = event.elapsed_in_event(elapsed_time)

                # Llamar render del efecto
                effect_rgb = effect.render(
                    elapsed_time=elapsed_in_effect,
                    bars_state=frame_3d.copy(),
                    audio_context=audio_context,
                    **event.parameters
                )

                # v2.1: Extender shape (7,93,3) → (NUM_BARS,93,3) si las
                # barras físicas son más que las que retorna el efecto.
                if effect_rgb.shape[0] < NUM_BARS:
                    extended = np.zeros((NUM_BARS, LEDS, 3), dtype=np.uint8)
                    for phys_idx in range(NUM_BARS):
                        eff_idx = PHYSICAL_TO_EFFECT_MAP[phys_idx]
                        if 0 <= eff_idx < effect_rgb.shape[0]:
                            extended[phys_idx] = effect_rgb[eff_idx]
                    effect_rgb = extended

                # Mezclar según scope
                if event.scope == "global" or event.scope == "all_bars":
                    # Efecto global: mezclar en todo el frame
                    frame_3d = self.blend_frames(frame_3d, effect_rgb, alpha=0.7)
                elif event.scope == "per_bar" and event.bar_indices:
                    # Efecto per-bar: aplicar solo a barras específicas
                    for bar_idx in event.bar_indices:
                        if 0 <= bar_idx < NUM_BARS:
                            frame_3d[bar_idx] = self.blend_frames(
                                frame_3d[bar_idx],
                                effect_rgb[0] if effect_rgb.shape[0] == 1 else effect_rgb[bar_idx],
                                alpha=0.7
                            )

            except Exception as e:
                # Log de error pero continúa con siguiente evento
                print(f"[!] Error renderizando effect {event.effect_id}: {e}")
                continue

        # Agregar capa de fondo: sección actual
        try:
            section = self.state.section_at(elapsed_time)
            colors = [
                (0.70, 1.0, 0.3),  # 0: azul tenue
                (0.95, 1.0, 0.5),  # 1: verde tenue
                (0.15, 1.0, 0.6),  # 2: rojo oscuro
                (0.0, 1.0, 1.0),   # 3: rojo brillante
                (0.33, 1.0, 0.7),  # 4: cyan
                (0.80, 1.0, 0.5),  # 5: morado
                (0.15, 0.5, 0.3),  # 6: rojo muy oscuro
                (0.0, 1.0, 0.9),   # 7: rojo puro
            ]
            color_hsv = colors[section] if section < len(colors) else (0, 0, 0)

            # Obtener RMS para intensidad
            rms_val = audio_context.get('rms', 0.2)
            intensity = 0.1 + rms_val * 0.3  # Background tenue
            r, g, b = hsv(*color_hsv[:2], color_hsv[2] * intensity)

            bg_frame = np.full((NUM_BARS, LEDS, 3), [r, g, b], dtype=np.uint8)
            frame_3d = self.blend_frames(frame_3d, bg_frame, alpha=0.2)  # 20% fondo

        except Exception as e:
            print(f"[!] Error rendering section background: {e}")

        # Convertir a list[bytearray] como espera la app
        rgb_frames = []
        for bar_idx in range(NUM_BARS):
            bar_rgb = frame_3d[bar_idx].flatten().astype(np.uint8)
            rgb_frames.append(bytearray(bar_rgb))

        return rgb_frames

    def _compute_frame_legacy(self, elapsed_time: float) -> List[bytearray]:
        """Computador de frames legacy usando render_stub."""
        try:
            ts_times = self.timeseries['times']
            rms  = self.timeseries['rms']
            flux = self.timeseries['flux']
            rms_norm  = np.clip((rms  - rms.min())  / (rms.max()  - rms.min()  + 0.001), 0, 1)
            flux_norm = np.clip((flux - flux.min()) / (flux.max() - flux.min() + 0.001), 0, 1)

            section  = self.state.section_at(elapsed_time)
            rms_val  = float(np.interp(elapsed_time, ts_times, rms_norm))
            flux_val = float(np.interp(elapsed_time, ts_times, flux_norm))

            # BPM local: tempo instantaneo normalizado respecto al BPM base (136)
            # Se usa para acelerar los efectos cuando la cancion se acelera
            bpm_norm = 1.0
            if 'dtempo' in self.timeseries and 'dtempo_times' in self.timeseries:
                raw_bpm = float(np.interp(elapsed_time,
                                          self.timeseries['dtempo_times'],
                                          self.timeseries['dtempo']))
                # Corregir armonicos: valores < 80 probablemente son mitad de tempo
                if raw_bpm < 80:
                    raw_bpm *= 2
                # Normalizar respecto al BPM base; limitar a rango razonable
                bpm_norm = float(np.clip(raw_bpm / 136.0, 0.75, 1.6))

            renderer   = self.renderers[section]
            rgb_frames = []

            for bar_idx in range(NUM_BARS):
                rgb = renderer(elapsed_time, bar_idx, self.state,
                               rms_val, flux_val, bpm_norm)
                rgb_frames.append(rgb)

            return rgb_frames

        except Exception as e:
            print(f"[!] Error en _compute_frame_legacy({elapsed_time}): {e}")
            return [bytearray(LEDS * 3) for _ in range(NUM_BARS)]

    def auto_schedule_from_analysis(self, audio_path: Optional[str] = None,
                                      beat_effect_id: int = 0,
                                      onset_effect_id: int = 1,
                                      spectral_effect_id: int = 2) -> bool:
        """
        Lee analysis.json y auto-genera disparadores de efectos.
        Retorna True si fue exitoso.
        """
        if not self.loaded or not self.timeline_scheduler:
            return False

        try:
            if self.analysis is None or not self.analysis.has_analysis:
                print(f"[!] auto_schedule_from_analysis sin AnalysisService disponible")
                return False
            svc = self.analysis

            # Beats (lista de floats en segundos)
            beats = svc.list_beats()
            if beats:
                self.timeline_scheduler.add_beat_events(beats, beat_effect_id, scope="global")
                print(f"[+] Scheduled {len(beats)} beat events")

            # Onsets — usamos 'all' como fuente principal
            onsets_list = [e.time_sec for e in svc.list_events('onsets_all')]
            if onsets_list:
                self.timeline_scheduler.add_onset_events(
                    onsets_list, onset_effect_id, scope="global"
                )
                print(f"[+] Scheduled {len(onsets_list)} onset events")

            # Spectral peaks - kicks como peaks de energía (respeta curación)
            kick_times = [e.time_sec for e in svc.list_events('kick')]
            if kick_times:
                self.timeline_scheduler.add_spectral_events(
                    kick_times, spectral_effect_id, peak_type="energy", scope="global"
                )
                print(f"[+] Scheduled {len(kick_times)} kick (energy peak) events")

            # Sections - límites como triggers de transición
            section_starts = [s.start for s in svc.list_sections()]
            if section_starts:
                # Usar effect_id 8 (multi_color_flash) por defecto para transiciones
                self.timeline_scheduler.add_section_events(
                    section_starts, effect_id=8, scope="global"
                )
                print(f"[+] Scheduled {len(section_starts)} section transition events")

            return True

        except Exception as e:
            print(f"[!] Error en auto_schedule_from_analysis: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_scheduler(self) -> Optional[TimelineScheduler]:
        """Retorna el scheduler para acceso externo."""
        return self.timeline_scheduler

    def _build_artnet_packet(self, universe: int, dmx_payload: bytes) -> bytes:
        """Construye un paquete Art-Net OpDmx (0x5000) estándar."""
        dmx = bytearray(512)
        dmx[:len(dmx_payload)] = dmx_payload
        return (b'Art-Net\x00' + struct.pack('<H', 0x5000) + struct.pack('>H', 14) +
                b'\x00\x00' + struct.pack('<H', universe) + struct.pack('>H', 512) + bytes(dmx))

    def send_artnet_to(self, ip: str, universe: int, dmx_payload: bytes):
        """Envío bajo nivel: paquete Art-Net a una IP+universo concretos."""
        try:
            pkt = self._build_artnet_packet(universe, dmx_payload)
            self.sock.sendto(pkt, (ip, 6454))
        except Exception:
            pass

    def send_artnet(self, bar_idx, rgb_data):
        """
        Envía RGB data a una barra. Si hay rig configurado, usa el routing
        del fixture correspondiente (by_legacy_bar). Si no, fallback a BARS.
        """
        try:
            if self.rig is not None:
                fx = self.rig.by_legacy_bar(bar_idx)
                if fx and fx.target_ip:
                    self.send_artnet_to(fx.target_ip, fx.universe, rgb_data)
                    return
            # Fallback legacy: lista BARS hard-coded
            ip, universe = BARS[bar_idx]
            self.send_artnet_to(ip, universe, rgb_data)
        except Exception:
            pass

    def send_frame(self, rgb_frames):
        """Envía todos los RGB frames a las barras vía Art-Net."""
        for bar_idx, rgb in enumerate(rgb_frames):
            self.send_artnet(bar_idx, rgb)

    # ════════════════════════════════════════════════════════════
    # v1.7 Fase 3 — Universe Assembler + Layer-mixed channel render
    # ════════════════════════════════════════════════════════════

    def render_channels_for_fixture(self, fixture, t: float,
                                    audio_context: Optional[Dict] = None,
                                    timeline=None) -> bytearray:
        """Genera los bytes DMX del fixture aplicando los clips channel-level
        activos en este tiempo, en orden de **layers ascendentes** (LTP).

        Para fixtures con `kind == 'led_strip'` esta función NO se usa: el
        flujo legacy `send_frame(rgb_frames)` sigue gestionando todos los
        píxeles RGB tal cual estaba antes de v1.7.

        Para fixtures no-LED:
          1. Buffer inicial = ceros (num_channels bytes).
          2. Itera clips activos asignados a este fixture en este `t`,
             ordenados por layer ascendente (capa superior pisa).
          3. Para cada clip, carga su ChannelEffect (Fase 6) y llama
             `effect.render(t, fixture, audio_context, clip.params)` →
             dict {channel_name: 0..255}.
          4. Aplica al buffer en los offsets del `profile.channel_map`.

        Por ahora (Fase 3, antes de tener ChannelEffect en Fase 6) el
        catálogo de channel-effects está vacío → el buffer se queda en 0s
        y el fixture renderiza "apagado". Esto es lo correcto: el flujo
        está montado, faltan los efectos.
        """
        if self.rig is None or fixture is None:
            return bytearray(0)

        profile = self.rig.get_profile(fixture.profile_id)
        if profile is None:
            return bytearray(0)

        buf = bytearray(profile.num_channels)

        # Recoger clips channel-level del timeline activos en `t` para este fixture
        if timeline is not None:
            clips_here = self._collect_channel_clips_at(
                timeline, fixture, t * 1000.0,
            )
            # Ordenar por layer ascendente (LTP entre layers)
            clips_here.sort(key=lambda c: (getattr(c, 'layer', 0),
                                            c.start_ms))

            for clip in clips_here:
                channels = self._render_clip_channels(
                    clip, fixture, t, audio_context,
                )
                if not channels:
                    continue
                for ch_name, val in channels.items():
                    offset = profile.channel_map.get(ch_name)
                    if offset is None or offset >= len(buf):
                        continue
                    buf[offset] = max(0, min(255, int(val)))

        return buf

    def _collect_channel_clips_at(self, timeline, fixture, t_ms: float) -> list:
        """Devuelve clips activos del fixture en t_ms (con categoría no-pixel).

        Por ahora reusamos el modelo de Clip existente. Un clip se considera
        "channel" si tiene atributo `category` != 'pixel' (Fase 5 v1.7 lo
        introducirá oficialmente). Antes de Fase 5, los clips no tienen
        `category` → se interpretan como pixel y este método los excluye.
        """
        out = []
        if not hasattr(timeline, 'clips'):
            return out
        fixture_scope_str = f"fixture:{fixture.fixture_id}"
        for clip in timeline.clips:
            # Filtrar por categoría (default 'pixel' = LED, no aplica aquí)
            cat = getattr(clip, 'category', 'pixel')
            if cat == 'pixel':
                continue
            # Filtrar por tiempo
            if not (clip.start_ms <= t_ms < clip.end_ms):
                continue
            # Filtrar por scope (debe apuntar al fixture o a un grupo que lo contiene)
            scope = getattr(clip, 'scope', '')
            if scope == fixture_scope_str or scope == 'global':
                out.append(clip)
                continue
            # group: groups containing fixture (Fase 5 ampliará scope:fixture:)
        return out

    def _get_channel_library(self):
        """Carga ChannelEffectLibrary perezosamente (singleton en ShowEngine)."""
        if not hasattr(self, '_channel_library'):
            try:
                from .channel_effects import ChannelEffectLibrary
                self._channel_library = ChannelEffectLibrary()
            except Exception as e:
                print(f"[!] ChannelEffectLibrary no disponible: {e}")
                self._channel_library = None
        return self._channel_library

    def _render_clip_channels(self, clip, fixture, t: float,
                              audio_context: Optional[Dict]) -> Dict[str, int]:
        """Carga el ChannelEffect del clip y llama a su render.

        v1.7 Fase 6: usa ChannelEffectLibrary. El effect_id de un clip de
        canal es el string `channel_effect_id` del Clip (ej. 'pos_circle').
        """
        lib = self._get_channel_library()
        if lib is None:
            return {}
        # channel_effect_id tiene prioridad; fallback a str(effect_id) por compat
        eff_id = getattr(clip, 'channel_effect_id', None)
        if not eff_id:
            raw = getattr(clip, 'effect_id', None)
            eff_id = str(raw) if isinstance(raw, str) else None
        if not eff_id:
            return {}
        effect = lib.get(eff_id)
        if effect is None:
            return {}
        try:
            # Tiempo relativo al clip (elapsed time desde el start)
            elapsed = t - (clip.start_ms / 1000.0)
            result = effect.render(elapsed, audio_context, getattr(clip, 'params', None) or {})
            # Garantizar que todos los valores son int 0-255
            return {k: max(0, min(255, int(round(v)))) for k, v in result.items()}
        except Exception as e:
            print(f"[!] ChannelEffect {eff_id} render error: {e}")
            return {}

    def assemble_universe(self, universe_id: int, t: float,
                          audio_context: Optional[Dict] = None,
                          rgb_frames_by_bar: Optional[List] = None,
                          timeline=None) -> bytes:
        """Ensambla los 512 bytes del universo `universe_id` en el instante `t`.

        Combina:
          • Fixtures LED strip → bytes RGB tal como los generaría el flujo
            legacy. Si `rgb_frames_by_bar` está dado, usa esos (consistencia
            con el render del Timeline). Si es None, devuelve ceros para LED
            (el caller debe haber renderizado por su cuenta).
          • Fixtures no-LED → render_channels_for_fixture() con layer mixing.

        Devuelve `bytes(512)` listo para enviar por Art-Net.
        """
        out = bytearray(512)
        if self.rig is None:
            return bytes(out)

        for fx in self.rig.by_universe(universe_id):
            profile = self.rig.get_profile(fx.profile_id)
            if profile is None:
                continue

            dmx_start_0 = max(0, int(fx.dmx_start) - 1)   # 1-based → 0-based
            n = profile.num_channels

            if profile.kind == 'led_strip' and profile.led_count > 0:
                # Buscar el RGB frame correspondiente
                rgb = None
                if rgb_frames_by_bar is not None and fx.legacy_bar_idx is not None:
                    if 0 <= fx.legacy_bar_idx < len(rgb_frames_by_bar):
                        rgb = rgb_frames_by_bar[fx.legacy_bar_idx]
                if rgb is None:
                    continue   # nada que escribir, deja en 0
                # rgb puede ser bytearray ya flat, o array (LEDS, 3) numpy
                if hasattr(rgb, 'tobytes'):
                    rgb_bytes = bytes(rgb)
                elif isinstance(rgb, (bytes, bytearray)):
                    rgb_bytes = bytes(rgb)
                else:
                    rgb_bytes = bytes(rgb)
                end = min(dmx_start_0 + len(rgb_bytes), 512)
                out[dmx_start_0:end] = rgb_bytes[:end - dmx_start_0]
            else:
                # Fixture no-LED → layer-mixed buffer
                buf = self.render_channels_for_fixture(
                    fx, t, audio_context, timeline=timeline,
                )
                end = min(dmx_start_0 + len(buf), 512)
                out[dmx_start_0:end] = buf[:end - dmx_start_0]

        return bytes(out)

    def send_universe_via_router(self, universe_id: int, dmx_bytes: bytes) -> None:
        """Despacha los bytes al OutputRouter (wled / artnet_node / sim_only).

        Compatible con el send_artnet_to() legacy: si hay router lo usa;
        si no, fallback al sock UDP directo (asumiendo Art-Net broadcast,
        que no es lo deseable pero mantiene compat).
        """
        if self.router is not None:
            self.router.send(universe_id, dmx_bytes)
        # Sin router no hay destino (sim_only): no-op silencioso.

    def get_fixture_dmx_states(self, t: float,
                                audio_context: Optional[Dict] = None,
                                rgb_frames_by_bar: Optional[List] = None,
                                timeline=None) -> Dict[str, Dict[str, float]]:
        """Devuelve el estado DMX normalizado (0..1) de los fixtures NO-LED
        en el instante `t`, listo para que el viewer 3D mueva movers/strobes.

        Estructura:
            {
              "mover_wash_L_back": {"pan": 0.5, "tilt": 0.3, "dim": 1.0,
                                    "r": 1.0, "g": 0.4, "b": 0.0, ...},
              ...
            }

        El cálculo:
          1. Itera fixtures no-LED del rig.
          2. Obtiene el buffer DMX del fixture (vía `render_channels_for_fixture`).
          3. Aplica `Fixture.manual_channels` (override) si el fixture lo expone
             — útil para sliders del patch panel y `set_fixture_channel` MCP.
          4. Mapea cada canal del `channel_map` a un valor 0..1.

        Los fixtures LED strip se omiten (los frames RGB van por canal binario).
        """
        states: Dict[str, Dict[str, float]] = {}
        if self.rig is None:
            return states

        for fx in self.rig.fixtures:
            profile = self.rig.get_profile(fx.profile_id)
            if profile is None:
                continue
            if profile.kind == 'led_strip' and profile.led_count > 0:
                continue   # los LED ya van por el frame RGB binario

            # Buffer DMX del fixture (zeros hasta Fase 6 si no hay clips channel)
            try:
                buf = self.render_channels_for_fixture(
                    fx, t, audio_context, timeline=timeline,
                )
            except Exception:
                buf = bytearray(profile.num_channels)

            # Aplicar overrides manuales si los hay
            manual = getattr(fx, 'manual_channels', None) or {}

            ch_state: Dict[str, float] = {}
            for ch_name, offset in profile.channel_map.items():
                # Override manual prevalece
                if ch_name in manual:
                    try:
                        v = float(manual[ch_name])
                        v = max(0.0, min(1.0, v))
                    except (TypeError, ValueError):
                        v = 0.0
                else:
                    if 0 <= offset < len(buf):
                        v = buf[offset] / 255.0
                    else:
                        v = 0.0
                ch_state[ch_name] = v

            states[fx.fixture_id] = ch_state

        return states

    def send_frame_via_assembler(self, t: float, audio_context: Optional[Dict],
                                  rgb_frames_by_bar: List, timeline=None) -> None:
        """Versión alternativa de send_frame() que pasa por el assembler y
        el router. Útil para tests + para el siguiente paso (broadcast 3D).

        OJO: por ahora **no se usa en el render loop real** del Timeline —
        eso sigue por `send_frame(rgb_frames)` legacy para mantener bit-exact
        el show de El Taser. Esta función existe para tests y para el
        broadcast extendido al viewer 3D que llegará en Fase 4.
        """
        if self.rig is None:
            return
        for uni in self.rig.universes():
            packet = self.assemble_universe(
                uni, t, audio_context,
                rgb_frames_by_bar=rgb_frames_by_bar,
                timeline=timeline,
            )
            self.send_universe_via_router(uni, packet)
