"""
Timeline Editor v0.5 – Grupos de barras.

NUEVAS funcionalidades v0.4
───────────────────────────
Draw tool  : clic en efecto del browser → cursor lápiz → arrastra en el track para crear clip.
             Escape / clic en 🖱 → vuelve a Select.
Undo/Redo  : Ctrl+Z / Ctrl+Shift+Z  (historial de 60 estados).
Copy/Paste : Ctrl+C copia selección, Ctrl+V pega en posición del cursor.
Layers     : cada bar tiene sub-filas (layer 0, 1, 2…). El clip elige su layer.
             Track header muestra "Bar 0 [2]" si hay 2 layers.
             Clips en el mismo bar se asignan automáticamente al layer libre.
Lock/Unlock: Ctrl+L / Ctrl+U – clips bloqueados no se mueven ni borran.
Bookmarks  : Ctrl+0-9 → salta a marcador; Shift+0-9 → crea marcador en cursor.
Audio scr. : Ctrl+drag en waveform → escucha el audio al desplazar el cursor.
Zoom +/-   : teclas + y - (igual que xLights).
Expand→mark: Ctrl+Shift+← / → expande el clip hasta el marker anterior/siguiente.
Draw mode  : cursor cambia a cruz; la toolbar muestra el efecto activo.

v0.3 FL-style visuals conservados (grid beats/bars, ruler, track colors, etc.)
Versiones anteriores: *_v01.py  *_v02.py  *_v03.py

Lanzar: python timeline_editor.py
"""
import sys, json, copy, math
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict

# Setup MINIMAL de sys.path ANTES de importar src._setup_paths
# (necesario porque src._setup_paths es lo que configura sys.path correctamente)
_root = Path(__file__).resolve().parent.parent.parent  # src/ui/timeline_editor.py → show-designer/
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Setup centralizado de sys.path
from src._setup_paths import *
import pygame, librosa

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QSlider, QComboBox,
    QListWidget, QListWidgetItem, QSplitter,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QGraphicsLineItem, QGraphicsTextItem, QGraphicsPathItem,
    QGraphicsItemGroup,
    QSpinBox, QStatusBar, QToolBar, QAction, QCheckBox, QMenu,
    QActionGroup, QInputDialog, QColorDialog, QFileDialog,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRectF, QPointF, QRect
from PyQt5.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
    QLinearGradient, QPainterPath, QCursor, QPixmap, QImage,
)

from src.core.effects_engine import EffectLibrary
from src.core.show_engine import ShowEngine, NUM_BARS, LEDS
from src.core.timeline_model import Timeline, Clip, BarGroup, CuePoint, NUM_TRACKS, make_demo_timeline, TIMELINE_FILE
from src.utils.shortcuts import ShortcutManager, ShortcutsDialog


# ═══════════════════════════════════════════════════════════════
# Layout & color constants  (FL Studio palette)
# ═══════════════════════════════════════════════════════════════
from src._paths import PROJECT_DIR, ANALIZADAS_DIR
AUDIO_FILE    = PROJECT_DIR / 'El Taser de Mama Remix.mp3'
ANALYSIS_FILE = ANALIZADAS_DIR / 'el_taser_de_mama_remix' / 'analysis.json'

DEFAULT_PX_PER_SEC = 40.0
WAVEFORM_H   = 72
RULER_H      = 22
BASE_TRACK_H = 32       # altura por LAYER
TRACK_GAP    = 1
HEADER_W     = 120
COLOR_STRIP  = 5
SNAP_RADIUS_MS = 80
MAX_LAYERS   = 8        # máx layers por bar visibles

# ─── Design System palette (design handoff 2026-06-01) ─────────────────────
C_BG          = QColor(0x0d, 0x0f, 0x12)   # bg-0
C_TRACK_EVEN  = QColor(0x15, 0x18, 0x1d)   # bg-1
C_TRACK_ODD   = QColor(0x11, 0x14, 0x18)   # entre bg-0 y bg-1
C_TRACK_LAYER = QColor(0x1d, 0x21, 0x27)   # bg-2 sub-layer
C_HEADER_BG   = QColor(0x1d, 0x21, 0x27)   # bg-2
C_HEADER_TEXT = QColor(0xf3, 0xf4, 0xf6)   # txt
C_RULER_BG    = QColor(0x15, 0x18, 0x1d)   # bg-1
C_RULER_BAR   = QColor(0xf3, 0xf4, 0xf6)   # txt
C_RULER_BEAT  = QColor(0x7d, 0x83, 0x8f)   # txt-3
C_GRID_BAR    = QColor(0x36, 0x3c, 0x45, 180)  # line
C_GRID_BEAT   = QColor(0x2b, 0x30, 0x38, 130)  # line-soft
C_WAVEFORM    = QColor(0x1f, 0xe3, 0x9a, 145)  # acc (verde LED)
C_SECTION     = QColor(0xe3, 0xc1, 0x4f, 220)  # warn ámbar
C_KICK        = QColor(0xf0, 0x65, 0x4b,  70)  # bad rojo
C_BEAT_MARK   = QColor(0x36, 0x3c, 0x45,  80)  # line dim
C_CURSOR      = QColor(0x1f, 0xe3, 0x9a)        # acc verde
C_SEL_BORDER  = QColor(0xa7, 0x79, 0xf0)        # acc-2 violeta
C_LOCK_TINT   = QColor(0xa7, 0x79, 0xf0,  30)
C_DRAW_RECT   = QColor(0x1f, 0xe3, 0x9a,  35)
C_DRAW_BORDER = QColor(0x1f, 0xe3, 0x9a, 200)
C_RB_FILL     = QColor(0xa7, 0x79, 0xf0,  25)
C_RB_BORDER   = QColor(0xa7, 0x79, 0xf0, 180)
C_BOOKMARK    = QColor(0xe3, 0xc1, 0x4f, 200)

# Familias de efectos (design handoff — colores vivos y distinguibles)
FAMILY_COLORS = {
    'flash':    '#f07a5a',   # rojo-naranja
    'wave':     '#5aa9f0',   # azul
    'gradient': '#d569e0',   # magenta
    'pattern':  '#3fe08a',   # verde
    'spectral': '#a779f0',   # violeta
    'color':    '#e0c05a',   # ámbar
}

# Fuente monoespaciada (JetBrains Mono si está instalada, Consolas como fallback)
FONT_MONO = QFont("JetBrains Mono", 7)
FONT_MONO.setStyleHint(QFont.Monospace)
FONT_MONO_SM = QFont("JetBrains Mono", 6)
FONT_MONO_SM.setStyleHint(QFont.Monospace)


def _bar_hue_color(idx: int, alpha: int = 255) -> QColor:
    """Color de barra calculado como oklch(0.75 0.16 idx*36°). Aproximado en HSV."""
    hue = (idx * 36) % 360
    return QColor.fromHsvF(hue / 360.0, 0.72, 0.82, alpha / 255.0)


# Colores de strip por barra (10 barras): calculados dinámicamente
TRACK_STRIP_COLORS = [_bar_hue_color(i).name() for i in range(10)]

# Colores de grupos (12 slots)
GROUP_COLORS = [_bar_hue_color(i * 3).name() for i in range(12)]


# ═══════════════════════════════════════════════════════════════
# Undo Manager
# ═══════════════════════════════════════════════════════════════
class UndoManager:
    """Snapshot-based undo/redo sobre la lista de clips."""
    def __init__(self, max_size: int = 60):
        self._stack: List[list] = []   # lista de snapshots (listas de dicts)
        self._pos   = -1
        self._max   = max_size

    def snapshot(self, clips: List[Clip]):
        """Guardar estado ANTES de una modificación."""
        self._stack = self._stack[:self._pos + 1]
        self._stack.append([c.to_dict() for c in clips])
        if len(self._stack) > self._max:
            self._stack.pop(0)
        else:
            self._pos += 1

    def undo(self) -> Optional[List[Clip]]:
        if self._pos <= 0:
            return None
        self._pos -= 1
        return [Clip.from_dict(d) for d in self._stack[self._pos]]

    def redo(self) -> Optional[List[Clip]]:
        if self._pos >= len(self._stack) - 1:
            return None
        self._pos += 1
        return [Clip.from_dict(d) for d in self._stack[self._pos]]

    @property
    def can_undo(self): return self._pos > 0
    @property
    def can_redo(self): return self._pos < len(self._stack) - 1


# ═══════════════════════════════════════════════════════════════
# Waveform
# ═══════════════════════════════════════════════════════════════
class WaveformData:
    def __init__(self, path: Path):
        self.audio_path = Path(path)
        self.duration_s = 0.0
        self.peaks = np.zeros(1, dtype=np.float32)
        self.sr = 22050
        self._load()

    def _load(self):
        print(f"[waveform] {self.audio_path.name}...")
        try:
            y, sr = librosa.load(str(self.audio_path), sr=self.sr, mono=True)
            self.duration_s = len(y) / sr
            bs = int(sr * 0.010); nb = len(y) // bs
            blk = y[:nb*bs].reshape(nb, bs)
            self.peaks = np.max(np.abs(blk), axis=1).astype(np.float32)
            self.peaks /= max(0.001, float(self.peaks.max()))
            print(f"[waveform] {self.duration_s:.1f}s OK")
        except Exception as e:
            print(f"[waveform] error: {e}")


# ═══════════════════════════════════════════════════════════════
# Timeline View
# ═══════════════════════════════════════════════════════════════
TOOL_SELECT = 'select'
TOOL_DRAW   = 'draw'
TOOL_SLICE  = 'slice'    # FL Round 2: cortar clip al hacer clic sobre él

class TimelineView(QGraphicsView):
    clips_selected   = pyqtSignal(list)
    time_seeked      = pyqtSignal(float)
    clip_created     = pyqtSignal(object)   # new Clip via draw tool
    copy_requested   = pyqtSignal()         # context-menu / atajo: copia selección
    paste_requested  = pyqtSignal()         # context-menu / atajo: pega clipboard
    request_snapshot = pyqtSignal()         # before mutating
    draw_warning     = pyqtSignal(str)      # v1.9 F1: mismatch lane/effect-kind

    def __init__(self, timeline: Timeline, waveform: WaveformData,
                 markers: dict, bpm: float = 128.0, parent=None):
        super().__init__(parent)
        self.timeline  = timeline
        self.waveform  = waveform
        self.markers   = markers
        self.bpm       = max(60.0, bpm)
        self.beat_ms   = 60000.0 / self.bpm
        self.bar_ms    = self.beat_ms * 4
        self.beats_per_bar = 4

        self.px_per_sec      = DEFAULT_PX_PER_SEC
        self.current_time_s  = 0.0
        self.ruler_mode      = 'bars'

        # Tool
        self.tool_mode       = TOOL_SELECT
        # v1.9 F1 — ningún efecto elegido por defecto: el usuario DEBE
        # seleccionar uno (pixel o channel) antes de poder dibujar.
        # Evita crear clips fantasma de white_flash si activa Draw sin elegir.
        self.draw_effect_id  = None
        self.draw_kind: str  = 'pixel'                 # 'pixel' | 'channel'
        self.draw_channel_effect_id = None             # str ('pos_circle'…)
        self.draw_channel_category  = None             # 'position'|'color'|'intensity'|'optical'|'strobe'
        self.draw_channel_defaults: Dict = {}
        self._draw_start_ms  = None
        self._draw_track     = None
        self._draw_layer     = 0
        self._draw_item      = None    # preview rect

        # Selection
        self.selected_clips: List[Clip] = []

        # Drag (select mode)
        self._drag_clip   = None
        self._drag_mode   = None
        self._drag_offset = 0.0
        self._drag_rel: Dict = {}

        # Rubber-band (select mode)
        self._rb_origin    = None
        self._rb_rect_item = None
        self._rb_add       = False

        # Snap
        self._snap_on = True
        self._snap_pts: list = []
        # Snap grid (subdivisión musical, estilo FL Studio):
        #   'off'  → solo snap a markers/clips/beats existentes
        #   'bar'  → snap a cada compás (4 beats)
        #   'beat' → snap a cada beat
        #   '1/4', '1/8', '1/16' → subdivisión de beat
        self._snap_grid = 'beat'

        # ── Filtros de vista (Fase 2.5) ───────────────────────────────
        # Tipos de track visibles. Si se desmarca, esas filas no se dibujan
        # (pero los clips siguen renderizándose en barras → afectan al show).
        self._show_bars       = True   # tracks 0-9 (barras físicas)
        self._show_groups     = True   # grupos simples (IZQ, DER, ...)
        self._show_group_sets = True   # group_sets (TODO, BORDES+CENTRO)
        self._show_fixtures   = True   # fixture lanes (v1.8 F2)
        # Layers visibles. Por defecto todos los 4 layers están activos.
        self._visible_layers: set = {0, 1, 2, 3, 4, 5, 6, 7}

        # ── Mute / Solo por track (estilo FL Studio) ──────────────────
        # _muted: tracks silenciados → clips no se renderizan ni envían
        # Art-Net pero sí se dibujan en pantalla (con look "deshabilitado").
        # _solo: si hay tracks en solo, SOLO esos se renderizan; el resto
        # queda muteado implícitamente.
        self._muted_tracks: set = set()
        self._solo_tracks:  set = set()

        # ── Loop region (estilo FL Studio: Shift+drag en ruler) ──────
        # Si están definidas, al reproducir y llegar a loop_end_ms,
        # el audio salta a loop_start_ms automáticamente.
        self._loop_start_ms: Optional[int] = None
        self._loop_end_ms:   Optional[int] = None
        self._loop_drag_start_ms: Optional[int] = None  # estado durante drag

        # Scrub (audio)
        self._scrubbing = False

        # Layer height cache {track: n_layers}
        self._track_layers: Dict[int, int] = {}

        # Bookmarks numéricos (atajos Ctrl+0-9): slot → time_ms
        self.bookmarks: Dict[int, int] = {}
        # Time markers libres (estilo FL Studio): lista de {time_ms, name, color}
        self.time_markers: list = []

        self._cursor_line = None

        sc = QGraphicsScene(self)
        self.setScene(sc); self.scene_obj = sc
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setBackgroundBrush(QBrush(C_BG))
        self.setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._rebuild_scene()
        self._update_snap_pts()
        # Reconstruir al hacer scroll (viewport culling necesita esto),
        # con throttle (~30ms) para no rebuild cada pixel.
        self._scroll_rebuild_timer = QTimer(self)
        self._scroll_rebuild_timer.setSingleShot(True)
        self._scroll_rebuild_timer.setInterval(35)
        self._scroll_rebuild_timer.timeout.connect(self._rebuild_scene)
        def _on_h_scroll(v):
            # Mover el header FIJO en cada scroll (instant, no throttled)
            grp = getattr(self, '_header_group', None)
            if grp is not None:
                try:
                    grp.setX(v)
                except RuntimeError:
                    self._header_group = None
            # Y agendar rebuild diferido para que el viewport culling se actualice
            self._scroll_rebuild_timer.start()
        self.horizontalScrollBar().valueChanged.connect(_on_h_scroll)

    # ── Coordinate helpers ────────────────────────────────────────────────
    def time_to_x(self, t_s: float) -> float:
        return HEADER_W + t_s * self.px_per_sec

    def x_to_time(self, x: float) -> float:
        return max(0.0, (x - HEADER_W) / self.px_per_sec)

    # ── Filtros de vista (qué tracks/layers se muestran) ─────────────────
    def _track_is_visible(self, track: int) -> bool:
        """¿Se dibuja este track con los filtros actuales?"""
        if track < 0:
            return False  # track=-1 (channel clips no mapeados) → no pintar
        if track < NUM_TRACKS:
            return self._show_bars
        n_groups = len(self._ordered_groups())
        fixture_start = NUM_TRACKS + n_groups
        if track >= fixture_start:
            return self._show_fixtures  # fixture lane
        # Es virtual de grupo: distinguir grupo simple vs group_set
        idx = track - NUM_TRACKS
        groups = self._ordered_groups()
        if not (0 <= idx < len(groups)):
            return False
        g = groups[idx]
        return self._show_group_sets if g.is_set else self._show_groups

    def _layer_is_visible(self, layer: int) -> bool:
        return layer in self._visible_layers

    def _track_is_audible(self, track: int) -> bool:
        """¿Este track produce salida visible/Art-Net? Aplica mute/solo."""
        if self._solo_tracks:
            return track in self._solo_tracks
        return track not in self._muted_tracks

    def _toggle_mute(self, track: int):
        if track in self._muted_tracks:
            self._muted_tracks.discard(track)
        else:
            self._muted_tracks.add(track)
        self._rebuild_scene()

    def _toggle_solo(self, track: int):
        if track in self._solo_tracks:
            self._solo_tracks.discard(track)
        else:
            self._solo_tracks.add(track)
        self._rebuild_scene()

    # ── Fixture lanes (v1.8 F2) ──────────────────────────────────────────
    # Tracks NUM_TRACKS+len(groups)..  = una lane por fixture no-LED.
    # Los channel clips (category!='pixel', scope='fixture:<id>') se mapean aquí.

    _FIXTURE_CAT_COLORS = {
        'position':  '#e06c30',
        'color':     '#5b8dd9',
        'intensity': '#d4b840',
        'optical':   '#4caf82',
        'strobe':    '#d94040',
    }

    def _ordered_fixture_lanes(self):
        """Fixtures no-LED del rig, en orden estable."""
        rig = getattr(self, 'fixture_rig', None)
        if not rig:
            return []
        return [fx for fx in rig.fixtures if fx.profile_id != 'wled_strip_93']

    def _fixture_track_start(self) -> int:
        """Índice del primer track de fixture lane."""
        return NUM_TRACKS + len(self._ordered_groups())

    # ── Tracks virtuales de grupos ────────────────────────────────────────
    # Track 0..NUM_TRACKS-1 = barras físicas. NUM_TRACKS..NUM_TRACKS+len(simple_groups)-1
    # = grupos simples (IZQ, DER, etc.). Después los group_sets.
    def _ordered_groups(self):
        """Lista de grupos en el orden visual: primero simples, luego sets."""
        groups = getattr(self.timeline, 'groups', []) or []
        simple = [g for g in groups if not g.is_set]
        sets_  = [g for g in groups if g.is_set]
        return simple + sets_

    def _total_tracks(self) -> int:
        n_fix = len(self._ordered_fixture_lanes()) if self._show_fixtures else 0
        return NUM_TRACKS + len(self._ordered_groups()) + n_fix

    def _is_virtual_track(self, track: int) -> bool:
        return track >= NUM_TRACKS

    def _scope_for_virtual_track(self, track: int):
        """Dado un índice de track virtual, devuelve 'group:X' o 'group_set:X'."""
        if track < NUM_TRACKS:
            return None
        idx = track - NUM_TRACKS
        groups = self._ordered_groups()
        if 0 <= idx < len(groups):
            g = groups[idx]
            return f'group_set:{g.name}' if g.is_set else f'group:{g.name}'
        return None

    def _virtual_track_for_scope(self, scope: str):
        """Inversa: scope='group:IZQ' → índice de track virtual."""
        if not isinstance(scope, str):
            return None
        if not (scope.startswith('group:') or scope.startswith('group_set:')):
            return None
        name = scope.split(':', 1)[1]
        for i, g in enumerate(self._ordered_groups()):
            if g.name == name:
                return NUM_TRACKS + i
        return None

    def _visual_track_of_clip(self, clip: Clip) -> int:
        """Dónde se dibuja el clip en el timeline. Cacheado por clip identity."""
        # Cache sobre el propio objeto Clip para evitar lookup repetido
        cached = getattr(clip, '_vt_cached', None)
        n_groups = len(self._ordered_groups())
        n_fixtures = len(self._ordered_fixture_lanes())
        cache_key = (clip.scope, clip.track,
                     len(getattr(self.timeline, 'groups', []) or []),
                     n_fixtures)
        if cached is not None and cached[0] == cache_key:
            return cached[1]

        # Channel clips (category != 'pixel') → fixture lane
        if getattr(clip, 'category', 'pixel') != 'pixel':
            scope = getattr(clip, 'scope', '')
            if scope.startswith('fixture:'):
                fx_id = scope.split(':', 1)[1]
                lanes = self._ordered_fixture_lanes()
                for i, fx in enumerate(lanes):
                    if fx.fixture_id == fx_id:
                        vt = NUM_TRACKS + n_groups + i
                        try:
                            clip._vt_cached = (cache_key, vt)
                        except Exception:
                            pass
                        return vt
            return -2  # fixture no encontrado → no pintar

        vt = self._virtual_track_for_scope(clip.scope)
        if vt is None:
            vt = clip.track
        try:
            clip._vt_cached = (cache_key, vt)
        except Exception:
            pass
        return vt

    def _prebuild_layers_cache(self):
        """Build layers cache in a single O(clips) pass instead of O(tracks×clips)."""
        layers_by_vtrack = {}
        layers_by_ptrack = {}
        for c in self.timeline.clips:
            vt = self._visual_track_of_clip(c)
            if vt not in layers_by_vtrack:
                layers_by_vtrack[vt] = set()
            layers_by_vtrack[vt].add(c.layer)
            if self._virtual_track_for_scope(getattr(c, 'scope', '')) is None:
                pt = c.track
                if pt not in layers_by_ptrack:
                    layers_by_ptrack[pt] = set()
                layers_by_ptrack[pt].add(c.layer)
        merged = {}
        for t, lset in layers_by_vtrack.items():
            merged[t] = max(1, max(lset) + 1) if lset else 1
        for t, lset in layers_by_ptrack.items():
            if t not in merged:
                merged[t] = max(1, max(lset) + 1) if lset else 1
        self._layers_cache = merged

    def _build_track_y_cache(self):
        """Pre-compute Y start position for every track in one O(total_tracks) pass.
        Also sets _cached_total_height. Must be called after _prebuild_layers_cache()."""
        n_tracks = (NUM_TRACKS + len(self._ordered_groups()) +
                    (len(self._ordered_fixture_lanes()) if self._show_fixtures else 0))
        cache = {}
        y = float(WAVEFORM_H + RULER_H)
        for t in range(n_tracks):
            cache[t] = y
            if self._track_is_visible(t):
                n = self._layers_cache.get(t, 1)
                y += n * BASE_TRACK_H + TRACK_GAP
        self._track_y_cache = cache
        self._cached_total_height = y + 10

    def _track_layers_count(self, track: int) -> int:
        """How many visible layers does this track currently have?"""
        # Cache: si ya calculamos, reusar
        cache = getattr(self, '_layers_cache', None)
        if cache is not None and track in cache:
            return cache[track]
        # Para tracks virtuales: contar clips cuyo visual_track es este
        if track >= NUM_TRACKS:
            layers = set()
            for c in self.timeline.clips:
                if self._visual_track_of_clip(c) == track:
                    layers.add(c.layer)
            n = max(1, max(layers) + 1) if layers else 1
        else:
            # Tracks físicos: solo clips per_bar (los de grupo van a virtual)
            layers = set()
            for c in self.timeline.clips:
                if c.track == track and self._virtual_track_for_scope(getattr(c, 'scope', '')) is None:
                    layers.add(c.layer)
            n = max(1, max(layers) + 1) if layers else 1
        if cache is not None:
            cache[track] = n
        return n

    def _track_y_start(self, track: int) -> float:
        """Y position of the top of track. O(1) when cache is warm."""
        c = getattr(self, '_track_y_cache', None)
        if c is not None:
            return c.get(track, float(WAVEFORM_H + RULER_H))
        # Fallback before first rebuild
        y = WAVEFORM_H + RULER_H
        for t in range(track):
            if not self._track_is_visible(t):
                continue
            y += self._track_layers_count(t) * BASE_TRACK_H + TRACK_GAP
        return y

    def _track_layer_y(self, track: int, layer: int) -> float:
        return self._track_y_start(track) + layer * BASE_TRACK_H

    def _total_height(self) -> float:
        y = WAVEFORM_H + RULER_H
        for t in range(self._total_tracks()):
            if not self._track_is_visible(t):
                continue
            y += self._track_layers_count(t) * BASE_TRACK_H + TRACK_GAP
        return y + 10

    def y_to_track_layer(self, y: float):
        """Returns (track, layer) or (-1, 0)."""
        cy = WAVEFORM_H + RULER_H
        for t in range(self._total_tracks()):
            if not self._track_is_visible(t):
                continue
            n = self._track_layers_count(t)
            h = n * BASE_TRACK_H
            if cy <= y < cy + h:
                rel   = y - cy
                layer = int(rel // BASE_TRACK_H)
                return t, min(layer, n - 1)
            cy += h + TRACK_GAP
        return -1, 0

    def ms_to_bar_beat(self, ms: float):
        bar  = int(ms / self.bar_ms)
        beat = int((ms % self.bar_ms) / self.beat_ms)
        return bar + 1, beat + 1

    # ── Next free layer for a time range on a track ────────────────────────
    def _next_free_layer(self, track: int, start_ms: int, end_ms: int) -> int:
        occupied = set()
        for c in self.timeline.clips:
            if c.track != track: continue
            if c.start_ms < end_ms and c.end_ms > start_ms:
                occupied.add(c.layer)
        layer = 0
        while layer in occupied:
            layer += 1
        return layer

    # ── Snap ─────────────────────────────────────────────────────────────
    def _update_snap_pts(self):
        pts = {0, self.timeline.duration_ms}
        for t in self.markers.get('beats', []):    pts.add(int(t * 1000))
        for t in self.markers.get('sections', []): pts.add(int(t * 1000))
        for c in self.timeline.clips:
            pts.add(c.start_ms); pts.add(c.end_ms)
        t = 0
        while t <= self.timeline.duration_ms:
            pts.add(int(t)); t += self.beat_ms
        self._snap_pts = sorted(pts)

    def _grid_step_ms(self) -> float:
        """Subdivisión en ms del grid actual."""
        if self._snap_grid == 'bar':
            return self.bar_ms
        if self._snap_grid == 'beat':
            return self.beat_ms
        if self._snap_grid == '1/4':
            return self.beat_ms / 2.0   # mitad de beat
        if self._snap_grid == '1/8':
            return self.beat_ms / 4.0
        if self._snap_grid == '1/16':
            return self.beat_ms / 8.0
        return 0.0   # off

    def _snap(self, ms: int) -> int:
        if not self._snap_on:
            return ms
        candidates = []
        # 1) Candidato del grid (cuantización musical)
        step = self._grid_step_ms()
        if step > 0:
            n = round(ms / step)
            candidates.append(int(n * step))
        # 2) Candidatos de markers/clips precomputados
        if self._snap_pts:
            candidates.append(min(self._snap_pts, key=lambda p: abs(p - ms)))
        if not candidates:
            return ms
        best = min(candidates, key=lambda p: abs(p - ms))
        return best if abs(best - ms) <= SNAP_RADIUS_MS else ms

    # ── Expand clip to adjacent timing marks ─────────────────────────────
    def expand_to_prev_mark(self):
        for c in self.selected_clips:
            if c.locked: continue
            prev = max((p for p in self._snap_pts if p < c.start_ms), default=0)
            c.start_ms = prev
        self._rebuild_scene()

    def expand_to_next_mark(self):
        for c in self.selected_clips:
            if c.locked: continue
            nxt = min((p for p in self._snap_pts if p > c.end_ms), default=self.timeline.duration_ms)
            c.end_ms = nxt
        self._rebuild_scene()

    # ── Zoom ─────────────────────────────────────────────────────────────
    def set_zoom(self, pps: float):
        self.px_per_sec = max(2.0, min(800.0, pps))
        self._rebuild_scene()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            f = 1.18 if event.angleDelta().y() > 0 else 1.0 / 1.18
            self.set_zoom(self.px_per_sec * f)
        else:
            super().wheelEvent(event)

    # ── Scene ─────────────────────────────────────────────────────────────
    def _rebuild_scene(self):
        # Nullear las referencias ANTES de borrar el scene, para que cualquier
        # señal/evento que se dispare durante clear() no acceda a objetos ya eliminados
        self._cursor_line  = None
        self._rb_rect_item = None
        self._draw_item    = None
        # Pre-construir caches: O(clips) layers + O(tracks) Y positions
        self._prebuild_layers_cache()
        self._build_track_y_cache()   # también setea _cached_total_height
        self.scene_obj.clear()

        dur_s   = self.timeline.duration_ms / 1000.0
        total_w = self.time_to_x(dur_s) + 80
        total_h = self._cached_total_height
        self.scene_obj.setSceneRect(0, 0, total_w, total_h)

        self._draw_track_bgs(total_w)
        self._draw_beat_grid(total_w)
        self._draw_waveform()
        self._draw_ruler(total_w)
        self._draw_markers()
        self._draw_bookmarks()
        self._draw_track_headers()
        # ── Viewport culling: solo dibujar clips visibles ───────────────
        # Calculamos el rango de tiempo visible (con margen) y filtramos.
        try:
            sb = self.horizontalScrollBar()
            vw = self.viewport().width()
            visible_x_lo = max(0, sb.value())
            visible_x_hi = sb.value() + vw + 200   # margen para evitar pop-in
            t_lo_ms = int(self.x_to_time(visible_x_lo) * 1000) - 200
            t_hi_ms = int(self.x_to_time(visible_x_hi) * 1000) + 200
        except Exception:
            t_lo_ms, t_hi_ms = 0, self.timeline.duration_ms + 1
        for clip in self.timeline.clips:
            # Skip clips totalmente fuera del viewport
            if clip.end_ms < t_lo_ms or clip.start_ms > t_hi_ms:
                continue
            self._draw_clip(clip)
        self._draw_cursor()

    def _draw_track_bgs(self, total_w):
        for t in range(NUM_TRACKS):
            n = self._track_layers_count(t)
            for layer in range(n):
                y   = self._track_layer_y(t, layer)
                col = (C_TRACK_EVEN if t % 2 == 0 else C_TRACK_ODD) if layer == 0 else C_TRACK_LAYER
                bg  = QGraphicsRectItem(HEADER_W, y, total_w - HEADER_W, BASE_TRACK_H)
                bg.setBrush(QBrush(col)); bg.setPen(QPen(Qt.NoPen)); bg.setZValue(0)
                self.scene_obj.addItem(bg)
            # separator after last layer
            y_sep = self._track_y_start(t) + n * BASE_TRACK_H
            sep   = QGraphicsLineItem(0, y_sep, total_w, y_sep)
            sep.setPen(QPen(QColor(38, 38, 55), 1)); sep.setZValue(1)
            self.scene_obj.addItem(sep)

    def _draw_beat_grid(self, total_w):
        max_y  = getattr(self, '_cached_total_height', None) or self._total_height()
        min_y  = self._track_layer_y(0, 0)
        px_pb  = self.beat_ms / 1000.0 * self.px_per_sec
        if px_pb < 3: return
        dur_ms = self.timeline.duration_ms
        # Viewport culling: only draw beats in the visible horizontal range
        try:
            sb = self.horizontalScrollBar()
            vis_lo = sb.value()
            vis_hi = sb.value() + self.viewport().width()
            t_lo = max(0.0, self.x_to_time(vis_lo) * 1000.0 - self.beat_ms * 2)
            t_hi = min(float(dur_ms), self.x_to_time(vis_hi) * 1000.0 + self.beat_ms * 2)
        except Exception:
            t_lo, t_hi = 0.0, float(dur_ms)
        beat_n = max(0, int(t_lo / self.beat_ms))
        t_ms   = beat_n * self.beat_ms
        while t_ms <= t_hi:
            x  = self.time_to_x(t_ms / 1000.0)
            ln = QGraphicsLineItem(x, min_y, x, max_y)
            ln.setPen(QPen(C_GRID_BAR if beat_n % 4 == 0 else C_GRID_BEAT, 1))
            ln.setZValue(2); self.scene_obj.addItem(ln)
            beat_n += 1; t_ms = beat_n * self.beat_ms

    def _draw_waveform(self):
        bg = QGraphicsRectItem(HEADER_W, 0, self.sceneRect().width()-HEADER_W, WAVEFORM_H)
        bg.setBrush(QBrush(QColor(14,14,22))); bg.setPen(QPen(Qt.NoPen)); bg.setZValue(3)
        self.scene_obj.addItem(bg)
        peaks = self.waveform.peaks; n = len(peaks); dur = self.waveform.duration_s
        if dur <= 0 or n == 0: return
        cy = WAVEFORM_H / 2; path = QPainterPath()
        step = max(1, int(1.0 / self.px_per_sec * 100))
        # Viewport culling: only draw the visible horizontal range
        try:
            sb = self.horizontalScrollBar()
            x_lo = max(0, sb.value() - HEADER_W)
            x_hi = sb.value() + self.viewport().width() - HEADER_W + 50
        except Exception:
            x_lo = 0
            x_hi = int(self.sceneRect().width() - HEADER_W)
        for i in range(int(x_lo), int(x_hi), step):
            t = i / self.px_per_sec
            if t > dur: break
            pi = int((t/dur)*n)
            if pi >= n: break
            amp = peaks[pi] * (WAVEFORM_H * 0.44)
            x = HEADER_W + i
            path.moveTo(x, cy-amp); path.lineTo(x, cy+amp)
        self.scene_obj.addPath(path, QPen(C_WAVEFORM, 1)).setZValue(4)
        ln = QGraphicsLineItem(HEADER_W, WAVEFORM_H, self.sceneRect().width(), WAVEFORM_H)
        ln.setPen(QPen(QColor(45,45,65), 1)); ln.setZValue(5)
        self.scene_obj.addItem(ln)

    def _draw_ruler(self, total_w):
        ry = WAVEFORM_H
        bg = QGraphicsRectItem(HEADER_W, ry, total_w-HEADER_W, RULER_H)
        bg.setBrush(QBrush(C_RULER_BG)); bg.setPen(QPen(Qt.NoPen)); bg.setZValue(5)
        self.scene_obj.addItem(bg)
        # Loop region (banda amarilla)
        if self._loop_start_ms is not None and self._loop_end_ms is not None \
                and self._loop_end_ms > self._loop_start_ms:
            lx0 = self.time_to_x(self._loop_start_ms / 1000.0)
            lx1 = self.time_to_x(self._loop_end_ms / 1000.0)
            loop_rect = QGraphicsRectItem(lx0, ry, max(2.0, lx1 - lx0), RULER_H)
            loop_rect.setBrush(QBrush(QColor(255, 210, 60, 110)))
            loop_rect.setPen(QPen(QColor(255, 210, 60), 1))
            loop_rect.setZValue(6)
            self.scene_obj.addItem(loop_rect)
        dur_ms = self.timeline.duration_ms
        # Viewport culling: solo ticks visibles
        try:
            _sb = self.horizontalScrollBar()
            _vis_lo = _sb.value(); _vis_hi = _vis_lo + self.viewport().width()
            _r_t_lo = max(0.0, self.x_to_time(_vis_lo) * 1000.0)
            _r_t_hi = min(float(dur_ms), self.x_to_time(_vis_hi) * 1000.0)
        except Exception:
            _r_t_lo, _r_t_hi = 0.0, float(dur_ms)
        if self.ruler_mode == 'bars':
            px_pb = self.beat_ms / 1000.0 * self.px_per_sec
            bar_n = max(0, int(_r_t_lo / self.bar_ms)); t_ms = bar_n * self.bar_ms
            while t_ms <= min(_r_t_hi + self.bar_ms, dur_ms):
                x  = self.time_to_x(t_ms / 1000.0)
                ln = QGraphicsLineItem(x, ry, x, ry+RULER_H)
                ln.setPen(QPen(C_RULER_BAR, 1)); ln.setZValue(7); self.scene_obj.addItem(ln)
                if px_pb * 4 >= 18:
                    tx = QGraphicsTextItem(str(bar_n+1))
                    tx.setDefaultTextColor(C_RULER_BAR)
                    tx.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
                    tx.setPos(x+2, ry+2); tx.setZValue(8); self.scene_obj.addItem(tx)
                bar_n += 1; t_ms = bar_n * self.bar_ms
            if px_pb >= 6:
                beat_n = max(0, int(_r_t_lo / self.beat_ms)); t_ms = beat_n * self.beat_ms
                while t_ms <= min(_r_t_hi + self.beat_ms, dur_ms):
                    if beat_n % 4 != 0:
                        x  = self.time_to_x(t_ms/1000.0)
                        ln = QGraphicsLineItem(x, ry+RULER_H//2, x, ry+RULER_H)
                        ln.setPen(QPen(C_RULER_BEAT,1)); ln.setZValue(7); self.scene_obj.addItem(ln)
                        if px_pb >= 22:
                            t2 = QGraphicsTextItem(f".{beat_n%4+1}")
                            t2.setDefaultTextColor(C_RULER_BEAT)
                            t2.setFont(FONT_MONO)
                            t2.setPos(x+1, ry+RULER_H//2); t2.setZValue(8); self.scene_obj.addItem(t2)
                    beat_n += 1; t_ms = beat_n * self.beat_ms
        else:
            tick_s = 1.0
            pps = self.px_per_sec
            if pps < 5: tick_s=60
            elif pps<12: tick_s=10
            elif pps<35: tick_s=5
            elif pps<80: tick_s=2
            t = (int(_r_t_lo / 1000.0 / tick_s)) * tick_s
            while t <= min(_r_t_hi / 1000.0 + tick_s, dur_ms / 1000.0):
                x  = self.time_to_x(t)
                ln = QGraphicsLineItem(x, ry, x, ry+RULER_H)
                ln.setPen(QPen(C_RULER_BAR,1)); ln.setZValue(7); self.scene_obj.addItem(ln)
                m,s = int(t)//60, int(t)%60
                tx = QGraphicsTextItem(f"{m}:{s:02d}" if m else f"{int(t)}s")
                tx.setDefaultTextColor(C_RULER_BAR); tx.setFont(FONT_MONO)
                tx.setPos(x+2, ry+3); tx.setZValue(8); self.scene_obj.addItem(tx)
                t += tick_s
        ln = QGraphicsLineItem(HEADER_W, ry+RULER_H, self.sceneRect().width(), ry+RULER_H)
        ln.setPen(QPen(QColor(50,50,72),1)); ln.setZValue(6); self.scene_obj.addItem(ln)

    def _draw_markers(self):
        total_h = getattr(self, '_cached_total_height', None) or self._total_height()
        # Viewport culling for high-density markers (kicks/beats)
        try:
            _sb = self.horizontalScrollBar()
            _m_t_lo = max(0.0, self.x_to_time(_sb.value()) - 0.1)
            _m_t_hi = self.x_to_time(_sb.value() + self.viewport().width()) + 0.1
        except Exception:
            _m_t_lo, _m_t_hi = 0.0, self.timeline.duration_ms / 1000.0 + 1
        for t in self.markers.get('sections', []):
            x  = self.time_to_x(t)
            ln = QGraphicsLineItem(x, 0, x, total_h)
            ln.setPen(QPen(C_SECTION, 2)); ln.setZValue(9); self.scene_obj.addItem(ln)
            lbl = QGraphicsTextItem(f"§{int(t)}s")
            lbl.setDefaultTextColor(C_SECTION); lbl.setFont(QFont("Consolas",7,QFont.Bold))
            lbl.setPos(x+2, WAVEFORM_H+RULER_H-14); lbl.setZValue(10); self.scene_obj.addItem(lbl)
        for t in self.markers.get('kicks', []):
            if t < _m_t_lo or t > _m_t_hi: continue
            x  = self.time_to_x(t)
            ln = QGraphicsLineItem(x, 0, x, WAVEFORM_H)
            ln.setPen(QPen(C_KICK,1)); ln.setZValue(4); self.scene_obj.addItem(ln)
        for t in self.markers.get('beats', []):
            if t < _m_t_lo or t > _m_t_hi: continue
            x  = self.time_to_x(t)
            ln = QGraphicsLineItem(x, WAVEFORM_H-8, x, WAVEFORM_H)
            ln.setPen(QPen(C_BEAT_MARK,1)); ln.setZValue(5); self.scene_obj.addItem(ln)

    def _draw_bookmarks(self):
        total_h = getattr(self, '_cached_total_height', None) or self._total_height()
        for slot, t_ms in self.bookmarks.items():
            x   = self.time_to_x(t_ms/1000.0)
            ln  = QGraphicsLineItem(x, WAVEFORM_H, x, total_h)
            ln.setPen(QPen(C_BOOKMARK, 1, Qt.DotLine)); ln.setZValue(8); self.scene_obj.addItem(ln)
            bm  = QGraphicsTextItem(str(slot))
            bm.setDefaultTextColor(C_BOOKMARK); bm.setFont(QFont("Consolas",8,QFont.Bold))
            bm.setPos(x+2, WAVEFORM_H+2); bm.setZValue(9); self.scene_obj.addItem(bm)

        # Time markers nombrables (FL Studio style)
        for mk in self.time_markers:
            x = self.time_to_x(mk['time_ms'] / 1000.0)
            col = QColor(mk.get('color', '#ff9933'))
            ln = QGraphicsLineItem(x, WAVEFORM_H, x, self._total_height())
            ln.setPen(QPen(col, 1, Qt.DashLine))
            ln.setZValue(8); self.scene_obj.addItem(ln)
            # Pequeña flag triangular en la parte superior del ruler
            flag_bg = QGraphicsRectItem(x, WAVEFORM_H, 80, 13)
            flag_bg.setBrush(QBrush(col)); flag_bg.setPen(QPen(QColor(20, 20, 30), 1))
            flag_bg.setZValue(9); self.scene_obj.addItem(flag_bg)
            txt = QGraphicsTextItem(mk.get('name', '?')[:14])
            txt.setDefaultTextColor(QColor(20, 20, 30))
            txt.setFont(QFont("Segoe UI", 7, QFont.Bold))
            txt.setPos(x + 3, WAVEFORM_H - 1); txt.setZValue(10)
            self.scene_obj.addItem(txt)

    def _draw_track_headers(self):
        ordered_groups = self._ordered_groups()
        # Lista de items que conforman el header. Se agrupan al final para
        # poder moverlos juntos al hacer scroll horizontal (frozen column).
        header_items = []
        def _add(it):
            it.setZValue(it.zValue() + 30)  # asegurar que tapen los clips
            self.scene_obj.addItem(it)
            header_items.append(it)
            return it

        fixture_start = self._fixture_track_start()
        fixture_lanes = self._ordered_fixture_lanes()

        for t in range(self._total_tracks()):
            if not self._track_is_visible(t):
                continue
            n  = self._track_layers_count(t)
            y  = self._track_y_start(t)
            th = n * BASE_TRACK_H
            is_fixture_lane = (t >= fixture_start)
            is_virtual = (t >= NUM_TRACKS)

            # ── Separador visual antes del primer fixture lane ───────────
            if is_fixture_lane and t == fixture_start:
                sep = QGraphicsRectItem(0, y - 4, HEADER_W, 4)
                sep.setBrush(QBrush(QColor(0xa7, 0x79, 0xf0, 60)))  # acc-2 dim
                sep.setPen(QPen(Qt.NoPen))
                sep.setZValue(10); _add(sep)
                lbl_sep = QGraphicsTextItem("FIXTURES")
                lbl_sep.setDefaultTextColor(QColor(0xa7, 0x79, 0xf0))  # acc-2
                lbl_sep.setFont(QFont("Segoe UI", 7, QFont.Bold))
                lbl_sep.setPos(COLOR_STRIP + 4, y - 14)
                lbl_sep.setZValue(11); _add(lbl_sep)

            # ── Fondo del header ─────────────────────────────────────────
            if is_fixture_lane:
                bg_color = QColor(0x20, 0x1e, 0x2a)   # bg-2 con tinte violeta
            elif is_virtual:
                bg_color = QColor(0x1e, 0x1d, 0x28)
            else:
                bg_color = C_HEADER_BG
            bg = QGraphicsRectItem(0, y, HEADER_W, th)
            bg.setBrush(QBrush(bg_color)); bg.setPen(QPen(QColor(0x36, 0x3c, 0x45), 1))
            bg.setZValue(10); _add(bg)

            # ── Strip de color a la izquierda ────────────────────────────
            if is_fixture_lane:
                strip_color = QColor(0xa7, 0x79, 0xf0)  # acc-2 violeta
            elif is_virtual:
                g = ordered_groups[t - NUM_TRACKS]
                strip_color = QColor(g.color)
            else:
                strip_color = QColor(TRACK_STRIP_COLORS[t])
            strip = QGraphicsRectItem(0, y, COLOR_STRIP, th)
            strip.setBrush(QBrush(strip_color)); strip.setPen(QPen(Qt.NoPen))
            strip.setZValue(11); _add(strip)

            # ── Nombre del track ─────────────────────────────────────────
            if is_fixture_lane:
                fx = fixture_lanes[t - fixture_start]
                name = f"⬡ {fx.label or fx.fixture_id}"
            elif is_virtual:
                g = ordered_groups[t - NUM_TRACKS]
                icon = '★' if g.is_set else '◆'
                name = f"{icon} {g.name}"
            else:
                name = f"Bar {t:02d}" + (f"  [{n}]" if n > 1 else "")
            # Elidir texto si es muy largo para el header
            font = QFont("Segoe UI", 9, QFont.Bold)
            fm = QFontMetrics(font)
            max_width = HEADER_W - COLOR_STRIP - 10
            name = fm.elidedText(name, Qt.ElideRight, max_width)
            txt  = QGraphicsTextItem(name)
            txt.setDefaultTextColor(C_HEADER_TEXT); txt.setFont(font)
            txt.setPos(COLOR_STRIP+5, y+(th-16)/2); txt.setZValue(12); _add(txt)

            # Layer labels on right of header
            if n > 1:
                for layer in range(n):
                    ly = y + layer * BASE_TRACK_H + 2
                    lt = QGraphicsTextItem(f"L{layer}")
                    lt.setDefaultTextColor(QColor(0x5a, 0x60, 0x6b)); lt.setFont(FONT_MONO)
                    lt.setPos(HEADER_W-24, ly); lt.setZValue(12); _add(lt)

            # Para tracks físicos: badges de los grupos a los que pertenecen
            if not is_virtual and ordered_groups:
                bx = COLOR_STRIP + 5; by = y + th - 9
                for g in ordered_groups:
                    if not g.is_set and t in g.bars:
                        sq = QGraphicsRectItem(bx, by, 7, 7)
                        sq.setBrush(QBrush(QColor(g.color))); sq.setPen(QPen(Qt.NoPen))
                        sq.setZValue(13); _add(sq)
                        bx += 9
                        if bx > HEADER_W - 12: break

            # Botones Mute / Solo (estilo FL Studio) en esquina inferior-derecha
            btn_w, btn_h = 16, 12
            m_y = y + th - btn_h - 1
            m_x = HEADER_W - btn_w * 2 - 4
            s_x = HEADER_W - btn_w - 2
            is_muted = t in self._muted_tracks
            is_solo  = t in self._solo_tracks
            m_bg = QColor(180, 60, 60) if is_muted else QColor(50, 50, 70)
            s_bg = QColor(220, 180, 50) if is_solo else QColor(50, 50, 70)
            m_btn = QGraphicsRectItem(m_x, m_y, btn_w, btn_h)
            m_btn.setBrush(QBrush(m_bg))
            m_btn.setPen(QPen(QColor(20, 20, 30), 1))
            m_btn.setZValue(14)
            m_btn.setData(0, ('mute', t))   # tag para detectar el clic
            _add(m_btn)
            m_txt = QGraphicsTextItem("M"); m_txt.setDefaultTextColor(QColor(240, 240, 240))
            m_txt.setFont(QFont("JetBrains Mono", 7, QFont.Bold))
            m_txt.setPos(m_x + 4, m_y - 1); m_txt.setZValue(15)
            _add(m_txt)
            s_btn = QGraphicsRectItem(s_x, m_y, btn_w, btn_h)
            s_btn.setBrush(QBrush(s_bg))
            s_btn.setPen(QPen(QColor(20, 20, 30), 1))
            s_btn.setZValue(14)
            s_btn.setData(0, ('solo', t))
            _add(s_btn)
            s_txt = QGraphicsTextItem("S"); s_txt.setDefaultTextColor(QColor(40, 40, 50))
            s_txt.setFont(QFont("JetBrains Mono", 7, QFont.Bold))
            s_txt.setPos(s_x + 5, m_y - 1); s_txt.setZValue(15)
            _add(s_txt)

        # ── Frozen header: agrupar todo y permitir moverlo al scroll ─────
        if header_items:
            group = self.scene_obj.createItemGroup(header_items)
            group.setZValue(50)   # tapa clips/cursor
            # Posicionar al scroll actual ya (al rebuild)
            try:
                group.setX(self.horizontalScrollBar().value())
            except Exception:
                pass
            self._header_group = group
        else:
            self._header_group = None

    def _draw_clip(self, clip: Clip):
        # Si el track destino o la capa están ocultos por filtros, no dibujarlo.
        vt  = self._visual_track_of_clip(clip)
        if not self._track_is_visible(vt) or not self._layer_is_visible(clip.layer):
            return
        x   = self.time_to_x(clip.start_ms / 1000.0)
        y   = self._track_layer_y(vt, clip.layer)
        w   = max(4.0, (clip.end_ms - clip.start_ms) / 1000.0 * self.px_per_sec)
        h   = BASE_TRACK_H - 2
        sel = clip in self.selected_clips

        # ── Determinar color de familia ───────────────────────────────────────
        cat = getattr(clip, 'category', 'pixel')
        is_channel = (cat != 'pixel')

        if is_channel:
            # Clips de canal: color por categoría DMX
            cat_hex = self._FIXTURE_CAT_COLORS.get(cat, '#808090')
            fam_col = QColor(cat_hex)
        else:
            # Clips de pixel: deducir familia del effect_id para el color
            # (clip.color puede estar en cualquier formato hex o ser el color del efecto)
            effect_name = (clip.label or "").lower()
            fam_key = 'wave'  # default
            for k in FAMILY_COLORS:
                if k in effect_name:
                    fam_key = k
                    break
            # Si clip.color ya tiene información útil, usarlo; si no, usar familia
            raw_col = QColor(clip.color) if clip.color else QColor(FAMILY_COLORS[fam_key])
            # Intentar mapear el color del clip a su familia más cercana
            fam_col = raw_col

        # Fondo del clip: mezcla 32% color familia con bg-2 (#1d2127)
        bg2 = QColor(0x1d, 0x21, 0x27)
        if getattr(clip, 'muted', False):
            fill_col = QColor(0x27, 0x2c, 0x34)  # bg-3 desaturado
        else:
            mix_r = int(fam_col.red()   * 0.28 + bg2.red()   * 0.72)
            mix_g = int(fam_col.green() * 0.28 + bg2.green() * 0.72)
            mix_b = int(fam_col.blue()  * 0.28 + bg2.blue()  * 0.72)
            fill_col = QColor(mix_r, mix_g, mix_b)
            if sel:   fill_col = fill_col.lighter(125)
            if clip.locked: fill_col = fill_col.darker(115)

        # Borde del clip
        now_ms = int(self.current_time_s * 1000)
        is_active = clip.start_ms <= now_ms < clip.end_ms
        if sel:
            border_pen = QPen(C_SEL_BORDER, 2)
        elif is_active:
            border_pen = QPen(C_CURSOR, 1)
        elif clip.locked:
            border_pen = QPen(QColor(0xa7, 0x79, 0xf0, 160), 1)
        else:
            # Borde color familia (semitransparente)
            bc = QColor(fam_col); bc.setAlpha(180)
            border_pen = QPen(bc, 1)

        # ── Fondo del clip ────────────────────────────────────────────────────
        rect = QGraphicsRectItem(x, y+1, w, h)
        rect.setBrush(QBrush(fill_col)); rect.setPen(border_pen)
        rect.setZValue(15); rect.setData(0, clip); self.scene_obj.addItem(rect)

        # ── Barra lateral izquierda de color (3px, color familia full) ────────
        bar_col = QColor(fam_col)
        if getattr(clip, 'muted', False): bar_col = QColor(0x45, 0x4c, 0x57)
        left_bar = QGraphicsRectItem(x, y+1, 3, h)
        left_bar.setBrush(QBrush(bar_col)); left_bar.setPen(QPen(Qt.NoPen))
        left_bar.setZValue(16); left_bar.setData(0, clip); self.scene_obj.addItem(left_bar)

        # lock overlay
        if clip.locked:
            lov = QGraphicsRectItem(x, y+1, w, h)
            lov.setBrush(QBrush(C_LOCK_TINT)); lov.setPen(QPen(Qt.NoPen))
            lov.setZValue(16); self.scene_obj.addItem(lov)
        # muted overlay: línea diagonal y label "M"
        if getattr(clip, 'muted', False):
            diag = QGraphicsLineItem(x, y + 1, x + w, y + h)
            diag.setPen(QPen(QColor(255, 80, 80, 200), 2))
            diag.setZValue(17); self.scene_obj.addItem(diag)
            mlbl = QGraphicsTextItem("MUTE")
            mlbl.setDefaultTextColor(QColor(255, 80, 80))
            mlbl.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
            mlbl.setPos(x + 4, y + (h - 14) / 2); mlbl.setZValue(18)
            self.scene_obj.addItem(mlbl)

        # label — offset de 7px para dejar espacio a la barra lateral
        if w > 28:
            if is_channel:
                eff_name = getattr(clip, 'channel_effect_id', '') or cat
                lbl_text = ("🔒 " if clip.locked else "") + eff_name
            else:
                lbl_text = ("🔒 " if clip.locked else "") + (clip.label or f"#{clip.effect_id}")
            txt = QGraphicsTextItem(lbl_text)
            txt.setDefaultTextColor(QColor(0xf3, 0xf4, 0xf6, 220))
            txt.setFont(QFont("Segoe UI", 8, QFont.Bold))
            txt.setPos(x+7, y+2); txt.setZValue(17); self.scene_obj.addItem(txt)

        # bar:beat sublabel
        if w > 80:
            bar, beat = self.ms_to_bar_beat(clip.start_ms)
            sub = QGraphicsTextItem(f"{bar}:{beat}")
            sub.setDefaultTextColor(QColor(255,255,255,100))
            sub.setFont(FONT_MONO)
            sub.setPos(x+4, y+BASE_TRACK_H-15); sub.setZValue(17); self.scene_obj.addItem(sub)

        # selection badge
        if sel and len(self.selected_clips)>1 and self.selected_clips[0] is clip:
            badge = QGraphicsTextItem(f"×{len(self.selected_clips)}")
            badge.setDefaultTextColor(C_SEL_BORDER)
            badge.setFont(QFont("Segoe UI",8,QFont.Bold))
            badge.setPos(x+w-28, y+3); badge.setZValue(18); self.scene_obj.addItem(badge)

    def _draw_cursor(self):
        x = self.time_to_x(self.current_time_s); maxy = self._total_height()
        sh = QGraphicsLineItem(x+1, 0, x+1, maxy)
        sh.setPen(QPen(QColor(0,0,0,100),2)); sh.setZValue(24); self.scene_obj.addItem(sh)
        ln = QGraphicsLineItem(x, 0, x, maxy)
        ln.setPen(QPen(C_CURSOR,2)); ln.setZValue(25); self.scene_obj.addItem(ln)
        tri = QPainterPath(); tri.moveTo(x-6,WAVEFORM_H); tri.lineTo(x+6,WAVEFORM_H); tri.lineTo(x,WAVEFORM_H+10); tri.closeSubpath()
        self.scene_obj.addPath(tri, QPen(Qt.NoPen), QBrush(C_CURSOR)).setZValue(26)
        self._cursor_line = ln

    def set_current_time(self, t_s: float):
        self.current_time_s = max(0.0, min(t_s, self.timeline.duration_ms/1000.0))
        if self._cursor_line:
            try:
                x = self.time_to_x(self.current_time_s)
                h = getattr(self, '_cached_total_height', None) or self._total_height()
                self._cursor_line.setLine(x, 0, x, h)
            except RuntimeError:
                # Objeto C++ ya eliminado (scene fue limpiado); se recrea en el próximo tick
                self._cursor_line = None

    # ── Clip lookup ───────────────────────────────────────────────────────
    def _clip_at(self, sp):
        for it in self.scene_obj.items(sp):
            c = it.data(0)
            if isinstance(c, Clip):
                rect = it.boundingRect().translated(it.pos())
                return c, sp.x() - rect.left()
        return None, 0.0

    # ── Mouse ──────────────────────────────────────────────────────────────
    def mouseDoubleClickEvent(self, event):
        """Doble-click en el ruler → crear time marker con nombre."""
        sp = self.mapToScene(event.pos())
        if WAVEFORM_H <= sp.y() < WAVEFORM_H + RULER_H and sp.x() > HEADER_W:
            t_ms = int(self.x_to_time(sp.x()) * 1000)
            t_ms = self._snap(t_ms)
            name, ok = QInputDialog.getText(
                self, "Nuevo time marker",
                f"Nombre del marker en {t_ms/1000:.2f}s:")
            if ok and name.strip():
                # Color cíclico para distinguir markers
                palette = ['#ff9933', '#33cc99', '#cc66ff', '#ffcc33',
                           '#ff6666', '#66ccff', '#aaff66', '#ff66aa']
                color = palette[len(self.time_markers) % len(palette)]
                self.time_markers.append({
                    'time_ms': t_ms, 'name': name.strip(), 'color': color,
                })
                self._update_snap_pts()
                self._rebuild_scene()
                return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        sp    = self.mapToScene(event.pos())
        shift = bool(event.modifiers() & Qt.ShiftModifier)
        ctrl  = bool(event.modifiers() & Qt.ControlModifier)

        if event.button() == Qt.RightButton:
            return super().mousePressEvent(event)

        # ── SLICE tool: clic sobre un clip lo divide en dos ───────────────
        if self.tool_mode == TOOL_SLICE and event.button() == Qt.LeftButton:
            clip, _ = self._clip_at(sp)
            if clip is not None and not clip.locked:
                cut_ms = int(self.x_to_time(sp.x()) * 1000)
                cut_ms = self._snap(cut_ms)
                if clip.start_ms < cut_ms < clip.end_ms:
                    self.request_snapshot.emit()
                    new_clip = copy.copy(clip)
                    new_clip.params = dict(clip.params)
                    new_clip.start_ms = cut_ms
                    new_clip.layer = clip.layer
                    clip.end_ms = cut_ms
                    self.timeline.add(new_clip)
                    self._update_snap_pts(); self._rebuild_scene()
                return

        # ── Clicks en botones Mute / Solo del header ──────────────────────
        if sp.x() < HEADER_W:
            it = self.scene_obj.itemAt(sp, self.transform())
            if it is not None:
                tag = it.data(0)
                if isinstance(tag, tuple) and len(tag) == 2:
                    kind, track_idx = tag
                    if kind == 'mute':
                        self._toggle_mute(track_idx); return
                    if kind == 'solo':
                        self._toggle_solo(track_idx); return

        # ── Audio scrub (Ctrl + click on waveform) ────────────────────────
        if ctrl and sp.y() < WAVEFORM_H:
            self._scrubbing = True
            t = self.x_to_time(sp.x())
            self.time_seeked.emit(t); self.set_current_time(t)
            return

        # ── Loop region: Shift+click+drag en el ruler ─────────────────────
        if shift and WAVEFORM_H <= sp.y() < WAVEFORM_H + RULER_H:
            t_ms = int(self.x_to_time(sp.x()) * 1000)
            self._loop_drag_start_ms = self._snap(t_ms)
            self._loop_start_ms = self._loop_drag_start_ms
            self._loop_end_ms   = self._loop_drag_start_ms + 100
            self._rebuild_scene()
            return

        # ── Click sin Shift en el ruler → quitar loop region ──────────────
        if not shift and WAVEFORM_H <= sp.y() < WAVEFORM_H + RULER_H:
            if self._loop_start_ms is not None:
                self._loop_start_ms = None
                self._loop_end_ms = None
                self._rebuild_scene()
            # Permitir que el resto de la lógica (scrub, etc.) prosiga

        # ── DRAW tool ──────────────────────────────────────────────────────
        if self.tool_mode == TOOL_DRAW:
            # v1.9 F1: si Draw está activo pero NO hay efecto elegido,
            # rechazar el click con un aviso claro. Evita clips fantasma.
            no_pixel_effect   = (self.draw_kind == 'pixel'
                                 and self.draw_effect_id is None)
            no_channel_effect = (self.draw_kind == 'channel'
                                 and not self.draw_channel_effect_id)
            if no_pixel_effect or no_channel_effect:
                self.draw_warning.emit(
                    "⚠ Selecciona un efecto en el browser (Pixel o Channel) antes de dibujar")
                return
            track, layer_hint = self.y_to_track_layer(sp.y())
            if track >= 0 and sp.x() > HEADER_W:
                # v1.9 F1: validar match draw_kind ↔ lane destino
                n_groups = len(self._ordered_groups())
                fixture_start = NUM_TRACKS + n_groups
                is_fixture_lane = track >= fixture_start
                if self.draw_kind == 'channel' and not is_fixture_lane:
                    self.draw_warning.emit(
                        "⚠ Channel effect activo — selecciona una fixture lane (no barras/grupos)")
                    return
                if self.draw_kind == 'pixel' and is_fixture_lane:
                    self.draw_warning.emit(
                        "⚠ Pixel effect activo — selecciona una barra o grupo (no fixture lane)")
                    return
                t_ms = int(self.x_to_time(sp.x()) * 1000)
                self._draw_start_ms = self._snap(t_ms)
                self._draw_track    = track
                self._draw_layer    = layer_hint
            return

        # ── SELECT tool ───────────────────────────────────────────────────
        clip, xrel = self._clip_at(sp)
        if clip is not None:
            if clip.locked and not ctrl:
                # Can select but not drag
                if shift:
                    if clip in self.selected_clips: self.selected_clips.remove(clip)
                    else:                           self.selected_clips.append(clip)
                else:
                    self.selected_clips = [clip]
                self.clips_selected.emit(list(self.selected_clips))
                self._rebuild_scene()
                return
            if shift:
                if clip in self.selected_clips: self.selected_clips.remove(clip)
                else:                           self.selected_clips.append(clip)
            else:
                if clip not in self.selected_clips:
                    self.selected_clips = [clip]
            clip_w = (clip.end_ms - clip.start_ms) / 1000.0 * self.px_per_sec
            if xrel < 8:               self._drag_mode = 'resize_l'
            elif xrel > clip_w - 8:    self._drag_mode = 'resize_r'
            else:                      self._drag_mode = 'move'
            self._drag_clip   = clip
            self._drag_offset = xrel
            self._drag_rel    = {c: (c.start_ms - clip.start_ms, c.track - clip.track, c.layer - clip.layer)
                                 for c in self.selected_clips if not c.locked}
            self.clips_selected.emit(list(self.selected_clips))
            self._rebuild_scene()
        elif sp.x() > HEADER_W and sp.y() < WAVEFORM_H + RULER_H:
            t = self.x_to_time(sp.x())
            self.time_seeked.emit(t); self.set_current_time(t)
            if not shift:
                self.selected_clips.clear(); self.clips_selected.emit([])
                self._rebuild_scene()
        else:
            if not shift: self.selected_clips.clear()
            self._rb_origin = sp; self._rb_add = shift

    def mouseMoveEvent(self, event):
        sp = self.mapToScene(event.pos())

        # Loop drag (Shift+arrastrar en ruler)
        if self._loop_drag_start_ms is not None:
            t_ms = self._snap(int(self.x_to_time(sp.x()) * 1000))
            lo, hi = sorted((self._loop_drag_start_ms, t_ms))
            self._loop_start_ms = max(0, lo)
            self._loop_end_ms   = min(self.timeline.duration_ms, max(lo + 50, hi))
            import time as _tt; _now = _tt.monotonic()
            if _now - getattr(self, '_drag_rebuild_t', 0.0) >= 0.04:
                self._drag_rebuild_t = _now; self._rebuild_scene()
            return

        # Scrub
        if self._scrubbing:
            t = self.x_to_time(sp.x())
            self.time_seeked.emit(t); self.set_current_time(t)
            return

        # Draw tool: show preview rectangle
        if self.tool_mode == TOOL_DRAW and self._draw_start_ms is not None:
            t_ms = int(self.x_to_time(sp.x()) * 1000)
            end_ms = max(self._draw_start_ms + 50, self._snap(t_ms))
            x  = self.time_to_x(self._draw_start_ms / 1000.0)
            y  = self._track_layer_y(self._draw_track, self._draw_layer)
            w  = (end_ms - self._draw_start_ms) / 1000.0 * self.px_per_sec
            if self._draw_item:
                self.scene_obj.removeItem(self._draw_item)
            dr = QGraphicsRectItem(x, y+1, max(4, w), BASE_TRACK_H-2)
            dr.setBrush(QBrush(C_DRAW_RECT)); dr.setPen(QPen(C_DRAW_BORDER, 1))
            dr.setZValue(30); self.scene_obj.addItem(dr)
            self._draw_item = dr
            return

        # Drag (select mode)
        if self._drag_clip and self._drag_mode:
            t_ms   = int(self.x_to_time(sp.x()) * 1000)
            anchor = self._drag_clip
            dur    = anchor.end_ms - anchor.start_ms
            if self._drag_mode == 'move':
                raw = max(0, t_ms - int(self._drag_offset / self.px_per_sec * 1000))
                raw = min(raw, self.timeline.duration_ms - dur)
                ss  = self._snap(raw); se = self._snap(raw+dur) - dur
                ns  = ss if abs(ss-raw) <= abs(se-raw) else se
                ns  = max(0, min(ns, self.timeline.duration_ms - dur))
                nt, nl = self.y_to_track_layer(sp.y())
                dt  = (nt - anchor.track)  if 0 <= nt < NUM_TRACKS else 0
                dl  = (nl - anchor.layer)
                for c in self.selected_clips:
                    if c.locked: continue
                    d_ms, d_tr, d_la = self._drag_rel.get(c, (0,0,0))
                    cd   = c.end_ms - c.start_ms
                    c.start_ms = max(0, ns + d_ms)
                    c.end_ms   = c.start_ms + cd
                    c.track    = max(0, min(NUM_TRACKS-1, anchor.track + dt + d_tr))
                    c.layer    = max(0, min(MAX_LAYERS-1, anchor.layer + dl + d_la))
            elif self._drag_mode == 'resize_l':
                s = self._snap(t_ms)
                anchor.start_ms = max(0, min(s, anchor.end_ms-50))
            elif self._drag_mode == 'resize_r':
                s = self._snap(t_ms)
                anchor.end_ms = max(anchor.start_ms+50, min(s, self.timeline.duration_ms))
            import time as _tt; _now = _tt.monotonic()
            if _now - getattr(self, '_drag_rebuild_t', 0.0) >= 0.04:
                self._drag_rebuild_t = _now; self._rebuild_scene()
            return

        # Rubber-band
        if self._rb_origin is not None:
            x0,y0 = min(self._rb_origin.x(),sp.x()), min(self._rb_origin.y(),sp.y())
            x1,y1 = max(self._rb_origin.x(),sp.x()), max(self._rb_origin.y(),sp.y())
            if self._rb_rect_item: self.scene_obj.removeItem(self._rb_rect_item)
            rb = QGraphicsRectItem(x0,y0,x1-x0,y1-y0)
            rb.setPen(QPen(C_RB_BORDER,1,Qt.DashLine)); rb.setBrush(QBrush(C_RB_FILL))
            rb.setZValue(50); self.scene_obj.addItem(rb); self._rb_rect_item = rb
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        sp = self.mapToScene(event.pos())

        # Scrub end
        if self._scrubbing:
            self._scrubbing = False; return

        # End of loop region drag
        if self._loop_drag_start_ms is not None:
            self._loop_drag_start_ms = None
            return

        # Draw tool: create clip
        if self.tool_mode == TOOL_DRAW and self._draw_start_ms is not None:
            t_ms   = int(self.x_to_time(sp.x()) * 1000)
            end_ms = max(self._draw_start_ms + 50, self._snap(t_ms))
            if self._draw_item: self.scene_obj.removeItem(self._draw_item); self._draw_item = None
            if end_ms > self._draw_start_ms and self._draw_track is not None and self._draw_track >= 0:
                self.request_snapshot.emit()

                # ── v1.9 F1: rama CHANNEL CLIP ──────────────────────────────
                if self.draw_kind == 'channel':
                    n_groups = len(self._ordered_groups())
                    fixture_start = NUM_TRACKS + n_groups
                    lanes = self._ordered_fixture_lanes()
                    fx_idx = self._draw_track - fixture_start
                    if 0 <= fx_idx < len(lanes):
                        fx = lanes[fx_idx]
                        # Layer libre en esa fixture lane
                        fx_scope = f'fixture:{fx.fixture_id}'
                        layers_in_use = {c.layer for c in self.timeline.clips
                                         if getattr(c, 'scope', '') == fx_scope
                                         and c.start_ms < end_ms
                                         and c.end_ms   > self._draw_start_ms}
                        layer = 0
                        while layer in layers_in_use and layer < MAX_LAYERS:
                            layer += 1
                        # Color por categoría (mismo dict que _draw_clip de F2)
                        cat_color = self._FIXTURE_CAT_COLORS.get(
                            self.draw_channel_category or '', '#808090')
                        new_c = Clip(
                            track=-1,
                            start_ms=self._draw_start_ms,
                            end_ms=end_ms,
                            effect_id=0,                              # no usado
                            scope=fx_scope,
                            category=self.draw_channel_category or 'position',
                            channel_effect_id=self.draw_channel_effect_id,
                            label=self.draw_channel_effect_id or '',
                            color=cat_color,
                            layer=layer,
                            params=dict(self.draw_channel_defaults or {}),
                        )
                        self.timeline.add(new_c)
                        self.selected_clips = [new_c]
                        self.clips_selected.emit([new_c])
                        self.clip_created.emit(new_c)
                        self._update_snap_pts()
                        self._rebuild_scene()
                    self._draw_start_ms = None; self._draw_track = None
                    return

                # ── rama PIXEL CLIP ─────────────────────────────────────────
                # v1.9 F2 — safety: el guard del press impide llegar aquí con
                # draw_effect_id=None, pero por defensa redundante salimos limpio.
                if self.draw_effect_id is None:
                    self._draw_start_ms = None; self._draw_track = None
                    return
                eff     = None
                try:
                    from src.core.effects_engine import EffectLibrary
                    lib = getattr(self, '_lib', None)
                    if lib: eff = lib.get_effect(self.draw_effect_id)
                except: pass
                # Si el track de dibujo es virtual (grupo), asignar scope=group:X
                # y guardar track=0 (irrelevante para grupos).
                virt_scope = self._scope_for_virtual_track(self._draw_track)
                if virt_scope is not None:
                    final_track = 0
                    final_scope = virt_scope
                    # Color del clip = color del grupo (más reconocible)
                    g_color = None
                    for gg in self._ordered_groups():
                        gname = virt_scope.split(':', 1)[1]
                        if gg.name == gname:
                            g_color = gg.color
                            break
                else:
                    final_track = self._draw_track
                    final_scope = 'per_bar'
                    g_color = None
                layer   = self._next_free_layer(self._draw_track,
                                                self._draw_start_ms, end_ms)
                fam     = eff.family if eff else 'flash'
                col     = g_color or FAMILY_COLORS.get(fam, '#3a7acc')
                lbl     = eff.name if eff else f"#{self.draw_effect_id}"
                new_c   = Clip(track=final_track,
                               start_ms=self._draw_start_ms, end_ms=end_ms,
                               effect_id=self.draw_effect_id,
                               scope=final_scope, label=lbl, color=col, layer=layer)
                self.timeline.add(new_c)
                self.selected_clips = [new_c]
                self.clips_selected.emit([new_c])
                self.clip_created.emit(new_c)
                self._update_snap_pts()
                self._rebuild_scene()
            self._draw_start_ms = None; self._draw_track = None
            return

        # Rubber-band select
        if self._rb_origin is not None and self._rb_rect_item is not None:
            x0,y0 = min(self._rb_origin.x(),sp.x()), min(self._rb_origin.y(),sp.y())
            x1,y1 = max(self._rb_origin.x(),sp.x()), max(self._rb_origin.y(),sp.y())
            sel   = QRectF(x0,y0,x1-x0,y1-y0)
            if not self._rb_add: self.selected_clips = []
            for c in self.timeline.clips:
                cx  = self.time_to_x(c.start_ms/1000.0)
                cx2 = self.time_to_x(c.end_ms/1000.0)
                cy  = self._track_layer_y(c.track, c.layer)
                if QRectF(cx,cy,cx2-cx,BASE_TRACK_H).intersects(sel) and c not in self.selected_clips:
                    self.selected_clips.append(c)
            self.clips_selected.emit(list(self.selected_clips))
            self._rb_origin = None; self._rb_rect_item = None
            self._rebuild_scene(); return

        self._rb_origin = None; self._rb_rect_item = None
        if self._drag_clip:
            self._drag_clip = None; self._drag_mode = None; self._drag_rel = {}
            self._update_snap_pts(); self._rebuild_scene()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        sp   = self.mapToScene(event.pos())
        clip, _ = self._clip_at(sp)
        # Si no hay clip bajo el cursor → menú mínimo con solo "Pegar"
        if clip is None:
            quick = QMenu(self)
            quick.setStyleSheet("QMenu{background:#1e1e30;color:#ddd;border:1px solid #444;}"
                                "QMenu::item:selected{background:#3a7acc;}")
            act_p = quick.addAction("📋  Pegar en cursor")
            act_p.setShortcut("Ctrl+V")
            chosen = quick.exec_(event.globalPos())
            if chosen == act_p:
                self.paste_requested.emit()
            return
        if clip not in self.selected_clips:
            self.selected_clips = [clip]; self.clips_selected.emit([clip]); self._rebuild_scene()
        n    = len(self.selected_clips)
        menu = QMenu(self)
        menu.setStyleSheet("QMenu{background:#1e1e30;color:#ddd;border:1px solid #444;}"
                           "QMenu::item:selected{background:#3a7acc;}")
        act_copy  = menu.addAction(f"📋  Copiar ({n})")
        act_copy.setShortcut("Ctrl+C")
        act_paste = menu.addAction("📋  Pegar en cursor")
        act_paste.setShortcut("Ctrl+V")
        menu.addSeparator()
        act_del  = menu.addAction(f"🗑  Borrar ({n})")
        act_dup  = menu.addAction(f"⎘  Duplicar ({n})")
        act_spl  = menu.addAction("✂  Dividir en cursor") if n == 1 else None
        menu.addSeparator()
        act_color = menu.addAction("🎨  Color…")
        muted_all = all(getattr(c, 'muted', False) for c in self.selected_clips)
        act_mute = menu.addAction("🔇  Mute clip" if not muted_all else "🔊  Unmute clip")
        locked_all = all(c.locked for c in self.selected_clips)
        act_lock = menu.addAction("🔒  Bloquear" if not locked_all else "🔓  Desbloquear")
        act_new_layer = menu.addAction("➕  Añadir layer a este bar")
        chosen   = menu.exec_(event.globalPos())
        if chosen == act_copy:
            self.copy_requested.emit(); return
        if chosen == act_paste:
            self.paste_requested.emit(); return
        if chosen == act_del:
            self.request_snapshot.emit()
            unlocked = [c for c in self.selected_clips if not c.locked]
            for c in unlocked: self.timeline.remove(c)
            self.selected_clips = [c for c in self.selected_clips if c.locked]
            self.clips_selected.emit(list(self.selected_clips))
            self._update_snap_pts(); self._rebuild_scene()
        elif chosen == act_dup:
            self.request_snapshot.emit()
            ncs = []
            for c in self.selected_clips:
                nc = copy.copy(c); nc.params = dict(c.params)
                nc.start_ms = c.end_ms; nc.end_ms = c.end_ms+(c.end_ms-c.start_ms); nc.locked = False
                nc.layer = self._next_free_layer(c.track, nc.start_ms, nc.end_ms)
                self.timeline.add(nc); ncs.append(nc)
            self.selected_clips = ncs; self.clips_selected.emit(ncs)
            self._update_snap_pts(); self._rebuild_scene()
        elif act_spl and chosen == act_spl:
            c = self.selected_clips[0]
            if c.locked: return
            t = int(self.current_time_s * 1000)
            if c.start_ms < t < c.end_ms:
                self.request_snapshot.emit()
                r = copy.copy(c); r.params = dict(c.params)
                r.start_ms = t; r.end_ms = c.end_ms; c.end_ms = t; r.locked = False
                self.timeline.add(r)
                self.selected_clips = [c,r]; self.clips_selected.emit([c,r])
                self._update_snap_pts(); self._rebuild_scene()
        elif chosen == act_color:
            # Color picker para los clips seleccionados
            current_color = QColor(self.selected_clips[0].color)
            new_color = QColorDialog.getColor(current_color, self, "Color del clip")
            if new_color.isValid():
                hex_color = new_color.name()
                for c in self.selected_clips:
                    if not c.locked:
                        c.color = hex_color
                self._rebuild_scene()
        elif chosen == act_mute:
            for c in self.selected_clips: c.muted = not muted_all
            self._rebuild_scene()
        elif chosen == act_lock:
            for c in self.selected_clips: c.locked = not locked_all
            self._rebuild_scene()
        elif chosen == act_new_layer:
            # Add a placeholder clip on new layer so it's visible
            track = clip.track
            new_layer = max(c.layer for c in self.timeline.clips if c.track == track) + 1
            # No clip created, just signal that the layer slot now exists by showing headers
            # (user draws on it with draw tool)
            self._rebuild_scene()

    def delete_selected(self):
        self.request_snapshot.emit()
        unlocked = [c for c in self.selected_clips if not c.locked]
        for c in unlocked: self.timeline.remove(c)
        self.selected_clips = [c for c in self.selected_clips if c.locked]
        self.clips_selected.emit(list(self.selected_clips))
        self._update_snap_pts(); self._rebuild_scene()

    def select_all(self):
        self.selected_clips = list(self.timeline.clips)
        self.clips_selected.emit(list(self.selected_clips)); self._rebuild_scene()


# ═══════════════════════════════════════════════════════════════
# Bar Selector
# ═══════════════════════════════════════════════════════════════
class BarSelectorWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#1a1a2a;")
        lay = QVBoxLayout(self); lay.setSpacing(3); lay.setContentsMargins(6,4,6,4)
        lbl = QLabel("Barras destino:"); lbl.setStyleSheet("color:#888;font-size:10px;")
        lay.addWidget(lbl)
        grid = QGridLayout(); grid.setSpacing(2)
        self.checks: List[QCheckBox] = []
        for i in range(NUM_TRACKS):
            col = QColor(TRACK_STRIP_COLORS[i % len(TRACK_STRIP_COLORS)])
            cb  = QCheckBox(f"B{i}"); cb.setChecked(True)
            cb.setStyleSheet(f"QCheckBox{{color:{col.lighter(160).name()};font-size:10px;}}")
            self.checks.append(cb); grid.addWidget(cb, i//5, i%5)
        lay.addLayout(grid)
        btn_row = QHBoxLayout(); btn_row.setSpacing(3)
        for lbl2, fn in [("Todas", lambda: [c.setChecked(True) for c in self.checks]),
                         ("Ninguna",lambda: [c.setChecked(False) for c in self.checks]),
                         ("Pares",  lambda: [c.setChecked(i%2==0) for i,c in enumerate(self.checks)]),
                         ("Impares",lambda: [c.setChecked(i%2==1) for i,c in enumerate(self.checks)])]:
            b = QPushButton(lbl2)
            b.setStyleSheet("QPushButton{background:#252535;color:#aaa;font-size:9px;"
                            "padding:2px 4px;border:1px solid #333;border-radius:2px;}"
                            "QPushButton:hover{background:#353550;}")
            b.clicked.connect(fn); btn_row.addWidget(b)
        lay.addLayout(btn_row)

    def selected_bars(self) -> List[int]:
        return [i for i,c in enumerate(self.checks) if c.isChecked()]


# ═══════════════════════════════════════════════════════════════
# Group Manager Widget
# ═══════════════════════════════════════════════════════════════
class GroupManagerWidget(QWidget):
    """Grupos de barras persistentes — crea, activa, renombra y borra grupos."""

    groups_changed = pyqtSignal()   # se emite al crear/renombrar/borrar grupos

    def __init__(self, groups: list, bar_sel: 'BarSelectorWidget', parent=None):
        super().__init__(parent)
        self.groups  = groups    # referencia directa a timeline.groups
        self.bar_sel = bar_sel
        self.setStyleSheet("background:#181828;")
        lay = QVBoxLayout(self); lay.setSpacing(2); lay.setContentsMargins(4, 3, 4, 3)

        hdr = QLabel("  GRUPOS DE BARRAS")
        hdr.setStyleSheet("background:#1e1e32;color:#666;font-size:9px;font-weight:bold;"
                          "padding:3px 0;letter-spacing:1px;")
        lay.addWidget(hdr)

        self.list_w = QListWidget()
        self.list_w.setMaximumHeight(82)
        self.list_w.setStyleSheet(
            "QListWidget{background:#141420;color:#d0d0e0;border:none;font-size:10px;}"
            "QListWidget::item{padding:2px 5px;border-bottom:1px solid #1a1a2a;}"
            "QListWidget::item:selected{background:#2a4a7a;color:#fff;}"
            "QListWidget::item:hover{background:#1e1e38;}")
        self.list_w.itemClicked.connect(self._on_click)
        self.list_w.itemDoubleClicked.connect(lambda _: self._rename())
        lay.addWidget(self.list_w)

        _bs = ("QPushButton{background:#252535;color:#aaa;font-size:9px;"
               "padding:2px 5px;border:1px solid #333;border-radius:2px;}"
               "QPushButton:hover{background:#353550;}")
        btn_row = QHBoxLayout(); btn_row.setSpacing(2)
        b_new = QPushButton("+ Grupo"); b_new.setStyleSheet(_bs)
        b_ren = QPushButton("✏");       b_ren.setStyleSheet(_bs); b_ren.setFixedWidth(26)
        b_del = QPushButton("🗑");       b_del.setStyleSheet(_bs); b_del.setFixedWidth(26)
        b_new.setToolTip("Crear grupo con las barras seleccionadas")
        b_ren.setToolTip("Renombrar grupo"); b_del.setToolTip("Borrar grupo")
        b_new.clicked.connect(self._create)
        b_ren.clicked.connect(self._rename)
        b_del.clicked.connect(self._delete)
        btn_row.addWidget(b_new); btn_row.addWidget(b_ren); btn_row.addWidget(b_del)
        lay.addLayout(btn_row)

        self.refresh()

    # ── public ────────────────────────────────────────────────────────────
    def refresh(self):
        self.list_w.clear()
        for g in self.groups:
            bars_str = ','.join(str(b) for b in sorted(g.bars))
            it = QListWidgetItem(f"  ◆ {g.name}  [{bars_str}]")
            it.setData(Qt.UserRole, g)
            it.setForeground(QColor(g.color).lighter(160))
            self.list_w.addItem(it)

    # ── slots ────────────────────────────────────────────────────────────
    def _on_click(self, item):
        """Activar el grupo → marca sus barras en el BarSelector."""
        g = item.data(Qt.UserRole)
        if g:
            for i, cb in enumerate(self.bar_sel.checks):
                cb.setChecked(i in g.bars)

    def _create(self):
        bars = self.bar_sel.selected_bars()
        if not bars:
            QInputDialog.getText(self, "Grupo vacío",
                                 "Marca primero qué barras quieres en el grupo.")
            return
        name, ok = QInputDialog.getText(self, "Nuevo grupo", "Nombre del grupo:")
        if ok and name.strip():
            color = GROUP_COLORS[len(self.groups) % len(GROUP_COLORS)]
            self.groups.append(BarGroup(name=name.strip(), bars=sorted(bars), color=color))
            self.refresh()
            self.groups_changed.emit()

    def _rename(self):
        item = self.list_w.currentItem()
        if not item: return
        g = item.data(Qt.UserRole)
        if not g: return
        name, ok = QInputDialog.getText(self, "Renombrar grupo", "Nuevo nombre:", text=g.name)
        if ok and name.strip():
            g.name = name.strip()
            self.refresh()
            self.groups_changed.emit()

    def _delete(self):
        item = self.list_w.currentItem()
        if not item: return
        g = item.data(Qt.UserRole)
        if g and g in self.groups:
            self.groups.remove(g)
            self.refresh()
            self.groups_changed.emit()


# ═══════════════════════════════════════════════════════════════
# Effects Browser Panel
# ═══════════════════════════════════════════════════════════════
class EffectsBrowserPanel(QWidget):
    effect_chosen           = pyqtSignal(int)   # double-click → add to bars (pixel)
    effect_selected         = pyqtSignal(int)   # single-click  → activate draw mode (pixel)
    # v1.9 F1 — channel effects
    channel_effect_selected = pyqtSignal(str)   # single-click → activate draw (channel)
    channel_effect_chosen   = pyqtSignal(str)   # double-click → add to fixture (futuro)

    # Colores por categoría de channel effect (mismo dict que TimelineView._FIXTURE_CAT_COLORS)
    _CHAN_CAT_COLORS = {
        'position':  '#e06c30',
        'color':     '#5b8dd9',
        'intensity': '#d4b840',
        'optical':   '#4caf82',
        'strobe':    '#d94040',
    }

    def __init__(self, library: EffectLibrary, timeline: Timeline, parent=None):
        super().__init__(parent)
        self._library = library
        self.setStyleSheet("background:#141420;")
        lay = QVBoxLayout(self); lay.setSpacing(0); lay.setContentsMargins(0,0,0,0)
        hdr = QLabel("  EFECTOS  (doble-clic=añadir, clic=dibujar)")
        hdr.setStyleSheet("background:#1e1e32;color:#666;font-size:9px;font-weight:bold;"
                          "padding:4px 0;letter-spacing:1px;")
        lay.addWidget(hdr)

        # v1.9 F1 — Tabs Pixel / Channel
        from PyQt5.QtWidgets import QTabWidget
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet("""
            QTabBar::tab{background:#1a1a26;color:#888;padding:4px 10px;font-size:10px;
                         font-weight:bold;border:1px solid #2a2a40;border-bottom:none;}
            QTabBar::tab:selected{background:#2a4a7a;color:#fff;}
            QTabBar::tab:hover:!selected{background:#23233a;color:#ccc;}
            QTabWidget::pane{border:1px solid #2a2a40;background:#141420;}""")

        # ── Lista PIXEL (la actual) ──────────────────────────────────────────
        self.list_w = QListWidget()
        self.list_w.setStyleSheet("""
            QListWidget{background:#141420;color:#d0d0e0;border:none;font-size:11px;}
            QListWidget::item{padding:3px 6px;border-bottom:1px solid #1e1e2e;}
            QListWidget::item:selected{background:#2a4a7a;color:#fff;}
            QListWidget::item:hover{background:#1e1e38;}""")
        self._tabs.addTab(self.list_w, "🎨 Pixel")

        # ── Lista CHANNEL (nueva) ────────────────────────────────────────────
        self.list_channel = QListWidget()
        self.list_channel.setStyleSheet("""
            QListWidget{background:#141420;color:#d0d0e0;border:none;font-size:11px;}
            QListWidget::item{padding:3px 6px;border-bottom:1px solid #1e1e2e;}
            QListWidget::item:selected{background:#5a3a2a;color:#fff;}
            QListWidget::item:hover{background:#2a1e1e;}""")
        self._tabs.addTab(self.list_channel, "⬡ Channel")

        lay.addWidget(self._tabs, stretch=1)

        # Groups panel first, then individual bar selector
        self.bar_sel  = BarSelectorWidget()
        self.groups_w = GroupManagerWidget(timeline.groups, self.bar_sel)
        lay.addWidget(self.groups_w)
        lay.addWidget(self.bar_sel)
        # Draw-mode indicator
        self.draw_lbl = QLabel("  🖱 SELECT")
        self.draw_lbl.setStyleSheet("background:#1e1e32;color:#888;font-size:10px;font-weight:bold;padding:4px;")
        self.draw_lbl.setMaximumWidth(200)
        lay.addWidget(self.draw_lbl)

        # Poblar lista PIXEL
        by_fam = {}
        for eid, eff in library.effects.items():
            by_fam.setdefault(eff.family, []).append((eid, eff))
        for fam in sorted(by_fam.keys()):
            hi = QListWidgetItem(f"  {fam.upper()}")
            hi.setFlags(Qt.NoItemFlags)
            hi.setForeground(QColor(FAMILY_COLORS.get(fam,'#888')).lighter(160))
            hi.setBackground(QColor(28,28,42)); hi.setFont(QFont("Segoe UI",9,QFont.Bold))
            self.list_w.addItem(hi)
            fc = QColor(FAMILY_COLORS.get(fam,'#999'))
            for eid, eff in sorted(by_fam[fam]):
                it = QListWidgetItem(f"   {eid:02d}  {eff.name}")
                it.setData(Qt.UserRole, eid); it.setForeground(fc.lighter(150))
                self.list_w.addItem(it)
        self.list_w.itemClicked.connect(self._on_click)
        self.list_w.itemDoubleClicked.connect(self._on_dbl)

        # Poblar lista CHANNEL
        try:
            from src.core.channel_effects import ChannelEffectLibrary
            ch_lib = ChannelEffectLibrary()
            by_cat = {}
            for eff in ch_lib.all():
                by_cat.setdefault(eff.category, []).append(eff)
            for cat in ['position', 'color', 'intensity', 'optical', 'strobe']:
                if cat not in by_cat:
                    continue
                hi = QListWidgetItem(f"  {cat.upper()}")
                hi.setFlags(Qt.NoItemFlags)
                cc = QColor(self._CHAN_CAT_COLORS.get(cat, '#888'))
                hi.setForeground(cc.lighter(160))
                hi.setBackground(QColor(28,24,28))
                hi.setFont(QFont("Segoe UI", 9, QFont.Bold))
                self.list_channel.addItem(hi)
                for eff in sorted(by_cat[cat], key=lambda e: e.effect_id):
                    label = f"   ⬡  {eff.effect_id}"
                    it = QListWidgetItem(label)
                    it.setData(Qt.UserRole, eff.effect_id)
                    it.setForeground(cc.lighter(150))
                    desc = getattr(eff, 'description', '') or ''
                    if desc:
                        it.setToolTip(f"{eff.effect_id} ({cat})\n{desc}")
                    else:
                        it.setToolTip(f"{eff.effect_id} ({cat})")
                    self.list_channel.addItem(it)
            self.list_channel.itemClicked.connect(self._on_channel_click)
            self.list_channel.itemDoubleClicked.connect(self._on_channel_dbl)
        except Exception as e:
            print(f"[browser] No se pudo cargar ChannelEffectLibrary: {e}")

    def _on_click(self, item):
        eid = item.data(Qt.UserRole)
        if eid is not None:
            self.effect_selected.emit(int(eid))

    def _on_dbl(self, item):
        eid = item.data(Qt.UserRole)
        if eid is not None:
            self.effect_chosen.emit(int(eid))

    # v1.9 F1 — channel
    def _on_channel_click(self, item):
        ceid = item.data(Qt.UserRole)
        if isinstance(ceid, str) and ceid:
            self.channel_effect_selected.emit(ceid)

    def _on_channel_dbl(self, item):
        ceid = item.data(Qt.UserRole)
        if isinstance(ceid, str) and ceid:
            self.channel_effect_chosen.emit(ceid)

    def set_draw_mode(self, active: bool, effect_name: str = "", kind: str = 'pixel'):
        if active:
            icon = "⬡" if kind == 'channel' else "✏"
            text = f"  {icon} DRAW: {effect_name}"
            fm = QFontMetrics(self.draw_lbl.font())
            text = fm.elidedText(text, Qt.ElideRight, 190)
            self.draw_lbl.setText(text)
            color = "#fa6" if kind == 'channel' else "#6f6"
            bg    = "#3a2a1a" if kind == 'channel' else "#1a3a1a"
            self.draw_lbl.setStyleSheet(
                f"background:{bg};color:{color};font-size:10px;font-weight:bold;padding:4px;")
        else:
            self.draw_lbl.setText("  🖱 SELECT")
            self.draw_lbl.setStyleSheet("background:#1e1e32;color:#888;font-size:10px;font-weight:bold;padding:4px;")

    def selected_bars(self) -> List[int]:
        return self.bar_sel.selected_bars()


# ═══════════════════════════════════════════════════════════════
# Properties Panel
# ═══════════════════════════════════════════════════════════════
class PropertiesPanel(QWidget):
    clip_changed = pyqtSignal()

    def __init__(self, library: EffectLibrary, parent=None):
        super().__init__(parent)
        self.library = library
        self._clips: List[Clip] = []
        self._setting = False
        self.setStyleSheet("background:#141420; color:#ccc;")
        self.setMaximumWidth(300)  # Ancho máximo del panel completo
        lay = QVBoxLayout(self); lay.setSpacing(5); lay.setContentsMargins(6,6,6,6)
        hdr = QLabel("  PROPIEDADES")
        hdr.setStyleSheet("background:#1e1e32;color:#777;font-size:9px;font-weight:bold;padding:4px 0;letter-spacing:2px;")
        lay.addWidget(hdr)
        self.title = QLabel("(ningún clip)")
        self.title.setStyleSheet("font-weight:bold;padding:4px;color:#e0e0e0;font-size:10px;")
        self.title.setWordWrap(True)
        self.title.setMaximumHeight(40)
        lay.addWidget(self.title)
        lay.addWidget(QLabel("Efecto:"))
        self.effect_combo = QComboBox()
        self.effect_combo.setStyleSheet("QComboBox{background:#1e1e32;color:#ddd;border:1px solid #333;padding:2px;font-size:9px;}")
        for eid in sorted(library.effects.keys()):
            self.effect_combo.addItem(f"{eid:02d} {library.get_effect(eid).name}", userData=eid)
        self.effect_combo.currentIndexChanged.connect(self._on_effect_changed)
        lay.addWidget(self.effect_combo)
        ss = "QSpinBox{background:#1e1e32;color:#ddd;border:1px solid #333;padding:2px;font-size:9px;}"
        for attr, label in [('start_ms_spin','Start:'),('end_ms_spin','End:')]:
            row = QHBoxLayout()
            row.setSpacing(2)
            lbl = QLabel(label); lbl.setMaximumWidth(40); lbl.setStyleSheet("font-size:9px;")
            sp  = QSpinBox(); sp.setRange(0,999_999); sp.setSingleStep(50); sp.setStyleSheet(ss); sp.setMaximumWidth(80)
            setattr(self, attr, sp); row.addWidget(lbl); row.addWidget(sp); row.addStretch(); lay.addLayout(row)
        self.start_ms_spin.valueChanged.connect(self._on_start_changed)
        self.end_ms_spin.valueChanged.connect(self._on_end_changed)
        lay.addWidget(QLabel("Scope:"))
        self.scope_combo = QComboBox()
        self.scope_combo.setStyleSheet("QComboBox{background:#1e1e32;color:#ddd;border:1px solid #333;padding:2px;font-size:9px;}")
        self.scope_combo.setMaximumWidth(140)
        # Items base; los grupos se cargan dinámicamente con refresh_groups()
        self.scope_combo.addItems(['per_bar', 'global'])
        self.scope_combo.currentTextChanged.connect(self._on_scope_changed)
        lay.addWidget(self.scope_combo)
        self._cached_groups_signature = None  # para evitar refrescos innecesarios
        sl_style = ("QSlider::groove:horizontal{background:#1e1e32;height:4px;}"
                    "QSlider::handle:horizontal{background:#4a7acc;width:12px;margin:-4px 0;border-radius:6px;}")
        for attr, lbl_text, lo, hi, dflt, fmt in [
            ('hue','H:',0,360,0,lambda v:f"{v}°"),
            ('sat','S:',0,100,100,lambda v:f"{v/100:.2f}"),
            ('speed','Sp:',10,400,100,lambda v:f"{v/100:.2f}×"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(2)
            lbl = QLabel(lbl_text); lbl.setMaximumWidth(30); lbl.setStyleSheet("font-size:9px;")
            sl  = QSlider(Qt.Horizontal); sl.setRange(lo,hi); sl.setValue(dflt); sl.setStyleSheet(sl_style)
            val = QLabel(fmt(dflt)); val.setMaximumWidth(45); val.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
            val.setStyleSheet("color:#aaa;font-size:8px;")
            setattr(self,f'{attr}_slider',sl); setattr(self,f'{attr}_val',val)
            row.addWidget(lbl); row.addWidget(sl); row.addWidget(val); lay.addLayout(row)
        self.hue_slider.valueChanged.connect(self._on_hue_changed)
        self.sat_slider.valueChanged.connect(self._on_sat_changed)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        self.delete_btn = QPushButton("🗑  Borrar selección")
        self.delete_btn.setStyleSheet("QPushButton{background:#6a1f1f;color:white;padding:6px;border-radius:3px;font-weight:bold;}"
                                       "QPushButton:hover{background:#8a2a2a;}")
        lay.addWidget(self.delete_btn); lay.addStretch()
        self.setEnabled(False)

    def refresh_groups(self, groups):
        """
        Repuebla el dropdown de Scope con los grupos disponibles del timeline.
        Llamar cuando se crea/elimina/renombra un BarGroup.
        Items resultantes:
            per_bar
            global
            group:IZQ
            group:DER
            …
            group_set:TODO       (los que tienen subgroups)
            group_set:BORDES…
        """
        # Calcular firma para ver si cambió la lista
        sig = tuple((g.name, g.is_set) for g in groups)
        if sig == self._cached_groups_signature:
            return
        self._cached_groups_signature = sig

        current = self.scope_combo.currentText()
        self._setting = True
        self.scope_combo.clear()
        self.scope_combo.addItems(['per_bar', 'global'])
        # Primero grupos simples, luego sets
        for g in groups:
            if not g.is_set:
                self.scope_combo.addItem(f'group:{g.name}')
        for g in groups:
            if g.is_set:
                self.scope_combo.addItem(f'group_set:{g.name}')
        # Restaurar selección anterior si sigue siendo válida
        idx = self.scope_combo.findText(current)
        if idx >= 0:
            self.scope_combo.setCurrentIndex(idx)
        self._setting = False

    @property
    def clip(self): return self._clips[0] if self._clips else None

    def set_clips(self, clips):
        self._clips = clips
        if not clips: self.title.setText("(ningún clip)"); self.setEnabled(False); return
        self.setEnabled(True); c = clips[0]

        # v1.9 F2 — Detectar channel clip y mostrar panel reducido.
        # Sin esto, el combo de efectos reescribe el clip al cambiar
        # (porque _on_effect_changed sobreescribe effect_id+label).
        if getattr(c, 'category', 'pixel') != 'pixel':
            ce = getattr(c, 'channel_effect_id', '') or '?'
            fx = c.scope.split(':', 1)[1] if c.scope.startswith('fixture:') else '?'
            cat = c.category
            text = f"⬡ {ce}  ·  {fx} L{c.layer}  ({cat}){'  🔒' if c.locked else ''}"
            fm = QFontMetrics(self.title.font())
            text = fm.elidedText(text, Qt.ElideRight, 270)
            self.title.setText(text)
            self._setting = True
            self.effect_combo.setEnabled(False)
            self.start_ms_spin.setValue(c.start_ms)
            self.end_ms_spin.setValue(c.end_ms)
            self._setting = False
            return

        # Rama pixel — re-habilitar combo por si venía deshabilitado
        # tras seleccionar un channel clip previamente.
        self.effect_combo.setEnabled(True)

        text = f"{len(clips)} clip(s)  ·  Bar {c.track}" if len(clips)>1 else f"Bar {c.track} L{c.layer}  ·  {c.label or f'#{c.effect_id}'}{'  🔒' if c.locked else ''}"
        fm = QFontMetrics(self.title.font())
        text = fm.elidedText(text, Qt.ElideRight, 270)
        self.title.setText(text)
        self._setting = True
        idx = self.effect_combo.findData(c.effect_id)
        if idx >= 0: self.effect_combo.setCurrentIndex(idx)
        self.start_ms_spin.setValue(c.start_ms); self.end_ms_spin.setValue(c.end_ms)
        # Si el scope del clip es 'group:X' / 'group_set:X' y no está en el combo
        # (porque aún no se ha llamado refresh_groups), añadirlo on-the-fly.
        if self.scope_combo.findText(c.scope) < 0:
            self.scope_combo.addItem(c.scope)
        self.scope_combo.setCurrentText(c.scope)
        self.hue_slider.setValue(int(c.params.get('hue',0))); self.hue_val.setText(f"{int(c.params.get('hue',0))}°")
        sat = c.params.get('saturation',1.0); self.sat_slider.setValue(int(sat*100)); self.sat_val.setText(f"{sat:.2f}")
        sp  = c.params.get('speed',1.0); self.speed_slider.setValue(int(sp*100)); self.speed_val.setText(f"{sp:.2f}×")
        self._setting = False

    def _on_effect_changed(self,_):
        if self._clips and not self._setting:
            eid = self.effect_combo.currentData()
            for c in self._clips: c.effect_id=eid; c.label=self.library.get_effect(eid).name
            self.clip_changed.emit()
    def _on_start_changed(self,v):
        if not self._clips or self._setting: return
        delta = v - self._clips[0].start_ms
        for c in self._clips:
            if c.locked: continue
            c.start_ms = max(0, c.start_ms+delta)
            if c.end_ms <= c.start_ms: c.end_ms = c.start_ms+100
        self.clip_changed.emit()
    def _on_end_changed(self,v):
        if not self._clips or self._setting: return
        delta = v - self._clips[0].end_ms
        for c in self._clips:
            if not c.locked: c.end_ms = max(c.start_ms+50, c.end_ms+delta)
        self.clip_changed.emit()
    def _on_scope_changed(self,txt):
        if self._clips and not self._setting:
            for c in self._clips: c.scope=txt
            self.clip_changed.emit()
    def _on_hue_changed(self,v):
        self.hue_val.setText(f"{v}°")
        if self._clips and not self._setting:
            for c in self._clips: c.params['hue']=v
            self.clip_changed.emit()
    def _on_sat_changed(self,v):
        s=v/100.0; self.sat_val.setText(f"{s:.2f}")
        if self._clips and not self._setting:
            for c in self._clips: c.params['saturation']=s
            self.clip_changed.emit()
    def _on_speed_changed(self,v):
        s=v/100.0; self.speed_val.setText(f"{s:.2f}×")
        if self._clips and not self._setting:
            for c in self._clips: c.params['speed']=s
            self.clip_changed.emit()


# ═══════════════════════════════════════════════════════════════
# Preview Canvas
# ═══════════════════════════════════════════════════════════════
class PreviewCanvas(QWidget):
    """
    Preview canvas de las 10 barras WLED.

    Visualmente alineado con el ShowPreviewWidget del feedback_app_with_barras:
    fondo negro puro, mayor altura, etiqueta de tiempo + sección en la esquina,
    LEDs apilados verticalmente (LED 0 = abajo, LED 92 = arriba).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 280)
        self.frame = np.zeros((NUM_BARS, LEDS, 3), dtype=np.uint8)
        self.setStyleSheet("background:#000000;border:1px solid #222;")
        self.current_time = 0.0
        self.section_id = 0

    def update_frame(self, f):
        if f is not None and f.shape == (NUM_BARS, LEDS, 3):
            self.frame = f
        self.update()

    def set_time_info(self, t_sec: float, section_id: int = 0):
        """Actualiza tiempo y sección mostrados como overlay."""
        self.current_time = float(t_sec)
        self.section_id = int(section_id)

    def paintEvent(self, event):
        try:
            p = QPainter(self)
            w, h = self.width(), self.height()
            p.fillRect(event.rect(), QColor(0, 0, 0))

            if w < 60 or h < 60:
                return

            top_pad = 18
            bot_pad = 18
            bar_area_h = max(20, h - top_pad - bot_pad)
            bw = w / NUM_BARS
            gap = max(1, int(bw * 0.06))

            # numpy → QImage por barra (10 drawImage en vez de 930 QColor+fillRect)
            for bar in range(NUM_BARS):
                # LED 0 = abajo → flip vertical del eje de LEDs
                col = np.ascontiguousarray(self.frame[bar, ::-1, :])
                img = QImage(col.tobytes(), 1, LEDS, 3, QImage.Format_RGB888)
                x = int(bar * bw) + gap
                rect_w = max(1, int(bw) - gap * 2)
                p.drawImage(QRect(x, top_pad, rect_w, bar_area_h), img)

            # Etiquetas B0..B9 abajo
            p.setPen(QColor(120, 120, 140))
            p.setFont(QFont("Segoe UI", 8))
            for bar in range(NUM_BARS):
                cx = int(bar * bw + bw / 2 - 7)
                p.drawText(cx, h - 4, f"B{bar}")

            # Info de tiempo / sección arriba a la izquierda
            p.setPen(QColor(220, 220, 230))
            p.setFont(QFont("Courier", 9, QFont.Bold))
            sec_text = f"Sec {self.section_id} | {self.current_time:.1f}s"
            p.drawText(8, 14, sec_text)

        except Exception as e:
            print(f"[paintEvent] {e}")


# ═══════════════════════════════════════════════════════════════
# Audio Engine
# ═══════════════════════════════════════════════════════════════
class AudioEngine:
    def __init__(self):
        pygame.init(); pygame.mixer.init(44100,-16,2,2048)
        self.loaded=False; self.duration_s=0.0
        self.start_tick=0; self.start_pos=0.0; self.playing=False
    def load(self,path):
        try:
            pygame.mixer.music.load(str(path))
            y,sr=librosa.load(str(path),sr=44100)
            self.duration_s=len(y)/sr; self.loaded=True; self._path=str(path); return True
        except Exception as e: print(f"[!] audio: {e}"); return False
    def play(self,start_s=0.0):
        if not self.loaded: return
        try:
            pygame.mixer.music.load(self._path)
            try:    pygame.mixer.music.play(loops=0,start=start_s)
            except: pygame.mixer.music.play(loops=0)
        except Exception as e: print(f"[!] play: {e}"); return
        self.start_tick=pygame.time.get_ticks(); self.start_pos=start_s; self.playing=True
    def pause(self):
        if self.playing: pygame.mixer.music.pause(); self.start_pos=self.get_time(); self.playing=False
    def stop(self):
        pygame.mixer.music.stop(); self.playing=False; self.start_pos=0.0
    def get_time(self):
        if self.playing: return min(self.duration_s, self.start_pos+(pygame.time.get_ticks()-self.start_tick)/1000.0)
        return self.start_pos
    def seek(self,t):
        was=self.playing
        if self.playing: self.pause()
        self.start_pos=max(0.0,min(t,self.duration_s))
        if was: self.play(self.start_pos)


# ═══════════════════════════════════════════════════════════════
# Minimap Widget — vista en miniatura del show (FL Studio style)
# ═══════════════════════════════════════════════════════════════
class MinimapWidget(QWidget):
    """
    Barra horizontal que muestra el show completo en miniatura, con:
      - Bands de color para cada clip
      - Líneas para sections y markers
      - Cursor vertical del playhead
      - Viewport rectangle indicando qué porción está visible en el timeline
    Click / drag → seek o scroll.
    """
    seek_requested = pyqtSignal(float)         # seek a tiempo (s)
    scroll_requested = pyqtSignal(float)       # scroll del timeline al t (s) como inicio

    def __init__(self, tl_view, parent=None):
        super().__init__(parent)
        self.tl_view = tl_view
        self.setMinimumHeight(38)
        self.setMaximumHeight(58)
        self.setStyleSheet("background:#11111a;border-top:1px solid #2a2a40;")
        self.setMouseTracking(True)
        self._dragging_viewport = False

    def sizeHint(self):
        from PyQt5.QtCore import QSize
        return QSize(800, 46)

    def _t_to_x(self, t_s, w):
        dur = max(0.001, self.tl_view.timeline.duration_ms / 1000.0)
        return int(t_s / dur * w)

    def _x_to_t(self, x, w):
        dur = max(0.001, self.tl_view.timeline.duration_ms / 1000.0)
        return max(0.0, min(dur, (x / max(1, w)) * dur))

    def paintEvent(self, ev):
        from PyQt5.QtGui import QPainter, QColor
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(17, 17, 26))

        # Clips: una band horizontal por cada clip (apilado por layer)
        for clip in self.tl_view.timeline.clips:
            x0 = self._t_to_x(clip.start_ms / 1000.0, w)
            x1 = self._t_to_x(clip.end_ms / 1000.0, w)
            band_h = max(1, (h - 6) // 4)
            y = 3 + min(clip.layer, 3) * band_h
            col = QColor(clip.color)
            col.setAlpha(180 if not getattr(clip, 'muted', False) else 60)
            p.fillRect(x0, y, max(1, x1 - x0), band_h, col)

        # Markers de sección (líneas naranjas)
        for t in self.tl_view.markers.get('sections', []):
            x = self._t_to_x(t, w)
            p.setPen(QColor(255, 155, 0, 200))
            p.drawLine(x, 0, x, h)

        # Time markers nombrables (líneas color del marker)
        for mk in self.tl_view.time_markers:
            x = self._t_to_x(mk['time_ms'] / 1000.0, w)
            p.setPen(QColor(mk.get('color', '#ff9933')))
            p.drawLine(x, 0, x, h)

        # Loop region (banda amarilla)
        ls = self.tl_view._loop_start_ms
        le = self.tl_view._loop_end_ms
        if ls is not None and le is not None and le > ls:
            lx0 = self._t_to_x(ls / 1000.0, w)
            lx1 = self._t_to_x(le / 1000.0, w)
            p.fillRect(lx0, 0, max(2, lx1 - lx0), 4, QColor(255, 210, 60, 200))

        # Viewport rectangle — la ventana visible del timeline
        try:
            sb = self.tl_view.horizontalScrollBar()
            vw = self.tl_view.viewport().width()
            sb_val = sb.value()
            t_left = self.tl_view.x_to_time(sb_val + HEADER_W)
            t_right = self.tl_view.x_to_time(sb_val + vw)
            x_lo = self._t_to_x(t_left, w)
            x_hi = self._t_to_x(t_right, w)
            p.setPen(QColor(120, 200, 255, 220))
            p.setBrush(QColor(120, 200, 255, 40))
            p.drawRect(x_lo, 1, max(2, x_hi - x_lo), h - 2)
        except Exception:
            pass

        # Cursor de playback (línea blanca)
        x_cur = self._t_to_x(self.tl_view.current_time_s, w)
        p.setPen(QColor(255, 255, 255, 230))
        p.drawLine(x_cur, 0, x_cur, h)

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        # Detectar si el clic cayó dentro del viewport rectangle → drag scroll
        x = ev.pos().x()
        try:
            sb = self.tl_view.horizontalScrollBar()
            vw = self.tl_view.viewport().width()
            t_left = self.tl_view.x_to_time(sb.value() + HEADER_W)
            t_right = self.tl_view.x_to_time(sb.value() + vw)
            x_lo = self._t_to_x(t_left, self.width())
            x_hi = self._t_to_x(t_right, self.width())
            if x_lo <= x <= x_hi:
                self._dragging_viewport = True
                self._drag_offset = x - x_lo
                return
        except Exception:
            pass
        # Click fuera del viewport → seek a esa posición
        t = self._x_to_t(x, self.width())
        self.seek_requested.emit(t)

    def mouseMoveEvent(self, ev):
        if not self._dragging_viewport:
            return
        x = ev.pos().x() - self._drag_offset
        t = self._x_to_t(x, self.width())
        self.scroll_requested.emit(t)

    def mouseReleaseEvent(self, ev):
        self._dragging_viewport = False


# ═══════════════════════════════════════════════════════════════
# Main Window
# ═══════════════════════════════════════════════════════════════
class TimelineEditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Show Timeline Editor v0.5 — Grupos de barras")
        self.setGeometry(30,30,1640,980)
        self.setStyleSheet("QMainWindow{background:#0e0e18;}"
                           "QToolBar{background:#1a1a2e;border-bottom:1px solid #333;spacing:4px;}"
                           "QToolBar QLabel{color:#aaa;font-size:10px;}"
                           "QStatusBar{background:#111120;color:#888;font-size:10px;}")

        # ── v1.8 F3: Obtener proyecto activo del ProjectManager ───────────
        # dual_app.py llama ensure_migrated() ANTES de crear esta ventana,
        # así que pm.current ya está establecido.
        try:
            from src.io.project_manager import get_manager
            self._pm = get_manager()
            self._project = self._pm.current
        except Exception as e:
            print(f"[!] ProjectManager no disponible: {e}")
            self._pm = None
            self._project = None

        # Rutas activas: usa el proyecto si está disponible, si no el legacy
        _audio_file    = Path(self._project.audio_path) if self._project else AUDIO_FILE
        _show_file     = self._project.show_file         if self._project else None
        _rig_file      = self._project.rig_file          if self._project else None
        _analysis_slug = (self._project.analysis_slug    if self._project else '')
        if self._project:
            print(f"[init] Proyecto activo: {self._project.name!r} ({self._project.slug})")

        print("[init] Library..."); self.library = EffectLibrary()
        print(f"[init] Waveform..."); self.waveform = WaveformData(_audio_file)
        print("[init] Analysis (via AnalysisService)...")
        # Fase A v1.6: una única puerta al análisis (servicio normaliza v1/v2→v3,
        # gestiona la curación humana, expone API limpia).
        from src.analysis.analyzer_service import AnalysisService, default_service, ANALIZADAS_DIR
        if _analysis_slug:
            try:
                self.analysis = AnalysisService(ANALIZADAS_DIR / _analysis_slug)
            except Exception:
                self.analysis = default_service()
        else:
            self.analysis = default_service()
        summary = self.analysis.summary
        bpm = float(summary.get('bpm') or 128.0)
        print(f"  BPM: {bpm} ({summary.get('bpm_source','?')}) "
              f"downbeats={summary.get('downbeats_source','?')}")
        # Markers para overlays del timeline (respeta curación)
        self.markers = {
            'beats':    self.analysis.list_beats(),
            'sections': [s.start for s in self.analysis.list_sections()],
            'kicks':    [e.time_sec for e in self.analysis.list_events('kick')],
        }
        print("[init] Timeline...")
        dur_ms = int((summary.get('duration_s') or 165) * 1000)
        if _show_file and _show_file.is_file():
            loaded = Timeline.load(_show_file)
        else:
            loaded = Timeline.load()   # fallback al legacy TIMELINE_FILE
        if loaded.clips: self.timeline=loaded; self.timeline.duration_ms=dur_ms
        else:            self.timeline=make_demo_timeline(dur_ms)

        # Si no hay grupos guardados (timeline antiguo), poblar los defaults
        # del layout 5+gap+5 (IZQ, DER, EXTREMOS, CENTRO, PARES, IMPARES,
        # TODO, BORDES+CENTRO).
        if not getattr(self.timeline, 'groups', None):
            from src.core.timeline_model import make_default_groups
            self.timeline.groups = make_default_groups()
            print(f"[init] Grupos por defecto creados: "
                  f"{[g.name for g in self.timeline.groups]}")

        print("[init] Audio..."); self.audio = AudioEngine(); self.audio.load(_audio_file)
        print("[init] ShowEngine...")
        # Fase 3: cargar FixtureRig (custom desde proyecto o fallback a legacy)
        try:
            from src.core.fixtures import FixtureRig, build_default_wled_rig, DEFAULT_RIG_FILE
            rig_source = _rig_file if (_rig_file and _rig_file.is_file()) else \
                         (DEFAULT_RIG_FILE if DEFAULT_RIG_FILE.is_file() else None)
            if rig_source:
                self.fixture_rig = FixtureRig.load(rig_source)
                print(f"[init] Rig cargado de {rig_source.name}: {len(self.fixture_rig.fixtures)} fixtures")
            else:
                self.fixture_rig = build_default_wled_rig()
                print(f"[init] Rig por defecto (WLED 10 barras): {len(self.fixture_rig.fixtures)} fixtures")
        except Exception as e:
            print(f"[!] No se pudo cargar rig: {e}")
            self.fixture_rig = None
        try:
            self.show_engine = ShowEngine(use_effects=False,
                                          rig=self.fixture_rig,
                                          analysis=self.analysis)
            self.send_artnet = True
        except Exception:
            self.show_engine = None
            self.send_artnet = False

        self._bpm       = bpm
        self._clipboard: List[Clip] = []
        self._undo      = UndoManager()
        self._undo.snapshot(self.timeline.clips)   # initial state
        self._live_mode = False    # En Vivo: envía a barras reales continuamente

        self._build_ui(bpm)
        self._build_toolbar()
        self.addToolBarBreak()
        self._build_cue_toolbar()

        self.render_timer = QTimer()
        self.render_timer.timeout.connect(self._tick)
        self.render_timer.start(33)
        self._last_scroll_t = -1.0

        # ── Atajos de teclado configurables ──────────────────────────────
        # IMPORTANTE: el parent debe ser un widget que QUEDE VISIBLE tras
        # _wrap_as_widget() en dual_app. La QMainWindow se hide()ea al
        # embeberse, dejando inactivos sus QShortcut. centralWidget se
        # extrae al container del tab y sigue visible.
        self.shortcuts = ShortcutManager(self.centralWidget() or self)
        self.shortcuts.register('play_pause',  'Play / Pause',
                                lambda: self._on_pause() if self.audio.playing else self._on_play(),
                                'Space')
        self.shortcuts.register('stop',        'Stop',           self._on_stop, 'S')
        self.shortcuts.register('save',        'Guardar timeline', self._on_save, 'Ctrl+S')
        self.shortcuts.register('save_as',     'Guardar como…',    self._on_save_as, 'Ctrl+Shift+S')
        self.shortcuts.register('open_show',   'Abrir show…',      self._on_open_show, 'Ctrl+O')
        self.shortcuts.register('undo',        'Deshacer',       self._do_undo, 'Ctrl+Z')
        self.shortcuts.register('redo',        'Rehacer',        self._do_redo, 'Ctrl+Shift+Z')
        self.shortcuts.register('toggle_snap', 'Toggle Snap',
                                lambda: self._snap_act.toggle(), 'Q')
        self.shortcuts.register('tool_select', 'Modo Select',
                                lambda: self._set_tool(TOOL_SELECT), 'Escape')
        self.shortcuts.register('tool_draw',   'Modo Draw',
                                lambda: self._set_tool(TOOL_DRAW), 'D')
        self.shortcuts.register('tool_slice',  'Modo Slice (cortar)',
                                lambda: self._set_tool(TOOL_SLICE), 'C')
        self.shortcuts.register('quantize',    'Cuantizar selección al grid',
                                self._do_quantize_selection, 'Ctrl+Q')
        self.shortcuts.register('blackout',    'Blackout',  self._send_blackout, 'B')
        self.shortcuts.register('view_bars',   'Vista: barras físicas',
                                lambda: self._toggle_view_flag('_show_bars'), 'F1')
        self.shortcuts.register('view_groups', 'Vista: grupos',
                                lambda: self._toggle_view_flag('_show_groups'), 'F2')
        self.shortcuts.register('view_sets',   'Vista: group_sets',
                                lambda: self._toggle_view_flag('_show_group_sets'), 'F3')
        self.shortcuts.register('copy',        'Copiar selección',
                                self._do_copy, 'Ctrl+C')
        self.shortcuts.register('paste',       'Pegar en cursor',
                                self._do_paste, 'Ctrl+V')
        self.shortcuts.register('select_all',  'Seleccionar todo',
                                lambda: self.tl_view.select_all(), 'Ctrl+A')
        self.shortcuts.register('delete',      'Borrar selección',
                                self._on_delete_clips, 'Delete')
        self.shortcuts.register('lock',        'Bloquear selección',
                                lambda: self._lock_selection(True), 'Ctrl+L')
        self.shortcuts.register('unlock',      'Desbloquear selección',
                                lambda: self._lock_selection(False), 'Ctrl+U')
        self.shortcuts.register('show_shortcuts_dialog', 'Editar atajos…',
                                self._open_shortcuts_dialog, 'Ctrl+K')
        # Cue points 1..9 (Performance Mode FL Studio)
        for slot in range(1, 10):
            self.shortcuts.register(f'cue_{slot}', f'Cue {slot} — go + play',
                                    lambda s=slot: self._trigger_cue(s), str(slot))
            self.shortcuts.register(f'set_cue_{slot}', f'Set cue {slot} aquí',
                                    lambda s=slot: self._set_cue(s), f'Shift+{slot}')
        self.shortcuts.bind_all()

    def _lock_selection(self, lock: bool):
        for c in self.tl_view.selected_clips:
            c.locked = lock
        self.tl_view._rebuild_scene()
        self.status.showMessage(
            ("🔒 Clips bloqueados" if lock else "🔓 Clips desbloqueados"), 2000)

    def _do_quantize_selection(self):
        """Alinea start_ms de los clips seleccionados al grid actual."""
        tl_view = self.tl_view
        step = tl_view._grid_step_ms()
        if step <= 0:
            self.status.showMessage("Grid en Off — cambia a Beat/Bar/1/N para cuantizar", 3000)
            return
        clips = tl_view.selected_clips or list(self.timeline.clips)
        if not clips:
            self.status.showMessage("Nada que cuantizar", 2000)
            return
        self._undo.snapshot(self.timeline.clips)
        moved = 0
        for c in clips:
            if c.locked:
                continue
            dur = c.end_ms - c.start_ms
            new_start = int(round(c.start_ms / step) * step)
            if new_start != c.start_ms:
                c.start_ms = new_start
                c.end_ms = new_start + dur
                moved += 1
        tl_view._update_snap_pts(); tl_view._rebuild_scene()
        self.status.showMessage(f"⌗ Cuantizados {moved} clips a {tl_view._snap_grid}", 3000)

    def _toggle_view_flag(self, attr: str):
        setattr(self.tl_view, attr, not getattr(self.tl_view, attr))
        self.tl_view._rebuild_scene()
        self.status.showMessage(f"Vista: {attr} = {getattr(self.tl_view, attr)}", 2000)

    def _open_shortcuts_dialog(self):
        ShortcutsDialog(self.shortcuts, self).exec_()

    def _open_3d_viewer(self):
        """Abre el viewer 3D en el navegador (http://localhost:8080)."""
        import webbrowser
        url = "http://localhost:8080/"
        webbrowser.open(url)
        self.status.showMessage(f"🌐 Abriendo {url} …", 4000)

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self, bpm):
        central = QWidget(); self.setCentralWidget(central)
        outer_lay = QVBoxLayout(central); outer_lay.setSpacing(0); outer_lay.setContentsMargins(2,2,2,2)
        # Contenedor horizontal principal (browser + timeline + props)
        center_container = QWidget()
        lay = QHBoxLayout(center_container); lay.setSpacing(2); lay.setContentsMargins(0,0,0,0)
        outer_lay.addWidget(center_container, 1)
        sp  = QSplitter(Qt.Horizontal)
        sp.setStyleSheet("QSplitter::handle{background:#222238;width:3px;}")

        self.browser = EffectsBrowserPanel(self.library, self.timeline)
        self.browser.effect_chosen.connect(self._on_effect_add_to_bars)
        self.browser.effect_selected.connect(self._on_effect_draw_activate)
        # v1.9 F1 — channel effects
        self.browser.channel_effect_selected.connect(self._on_channel_effect_draw_activate)
        sp.addWidget(self.browser)

        self.tl_view = TimelineView(self.timeline, self.waveform, self.markers, bpm)
        self.tl_view.fixture_rig = self.fixture_rig   # v1.8 F2: fixture lanes
        self.tl_view._lib = self.library    # reference for draw tool
        self.tl_view.clips_selected.connect(self._on_clips_selected)
        self.tl_view.time_seeked.connect(lambda t: self.audio.seek(t))
        self.tl_view.clip_created.connect(self._on_clip_created)
        self.tl_view.request_snapshot.connect(lambda: self._undo.snapshot(self.timeline.clips))
        self.tl_view.copy_requested.connect(self._do_copy)
        self.tl_view.paste_requested.connect(self._do_paste)
        # v1.9 F1 — warnings de draw (mismatch lane/effect-kind)
        self.tl_view.draw_warning.connect(lambda msg: self.status.showMessage(msg, 3000))
        sp.addWidget(self.tl_view)

        right = QSplitter(Qt.Vertical)
        right.setStyleSheet("QSplitter::handle{background:#222238;height:3px;}")
        self.props = PropertiesPanel(self.library)
        self.props.clip_changed.connect(self.tl_view._rebuild_scene)
        self.props.delete_btn.clicked.connect(self._on_delete_clips)
        # Poblar el dropdown de Scope con los grupos del timeline
        try:
            self.props.refresh_groups(self.timeline.groups or [])
        except Exception as e:
            print(f"[!] refresh_groups inicial falló: {e}")
        # Reaccionar cuando el usuario cree/renombre/borre grupos en el browser
        try:
            if hasattr(self.browser, 'groups_w'):
                self.browser.groups_w.groups_changed.connect(
                    lambda: self.props.refresh_groups(self.timeline.groups or [])
                )
        except Exception as e:
            print(f"[!] hook groups_changed falló: {e}")
        right.addWidget(self.props)
        self.preview = PreviewCanvas(); right.addWidget(self.preview)
        right.setSizes([440,200])
        sp.addWidget(right)
        sp.setSizes([230,1090,310]); lay.addWidget(sp)

        # ── Minimap (FL Studio overview) bajo el timeline principal ────
        self.minimap = MinimapWidget(self.tl_view)
        outer_lay.addWidget(self.minimap)
        # Click en el minimap → seek
        self.minimap.seek_requested.connect(lambda t: self.audio.seek(t))
        self.minimap.seek_requested.connect(self.tl_view.set_current_time)
        # Drag del viewport → scroll del timeline
        def _scroll_to(t_s):
            sb = self.tl_view.horizontalScrollBar()
            x  = self.tl_view.time_to_x(t_s) - HEADER_W
            sb.setValue(max(0, int(x)))
        self.minimap.scroll_requested.connect(_scroll_to)
        # Refrescar minimap cuando cambien clips o scroll
        self.tl_view.horizontalScrollBar().valueChanged.connect(
            lambda _v: self.minimap.update())

        self.status = QStatusBar(); self.setStatusBar(self.status)
        self.status.showMessage("Clic efecto=DRAW  DblClic efecto=añadir a barras  "
                                "Esc=SELECT  Del=borrar  Ctrl+Z=undo  Ctrl+C/V=copy/paste")

    def _trigger_cue(self, slot: int):
        """Salta al tiempo del cue point y reproduce."""
        try:
            cue = next((c for c in self.timeline.cue_points if c.slot == slot), None)
            if cue is None or not cue.is_set():
                self.status.showMessage(f"[!] Cue {slot} no asignado", 2000)
                return
            self.audio.seek(cue.time_ms / 1000.0)
            self.audio.play(cue.time_ms / 1000.0)
            self.status.showMessage(
                f"▶ Cue {slot}: {cue.name or f'@{cue.time_ms/1000:.1f}s'}", 3000)
        except Exception as e:
            print(f"[!] trigger_cue: {e}")

    def _set_cue(self, slot: int):
        """Asigna el tiempo actual al cue."""
        try:
            cue = next((c for c in self.timeline.cue_points if c.slot == slot), None)
            if cue is None:
                return
            cue.time_ms = int(self.audio.get_time() * 1000)
            if not cue.name:
                cue.name = f"Cue {slot}"
            self._refresh_cue_buttons()
            self.status.showMessage(
                f"📌 Cue {slot} = {cue.time_ms/1000:.2f}s", 3000)
        except Exception as e:
            print(f"[!] set_cue: {e}")

    def _clear_cue(self, slot: int):
        try:
            cue = next((c for c in self.timeline.cue_points if c.slot == slot), None)
            if cue:
                cue.time_ms = -1
                cue.name = ""
                self._refresh_cue_buttons()
                self.status.showMessage(f"⛔ Cue {slot} borrado", 2000)
        except Exception:
            pass

    def _rename_cue(self, slot: int):
        cue = next((c for c in self.timeline.cue_points if c.slot == slot), None)
        if cue is None or not cue.is_set():
            return
        name, ok = QInputDialog.getText(self, f"Renombrar cue {slot}",
                                        "Nombre:", text=cue.name)
        if ok:
            cue.name = name.strip()
            self._refresh_cue_buttons()

    def _refresh_cue_buttons(self):
        """Actualiza textos y colores de los botones cue según su estado."""
        for slot in range(1, 10):
            btn = self._cue_buttons.get(slot)
            if btn is None: continue
            cue = next((c for c in self.timeline.cue_points if c.slot == slot), None)
            if cue and cue.is_set():
                label = f"{slot}\n{(cue.name or '·')[:8]}"
                btn.setText(label)
                btn.setStyleSheet("QPushButton{background:#4a8fcc;color:white;"
                                  "font-size:9px;font-weight:bold;border:1px solid #6abadd;"
                                  "padding:2px;border-radius:3px;}"
                                  "QPushButton:hover{background:#5aaadd;}")
            else:
                btn.setText(f"{slot}\n—")
                btn.setStyleSheet("QPushButton{background:#1e1e30;color:#666;"
                                  "font-size:9px;border:1px dashed #444;padding:2px;"
                                  "border-radius:3px;}"
                                  "QPushButton:hover{background:#2a2a40;color:#aaa;}")

    def _cue_context_menu(self, slot: int, btn):
        m = QMenu(self)
        m.setStyleSheet("QMenu{background:#1e1e30;color:#ddd;border:1px solid #444;}"
                        "QMenu::item:selected{background:#3a7acc;}")
        a_set    = m.addAction(f"📌 Set cue {slot} aquí (tiempo actual)")
        a_rename = m.addAction(f"✏  Renombrar")
        a_clear  = m.addAction(f"⛔ Borrar cue {slot}")
        chosen = m.exec_(btn.mapToGlobal(btn.rect().bottomLeft()))
        if chosen == a_set:    self._set_cue(slot)
        elif chosen == a_rename: self._rename_cue(slot)
        elif chosen == a_clear:  self._clear_cue(slot)

    def _build_cue_toolbar(self):
        """Toolbar dedicada estilo FL Studio Performance Mode con 9 botones de cue."""
        tb = self.addToolBar("Cues")
        tb.setMovable(False)
        tb.addWidget(QLabel(" 🎯 CUES: "))
        self._cue_buttons = {}
        for slot in range(1, 10):
            btn = QPushButton()
            btn.setFixedSize(46, 36)
            btn.clicked.connect(lambda _, s=slot: self._trigger_cue(s))
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda _pos, s=slot, b=btn: self._cue_context_menu(s, b))
            btn.setToolTip(f"Cue {slot}\n"
                           f"Click: ir y reproducir\n"
                           f"Right-click: asignar/borrar/renombrar\n"
                           f"Atajo: {slot}")
            self._cue_buttons[slot] = btn
            tb.addWidget(btn)
        self._refresh_cue_buttons()

    def _build_toolbar(self):
        tb = self.addToolBar("Transport"); tb.setMovable(False)
        def act(label, slot, checkable=False, checked=False):
            a = QAction(label,self)
            if checkable: a.setCheckable(True); a.setChecked(checked)
            a.triggered.connect(slot); tb.addAction(a); return a

        act("▶", self._on_play)
        act("⏸", self._on_pause)
        act("⏹", self._on_stop)
        tb.addSeparator()
        act("🌐 3D View", self._open_3d_viewer).setToolTip(
            "Abrir el visualizador 3D en el navegador (http://localhost:8080)")
        tb.addSeparator()
        act("💾", self._on_save).setToolTip("Guardar (Ctrl+S)")
        act("💾⇲ Save As…", self._on_save_as).setToolTip("Guardar como… (Ctrl+Shift+S)")
        act("📂 Open…", self._on_open_show).setToolTip("Abrir show… (Ctrl+O)")
        act("✗ Clear", self._on_clear)
        tb.addSeparator()

        # v1.8 F3 — Botón de proyecto
        self._project_btn = QPushButton()
        proj_name = (self._project.name[:20] if self._project else "Sin proyecto")
        self._project_btn.setText(f"📁 {proj_name}")
        self._project_btn.setToolTip("Gestión de proyectos")
        self._project_btn.setStyleSheet(
            "QPushButton{background:#252540;color:#9fa;font-size:10px;"
            "border:1px solid #3a5a3a;padding:2px 6px;border-radius:3px;}"
            "QPushButton:hover{background:#2a3a2a;}"
            "QPushButton:pressed{background:#1a2a1a;}")
        self._project_btn.clicked.connect(self._show_project_menu)
        tb.addWidget(self._project_btn)
        tb.addSeparator()

        # Tool mode
        tb.addWidget(QLabel(" Tool: "))
        self._tool_select_act = act("🖱 Select", lambda: self._set_tool(TOOL_SELECT), checkable=True, checked=True)
        self._tool_draw_act   = act("✏ Draw",   lambda: self._set_tool(TOOL_DRAW),   checkable=True, checked=False)
        self._tool_slice_act  = act("✂ Slice",  lambda: self._set_tool(TOOL_SLICE),  checkable=True, checked=False)
        tg = QActionGroup(self); tg.setExclusive(True)
        tg.addAction(self._tool_select_act); tg.addAction(self._tool_draw_act); tg.addAction(self._tool_slice_act)
        # Quantize button
        act("⌗ Quantize", self._do_quantize_selection)
        tb.addSeparator()

        # Undo/Redo
        self._undo_act = act("↩ Undo", self._do_undo)
        self._redo_act = act("↪ Redo", self._do_redo)
        tb.addSeparator()

        # Ruler mode
        tb.addWidget(QLabel(" Ruler: "))
        self._ruler_btn = QPushButton("BARS")
        self._ruler_btn.setFixedWidth(52)
        self._ruler_btn.setStyleSheet("QPushButton{background:#252540;color:#9af;font-size:10px;"
                                       "font-weight:bold;border:1px solid #444;padding:2px;}"
                                       "QPushButton:hover{background:#353555;}")
        self._ruler_btn.clicked.connect(self._toggle_ruler)
        tb.addWidget(self._ruler_btn)
        tb.addSeparator()

        # BPM
        tb.addWidget(QLabel(" BPM: "))
        bl = QLabel(f"{self._bpm:.0f}")
        bl.setStyleSheet("color:#fa8;font-size:11px;font-weight:bold;padding:0 4px;")
        tb.addWidget(bl)
        tb.addSeparator()

        # Zoom
        tb.addWidget(QLabel(" Zoom: "))
        self._zoom_sl = QSlider(Qt.Horizontal); self._zoom_sl.setRange(5,400)
        self._zoom_sl.setValue(int(DEFAULT_PX_PER_SEC)); self._zoom_sl.setMaximumWidth(160)
        self._zoom_sl.setStyleSheet("QSlider::groove:horizontal{background:#252535;height:4px;}"
                                     "QSlider::handle:horizontal{background:#4a7acc;width:12px;margin:-4px 0;border-radius:6px;}")
        self._zoom_sl.valueChanged.connect(lambda v: self.tl_view.set_zoom(float(v)))
        tb.addWidget(self._zoom_sl)
        tb.addSeparator()

        self._snap_act = act("🧲 Snap", lambda on: setattr(self.tl_view,'_snap_on',on), checkable=True, checked=True)
        # Combobox de grid (snap subdivision, estilo FL Studio)
        self._snap_grid_combo = QComboBox()
        self._snap_grid_combo.addItems(['off', 'bar', 'beat', '1/4', '1/8', '1/16'])
        self._snap_grid_combo.setCurrentText('beat')
        self._snap_grid_combo.setStyleSheet("QComboBox{background:#1e1e32;color:#9af;border:1px solid #444;padding:1px 6px;font-size:10px;}")
        self._snap_grid_combo.setToolTip("Grid de snap (subdivisión musical)")
        self._snap_grid_combo.currentTextChanged.connect(
            lambda t: setattr(self.tl_view, '_snap_grid', t))
        tb.addWidget(self._snap_grid_combo)
        tb.addSeparator()

        # Track height (zoom vertical) — FL Studio Round 3
        tb.addWidget(QLabel(" Alto: "))
        self._track_h_sl = QSlider(Qt.Horizontal)
        self._track_h_sl.setRange(16, 80); self._track_h_sl.setValue(BASE_TRACK_H)
        self._track_h_sl.setMaximumWidth(80)
        self._track_h_sl.setStyleSheet("QSlider::groove:horizontal{background:#252535;height:4px;}"
                                       "QSlider::handle:horizontal{background:#4a7acc;width:10px;margin:-4px 0;border-radius:5px;}")
        self._track_h_sl.setToolTip("Altura de cada layer/track en pixels")
        def _set_track_h(v):
            global BASE_TRACK_H
            BASE_TRACK_H = int(v)
            self.tl_view._rebuild_scene()
        self._track_h_sl.valueChanged.connect(_set_track_h)
        tb.addWidget(self._track_h_sl)
        tb.addSeparator()

        # ── Vista (filtros de visibilidad del timeline) ──────────────────
        view_btn = QPushButton("👁 Vista ▾")
        view_btn.setStyleSheet("QPushButton{background:#252540;color:#aae;font-size:10px;"
                               "font-weight:bold;border:1px solid #444;padding:3px 8px;}"
                               "QPushButton:hover{background:#353555;}")
        view_menu = QMenu(view_btn)
        view_menu.setStyleSheet("QMenu{background:#1a1a2a;color:#ccc;border:1px solid #333;}"
                                "QMenu::item:selected{background:#2a4a8a;}")

        def _make_toggle(label, getter, setter, default=True):
            a = QAction(label, view_menu); a.setCheckable(True); a.setChecked(getter())
            def _on(v):
                setter(v)
                self.tl_view._rebuild_scene()
            a.toggled.connect(_on)
            view_menu.addAction(a)
            return a

        view_menu.addSection("Tracks")
        _make_toggle("Barras físicas (B0-B9)",
                     lambda: self.tl_view._show_bars,
                     lambda v: setattr(self.tl_view, '_show_bars', v))
        _make_toggle("Grupos (IZQ, DER, …)",
                     lambda: self.tl_view._show_groups,
                     lambda v: setattr(self.tl_view, '_show_groups', v))
        _make_toggle("Group_sets (TODO, …)",
                     lambda: self.tl_view._show_group_sets,
                     lambda v: setattr(self.tl_view, '_show_group_sets', v))
        _make_toggle("Fixture lanes (movers, wash, …)",
                     lambda: self.tl_view._show_fixtures,
                     lambda v: setattr(self.tl_view, '_show_fixtures', v))

        view_menu.addSection("Layers")
        def _layer_setter(idx):
            def _set(v):
                if v: self.tl_view._visible_layers.add(idx)
                else: self.tl_view._visible_layers.discard(idx)
            return _set
        for li, lbl in [(0, "Layer 0 — backgrounds"),
                        (1, "Layer 1 — kicks"),
                        (2, "Layer 2 — decoración"),
                        (3, "Layer 3 — L/R + olas")]:
            _make_toggle(lbl,
                         (lambda l=li: l in self.tl_view._visible_layers),
                         _layer_setter(li))

        view_btn.setMenu(view_menu)
        tb.addWidget(view_btn)

        # v1.8 F5 — Exportar
        export_btn = QPushButton("📤 Exportar ▾")
        export_btn.setStyleSheet("QPushButton{background:#252535;color:#fca;font-size:10px;"
                                 "font-weight:bold;border:1px solid #5a3a2a;padding:3px 8px;}"
                                 "QPushButton:hover{background:#352535;}")
        export_menu = QMenu(export_btn)
        export_menu.setStyleSheet("QMenu{background:#1a1a2a;color:#ccc;border:1px solid #333;}"
                                  "QMenu::item:selected{background:#4a2a1a;}")
        export_menu.addSection("Exportar show")
        _ex_csv   = QAction("📋 CSV — lista de clips",        export_menu)
        _ex_qlc   = QAction("💡 QLC+ XML workspace (.qxw)",   export_menu)
        _ex_csv.triggered.connect(lambda: self._export_format('csv_clips'))
        _ex_qlc.triggered.connect(lambda: self._export_format('qlc'))
        export_menu.addAction(_ex_csv)
        export_menu.addAction(_ex_qlc)
        export_btn.setMenu(export_menu)
        tb.addWidget(export_btn)

        # Atajos de teclado
        shortcuts_btn = QPushButton("⌨ Atajos")
        shortcuts_btn.setStyleSheet("QPushButton{background:#252540;color:#aae;font-size:10px;"
                                    "font-weight:bold;border:1px solid #444;padding:3px 8px;}"
                                    "QPushButton:hover{background:#353555;}")
        shortcuts_btn.setToolTip("Editar atajos de teclado (Ctrl+K)")
        shortcuts_btn.clicked.connect(self._open_shortcuts_dialog)
        tb.addWidget(shortcuts_btn)
        tb.addSeparator()

        # Align
        tb.addWidget(QLabel(" Alinear: "))
        for lbl2, tip, slot in [("⊢|","Align starts",self._align_starts),
                                  ("|⊣","Align ends",self._align_ends),
                                  ("↔", "Distribuir", self._distribute),
                                  ("⟷", "Igualar dur",self._equalize_duration)]:
            a = QAction(lbl2,self); a.setToolTip(tip); a.triggered.connect(slot); tb.addAction(a)
        tb.addSeparator()

        # Live time counter
        tb.addWidget(QLabel(" Pos: "))
        self._time_lbl = QLabel("1:1  0:00.0")
        self._time_lbl.setStyleSheet("color:#7df;font-size:11px;font-weight:bold;"
                                      "font-family:Consolas;padding:0 6px;min-width:120px;")
        tb.addWidget(self._time_lbl)
        tb.addSeparator()

        # ── LIVE output section ──────────────────────────────────────────
        tb.addWidget(QLabel(" "))

        # EN VIVO button — envía a barras reales continuamente
        self._live_btn = QPushButton("⬤  EN VIVO")
        self._live_btn.setCheckable(True)
        self._live_btn.setChecked(False)
        _live_off = ("QPushButton{background:#2a2a3a;color:#666;font-size:11px;font-weight:bold;"
                     "padding:4px 10px;border:2px solid #444;border-radius:4px;}"
                     "QPushButton:hover{background:#333344;color:#888;}")
        _live_on  = ("QPushButton{background:#8b0000;color:#ff4444;font-size:11px;font-weight:bold;"
                     "padding:4px 10px;border:2px solid #ff2222;border-radius:4px;}"
                     "QPushButton:checked{background:#cc0000;color:#ffffff;}"
                     "QPushButton:hover{background:#aa0000;}")
        self._live_btn.setStyleSheet(_live_off)
        self._live_btn.setToolTip("Enviar show a barras WLED en tiempo real (sin necesidad de reproducir audio)")
        def _toggle_live(checked):
            self._live_mode = checked
            if checked:
                self._live_btn.setStyleSheet(_live_on)
                self._live_btn.setText("⬤  EN VIVO")
                self.status.showMessage("🔴 EN VIVO — enviando a barras reales")
            else:
                self._live_btn.setStyleSheet(_live_off)
                self._live_btn.setText("⬤  EN VIVO")
                self._send_blackout()
                self.status.showMessage("⬛ LIVE apagado — blackout enviado")
        self._live_btn.toggled.connect(_toggle_live)
        tb.addWidget(self._live_btn)

        # BLACKOUT button
        self._blackout_btn = QPushButton("⬛ BLACKOUT")
        self._blackout_btn.setStyleSheet(
            "QPushButton{background:#1a1a1a;color:#888;font-size:10px;font-weight:bold;"
            "padding:4px 8px;border:1px solid #444;border-radius:4px;}"
            "QPushButton:hover{background:#2a0000;color:#f88;border-color:#844;}")
        self._blackout_btn.setToolTip("Apagar todas las barras inmediatamente")
        self._blackout_btn.clicked.connect(self._send_blackout)
        tb.addWidget(self._blackout_btn)
        tb.addSeparator()

        # Art-Net raw toggle (existente, ahora al final)
        self._artnet_act = act("Art-Net", lambda x: setattr(self,'send_artnet',x),
                               checkable=True, checked=self.send_artnet)

        # Indicador de estado de conexión
        self._conn_lbl = QLabel("● OFF")
        self._conn_lbl.setStyleSheet("color:#444;font-size:10px;font-weight:bold;padding:0 4px;")
        self._conn_lbl.setToolTip("Estado conexión Art-Net con barras WLED")
        tb.addWidget(self._conn_lbl)

    # ── Blackout (apaga todas las barras vía Art-Net) ─────────────────────
    def _send_blackout(self):
        """Envía RGB ceros a las 10 barras: blackout instantáneo."""
        try:
            if self.show_engine:
                empty = [bytearray(LEDS * 3) for _ in range(NUM_BARS)]
                self.show_engine.send_frame(empty)
                self.status.showMessage("⬛ Blackout enviado a las barras")
        except Exception as e:
            print(f"[!] Error en _send_blackout: {e}")

    # ── Tool mode ──────────────────────────────────────────────────────────
    def _set_tool(self, mode: str, effect_id: int = None,
                  channel_effect_id: str = None):
        self.tl_view.tool_mode = mode

        # v1.9 F1 — bimodal draw state
        if channel_effect_id is not None:
            self.tl_view.draw_kind = 'channel'
            self.tl_view.draw_channel_effect_id = channel_effect_id
            ch_lib = getattr(self, '_channel_lib', None)
            if ch_lib is None:
                from src.core.channel_effects import ChannelEffectLibrary
                ch_lib = ChannelEffectLibrary()
                self._channel_lib = ch_lib
            eff = ch_lib.get(channel_effect_id)
            if eff is not None:
                self.tl_view.draw_channel_category = eff.category
                self.tl_view.draw_channel_defaults = dict(eff.default_params)
            else:
                self.tl_view.draw_channel_category = None
                self.tl_view.draw_channel_defaults = {}
        elif effect_id is not None:
            self.tl_view.draw_kind = 'pixel'
            self.tl_view.draw_effect_id = effect_id

        if mode == TOOL_SELECT:
            # Reset draw state al volver a SELECT
            self.tl_view.draw_kind = 'pixel'
            self.tl_view.draw_channel_effect_id = None
            self.tl_view.draw_channel_category  = None
            self.tl_view.draw_channel_defaults  = {}
            self.tl_view.setCursor(Qt.ArrowCursor)
            self.browser.set_draw_mode(False)
            self._tool_select_act.setChecked(True)
        elif mode == TOOL_SLICE:
            self.tl_view.setCursor(Qt.SplitHCursor)
            self.browser.set_draw_mode(False)
            if hasattr(self, '_tool_slice_act'):
                self._tool_slice_act.setChecked(True)
            self.status.showMessage("✂ SLICE — clic sobre clip para cortarlo", 3000)
        else:
            self.tl_view.setCursor(Qt.CrossCursor)
            if self.tl_view.draw_kind == 'channel':
                lbl = self.tl_view.draw_channel_effect_id or "(sin efecto)"
                self.browser.set_draw_mode(True, lbl, kind='channel')
                self.status.showMessage(
                    f"⬡ DRAW Channel — arrastra en una fixture lane para crear "
                    f"clip '{lbl}'", 4000)
            else:
                # v1.9 F1: si no hay efecto elegido, mostrar label informativo
                # y un aviso en la status bar.
                if self.tl_view.draw_effect_id is None:
                    self.browser.set_draw_mode(True, "(sin efecto)", kind='pixel')
                    self.status.showMessage(
                        "⚠ Modo Draw activo — selecciona un efecto en el browser "
                        "para empezar a dibujar", 5000)
                else:
                    eff = self.library.get_effect(self.tl_view.draw_effect_id)
                    self.browser.set_draw_mode(True, eff.name if eff else "?", kind='pixel')
            self._tool_draw_act.setChecked(True)

    def _on_effect_draw_activate(self, eid: int):
        self._set_tool(TOOL_DRAW, eid)

    def _on_channel_effect_draw_activate(self, ceid: str):
        """v1.9 F1: activar Draw con un Channel Effect del browser."""
        self._set_tool(TOOL_DRAW, channel_effect_id=ceid)

    def _on_effect_add_to_bars(self, eid: int):
        try:
            bars = self.browser.selected_bars()
            if not bars: self.status.showMessage("⚠ Ninguna barra seleccionada."); return
            self._undo.snapshot(self.timeline.clips)
            t_ms = int(self.audio.get_time()*1000) if self.audio.loaded else 0
            eff  = self.library.get_effect(eid)
            if eff is None:
                self.status.showMessage(f"⚠ Efecto {eid} no encontrado"); return
            col  = FAMILY_COLORS.get(eff.family, '#3a7acc')
            ncs  = []
            for b in bars:
                layer = self.tl_view._next_free_layer(b, t_ms, t_ms+4000)
                c = Clip(track=b, start_ms=t_ms, end_ms=t_ms+4000,
                         effect_id=eid, scope='per_bar', label=eff.name, color=col, layer=layer)
                self.timeline.add(c); ncs.append(c)
            self.tl_view.selected_clips = ncs
            self.tl_view._update_snap_pts(); self.tl_view._rebuild_scene()
            self.tl_view.clips_selected.emit(ncs)
            self.status.showMessage(f"+ {eff.name}  ×{len(bars)} barras  desde {self.tl_view.ms_to_bar_beat(t_ms)[0]}:{self.tl_view.ms_to_bar_beat(t_ms)[1]}")
        except Exception as e:
            import traceback
            self.status.showMessage(f"⚠ Error añadiendo efecto: {e}")
            print(f"[_on_effect_add_to_bars] {traceback.format_exc()}")

    def _on_clip_created(self, clip: Clip):
        self.status.showMessage(f"✏ Creado: {clip.label}  Bar{clip.track} L{clip.layer}  {clip.start_ms}–{clip.end_ms} ms")

    # ── Undo/Redo ─────────────────────────────────────────────────────────
    def _do_undo(self):
        state = self._undo.undo()
        if state is None: self.status.showMessage("Nada que deshacer"); return
        self.timeline.clips = state
        self.tl_view.selected_clips.clear()
        self.tl_view._update_snap_pts(); self.tl_view._rebuild_scene()
        self.props.set_clips([])
        self.status.showMessage(f"↩ Undo  ({len(self.timeline.clips)} clips)")

    def _do_redo(self):
        state = self._undo.redo()
        if state is None: self.status.showMessage("Nada que rehacer"); return
        self.timeline.clips = state
        self.tl_view.selected_clips.clear()
        self.tl_view._update_snap_pts(); self.tl_view._rebuild_scene()
        self.props.set_clips([])
        self.status.showMessage(f"↪ Redo  ({len(self.timeline.clips)} clips)")

    # ── Copy / Paste ───────────────────────────────────────────────────────
    def _do_copy(self):
        self._clipboard = [copy.deepcopy(c) for c in self.tl_view.selected_clips]
        self.status.showMessage(f"📋 Copiados {len(self._clipboard)} clips")

    def _do_paste(self):
        if not self._clipboard: return
        self._undo.snapshot(self.timeline.clips)
        t_ms  = int(self.audio.get_time()*1000)
        min_s = min(c.start_ms for c in self._clipboard)
        ncs   = []
        for c in self._clipboard:
            nc = copy.deepcopy(c); nc.locked = False
            offset = c.start_ms - min_s
            nc.start_ms = t_ms + offset
            nc.end_ms   = nc.start_ms + (c.end_ms - c.start_ms)
            nc.layer    = self.tl_view._next_free_layer(nc.track, nc.start_ms, nc.end_ms)
            self.timeline.add(nc); ncs.append(nc)
        self.tl_view.selected_clips = ncs
        self.tl_view._update_snap_pts(); self.tl_view._rebuild_scene()
        self.tl_view.clips_selected.emit(ncs)
        self.status.showMessage(f"📋 Pegados {len(ncs)} clips en {t_ms} ms")

    # ── Selection callbacks ────────────────────────────────────────────────
    def _on_clips_selected(self, clips):
        self.props.set_clips(clips)
        n = len(clips)
        if n == 0:   self.status.showMessage("")
        elif n == 1:
            c = clips[0]; bar, beat = self.tl_view.ms_to_bar_beat(c.start_ms)
            self.status.showMessage(f"{c.label or c.effect_id}  Bar{c.track} L{c.layer}  {bar}:{beat}  {c.start_ms}–{c.end_ms} ms{'  🔒' if c.locked else ''}")
        else:
            self.status.showMessage(f"{n} clips seleccionados")

    def _on_delete_clips(self):
        self.tl_view.delete_selected(); self.props.set_clips([])

    # ── Transport ─────────────────────────────────────────────────────────
    def _on_play(self):
        if self.audio.loaded: self.audio.play(self.audio.get_time())
    def _on_pause(self): self.audio.pause()
    def _on_stop(self):
        self.audio.stop(); self.tl_view.set_current_time(0.0)
        if self.show_engine and self.send_artnet:
            self.show_engine.send_frame([bytearray(LEDS*3) for _ in range(NUM_BARS)])
    def _on_save(self):
        # v1.8 F3: guardar en el proyecto activo si existe
        if self._pm is not None and self._project is not None:
            try:
                self._pm.save_show(self.timeline)
                # También guardar el rig por si hubo cambios en el patch panel
                if self.fixture_rig is not None:
                    self._pm.save_rig(self.fixture_rig)
                self.status.showMessage(
                    f"💾 {len(self.timeline.clips)} clips guardados → {self._project.slug}/show.json")
                return
            except Exception as e:
                print(f"[!] save al proyecto: {e}")
        # Fallback legacy
        self.timeline.save()
        self.status.showMessage(f"💾 {len(self.timeline.clips)} clips guardados")

    def _on_save_as(self):
        """Guarda el timeline con un nombre en /shows_saved/."""
        saves_dir = PROJECT_DIR / 'shows_saved'
        saves_dir.mkdir(exist_ok=True)
        fname, _ = QFileDialog.getSaveFileName(
            self, "Guardar show como…", str(saves_dir), "Show JSON (*.json)")
        if not fname:
            return
        try:
            self.timeline.save(fname)
            self.status.showMessage(f"💾 Guardado en {Path(fname).name}", 4000)
        except Exception as e:
            self.status.showMessage(f"[!] Error guardando: {e}", 5000)

    def _on_open_show(self):
        """Carga un timeline desde /shows_saved/."""
        saves_dir = PROJECT_DIR / 'shows_saved'
        saves_dir.mkdir(exist_ok=True)
        fname, _ = QFileDialog.getOpenFileName(
            self, "Abrir show…", str(saves_dir), "Show JSON (*.json)")
        if not fname:
            return
        try:
            new_tl = Timeline.load(fname)
            self.timeline.clips = new_tl.clips
            self.timeline.duration_ms = new_tl.duration_ms
            if new_tl.groups:
                self.timeline.groups = new_tl.groups
            self.tl_view.selected_clips.clear()
            self.tl_view._update_snap_pts()
            self.tl_view._rebuild_scene()
            try:
                self.props.refresh_groups(self.timeline.groups or [])
            except Exception:
                pass
            self.status.showMessage(
                f"📂 Cargado {Path(fname).name} ({len(self.timeline.clips)} clips)", 4000)
        except Exception as e:
            self.status.showMessage(f"[!] Error abriendo: {e}", 5000)
    def _on_clear(self):
        self._undo.snapshot(self.timeline.clips)
        self.timeline.clips.clear(); self.tl_view.selected_clips.clear()
        self.props.set_clips([]); self.tl_view._rebuild_scene()
        self.status.showMessage("Timeline vacía")

    # ── v1.8 F3: Gestión de proyectos ────────────────────────────────────────
    def _show_project_menu(self):
        """Muestra el menú de proyectos bajo el botón 📁."""
        menu = QMenu(self)
        menu.setStyleSheet("QMenu{background:#1a1a2a;color:#ccc;border:1px solid #333;}"
                           "QMenu::item:selected{background:#2a4a2a;}")
        # Proyecto activo (solo info)
        proj_name = self._project.name if self._project else "Sin proyecto"
        lbl = menu.addAction(f"Proyecto: {proj_name}")
        lbl.setEnabled(False)
        menu.addSeparator()

        # Listar proyectos disponibles
        if self._pm is not None:
            projects = self._pm.list_projects()
            for p in projects:
                icon = "✓ " if (self._project and p.slug == self._project.slug) else "   "
                act = menu.addAction(f"{icon}{p.name}")
                act.setData(p.slug)
        menu.addSeparator()
        menu.addAction("📂 Abrir proyecto…").setData('_open_dialog')
        menu.addAction("🆕 Nuevo proyecto…").setData('_new_dialog')

        action = menu.exec_(self._project_btn.mapToGlobal(
            self._project_btn.rect().bottomLeft()))
        if action is None:
            return
        data = action.data()
        if data == '_open_dialog':
            self._new_project_dialog(select_only=True)
        elif data == '_new_dialog':
            self._new_project_dialog(select_only=False)
        elif data and not data.startswith('_'):
            self._switch_project(data)

    def _new_project_dialog(self, select_only=False):
        """Diálogo para crear un nuevo proyecto o seleccionar uno existente."""
        from PyQt5.QtWidgets import QDialog, QFormLayout, QLineEdit, QDialogButtonBox

        dlg = QDialog(self)
        dlg.setWindowTitle("Nuevo proyecto" if not select_only else "Abrir proyecto")
        dlg.setStyleSheet("QDialog{background:#1a1a2a;color:#ddd;}"
                          "QLabel{color:#ccc;} QLineEdit{background:#252540;color:#ddd;"
                          "border:1px solid #444;padding:4px;}")
        dlg.resize(420, 220)
        lay = QFormLayout(dlg)

        slug_ed   = QLineEdit(); slug_ed.setPlaceholderText("mi_show  (sin espacios)")
        name_ed   = QLineEdit(); name_ed.setPlaceholderText("Mi Show 2026")
        audio_ed  = QLineEdit(); audio_ed.setPlaceholderText("Ruta absoluta al MP3/WAV")
        slug_ed.setObjectName("slug"); name_ed.setObjectName("name"); audio_ed.setObjectName("audio")

        def _browse():
            f, _ = QFileDialog.getOpenFileName(dlg, "Seleccionar audio…", str(PROJECT_DIR),
                                               "Audio (*.mp3 *.wav *.ogg *.flac)")
            if f:
                audio_ed.setText(f)
                if not name_ed.text():
                    name_ed.setText(Path(f).stem.replace('_', ' ').title())
                if not slug_ed.text():
                    slug_ed.setText(Path(f).stem.lower().replace(' ', '_'))

        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(_browse)
        audio_row = QWidget(); audio_row_lay = QHBoxLayout(audio_row)
        audio_row_lay.setContentsMargins(0,0,0,0)
        audio_row_lay.addWidget(audio_ed); audio_row_lay.addWidget(browse_btn)

        lay.addRow("Slug (carpeta):", slug_ed)
        lay.addRow("Nombre:", name_ed)
        lay.addRow("Audio:", audio_row)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addRow(btns)

        if dlg.exec_() != QDialog.Accepted:
            return
        slug  = slug_ed.text().strip().replace(' ', '_')
        name  = name_ed.text().strip() or slug
        audio = audio_ed.text().strip()
        if not slug or not audio:
            self.status.showMessage("[!] Slug y audio son obligatorios", 4000)
            return

        # Crear proyecto
        from pathlib import Path as _Path
        audio_p = _Path(audio)
        # Intentar deducir slug de análisis
        from src.analysis.analyzer_service import discover_analyzed_songs, ANALIZADAS_DIR
        known = discover_analyzed_songs()
        analysis_slug = ''
        stem = audio_p.stem.lower().replace(' ', '_').replace('-', '_')
        for s in known:
            if s == stem or s.startswith(stem[:12]):
                analysis_slug = s
                break

        if self._pm is not None:
            new_proj = self._pm.create_project(
                slug=slug, name=name, audio_path=str(audio_p),
                analysis_slug=analysis_slug)
            self._switch_project(new_proj.slug)

    def _switch_project(self, slug: str):
        """Cambia al proyecto indicado: guarda el actual y carga el nuevo."""
        if self._pm is None:
            return
        if self._project and self._project.slug == slug:
            return  # ya estamos en ese proyecto

        # Guardar proyecto actual
        try:
            self._pm.save_show(self.timeline)
            if self.fixture_rig:
                self._pm.save_rig(self.fixture_rig)
        except Exception as e:
            print(f"[project] Error guardando proyecto actual: {e}")

        # Cargar el nuevo
        new_proj = self._pm.open_project(slug)
        if new_proj is None:
            self.status.showMessage(f"[!] Proyecto '{slug}' no encontrado", 4000)
            return

        self._project = new_proj
        try:
            # Audio
            from pathlib import Path as _Path
            new_audio = _Path(new_proj.audio_path)
            self.waveform = WaveformData(new_audio)
            self.audio.load(new_audio)

            # Análisis
            from src.analysis.analyzer_service import AnalysisService, default_service, ANALIZADAS_DIR
            if new_proj.analysis_slug:
                self.analysis = AnalysisService(ANALIZADAS_DIR / new_proj.analysis_slug)
            else:
                self.analysis = default_service()
            summary = self.analysis.summary
            bpm = float(summary.get('bpm') or 128.0)
            self._bpm = bpm
            dur_ms = int((summary.get('duration_s') or 165) * 1000)

            # Timeline
            if new_proj.show_file.is_file():
                loaded = Timeline.load(new_proj.show_file)
                if loaded.clips:
                    self.timeline.clips = loaded.clips
                    self.timeline.groups = loaded.groups
                    self.timeline.cue_points = loaded.cue_points
                    self.timeline.duration_ms = dur_ms
                else:
                    self.timeline = make_demo_timeline(dur_ms)
            else:
                self.timeline = make_demo_timeline(dur_ms)

            # Rig
            from fixtures import FixtureRig, build_default_wled_rig
            if new_proj.rig_file.is_file():
                self.fixture_rig = FixtureRig.load(new_proj.rig_file)
            else:
                self.fixture_rig = build_default_wled_rig()
            self.tl_view.fixture_rig = self.fixture_rig

            # Markers
            self.markers = {
                'beats':    self.analysis.list_beats(),
                'sections': [s.start for s in self.analysis.list_sections()],
                'kicks':    [e.time_sec for e in self.analysis.list_events('kick')],
            }
            self.tl_view.markers = self.markers

            # Rebuild UI
            self.tl_view.selected_clips.clear()
            self.tl_view.timeline = self.timeline
            self.tl_view._update_snap_pts()
            self.tl_view._rebuild_scene()
            try:
                self.props.refresh_groups(self.timeline.groups or [])
            except Exception:
                pass

            # Actualizar botón de proyecto
            proj_name = new_proj.name[:20]
            self._project_btn.setText(f"📁 {proj_name}")

            self.status.showMessage(
                f"📁 Proyecto cargado: {new_proj.name} ({len(self.timeline.clips)} clips)", 5000)
            print(f"[project] Proyecto activo: {new_proj.name!r} ({new_proj.slug})")
        except Exception as e:
            self.status.showMessage(f"[!] Error cargando proyecto: {e}", 5000)
            print(f"[!] _switch_project: {e}")
            import traceback; traceback.print_exc()

    # ── v1.8 F5: Exportar ────────────────────────────────────────────────────
    def _export_format(self, fmt: str):
        """Exporta el show al formato indicado ('csv_clips' | 'qlc')."""
        from exporter import export_clips_csv, export_qlc_workspace

        # Directorio destino: exports/ dentro del proyecto activo o del directorio raiz
        if self._project is not None:
            exports_dir = self._project.folder / 'exports'
        else:
            exports_dir = PROJECT_DIR / 'exports'
        exports_dir.mkdir(parents=True, exist_ok=True)

        song_name = (self._project.name if self._project else 'show')

        if fmt == 'csv_clips':
            default_name = f"{song_name.replace(' ', '_')}_clips.csv"
            fname, _ = QFileDialog.getSaveFileName(
                self, "Exportar clips como CSV…",
                str(exports_dir / default_name),
                "CSV (*.csv)")
            if not fname:
                return
            try:
                n = export_clips_csv(self.timeline, fname)
                self.status.showMessage(
                    f"📋 Exportado: {n} clips -> {Path(fname).name}", 5000)
            except Exception as e:
                self.status.showMessage(f"[!] Error exportando CSV: {e}", 5000)

        elif fmt == 'qlc':
            default_name = f"{song_name.replace(' ', '_')}.qxw"
            fname, _ = QFileDialog.getSaveFileName(
                self, "Exportar QLC+ workspace…",
                str(exports_dir / default_name),
                "QLC+ Workspace (*.qxw)")
            if not fname:
                return
            try:
                stats = export_qlc_workspace(
                    self.timeline, self.fixture_rig, fname,
                    song_name=song_name)
                self.status.showMessage(
                    f"💡 QLC+ exportado: {stats['fixtures']} fixtures, "
                    f"{stats['scenes']} scenes -> {Path(fname).name}", 5000)
            except Exception as e:
                self.status.showMessage(f"[!] Error exportando QLC+: {e}", 5000)

    # ── Ruler toggle ──────────────────────────────────────────────────────
    def _toggle_ruler(self):
        self.tl_view.ruler_mode = 'time' if self.tl_view.ruler_mode=='bars' else 'bars'
        self._ruler_btn.setText(self.tl_view.ruler_mode.upper()); self.tl_view._rebuild_scene()

    # ── Align ─────────────────────────────────────────────────────────────
    def _align_starts(self):
        c=self.tl_view.selected_clips
        if len(c)<2: return
        self._undo.snapshot(self.timeline.clips)
        t=min(x.start_ms for x in c)
        for x in c:
            if x.locked: continue
            d=x.end_ms-x.start_ms; x.start_ms=t; x.end_ms=t+d
        self.tl_view._rebuild_scene()
    def _align_ends(self):
        c=self.tl_view.selected_clips
        if len(c)<2: return
        self._undo.snapshot(self.timeline.clips)
        t=max(x.end_ms for x in c)
        for x in c:
            if x.locked: continue
            d=x.end_ms-x.start_ms; x.end_ms=t; x.start_ms=t-d
        self.tl_view._rebuild_scene()
    def _distribute(self):
        c=self.tl_view.selected_clips
        if len(c)<3: return
        self._undo.snapshot(self.timeline.clips)
        sc=sorted([x for x in c if not x.locked], key=lambda x:x.start_ms)
        tot=sum(x.end_ms-x.start_ms for x in sc)
        gap=max(0,(sc[-1].end_ms-sc[0].start_ms-tot)//(len(sc)-1))
        pos=sc[0].start_ms
        for x in sc:
            d=x.end_ms-x.start_ms; x.start_ms=pos; x.end_ms=pos+d; pos+=d+gap
        self.tl_view._rebuild_scene()
    def _equalize_duration(self):
        c=self.tl_view.selected_clips
        if len(c)<2: return
        self._undo.snapshot(self.timeline.clips)
        d=c[0].end_ms-c[0].start_ms
        for x in c[1:]:
            if not x.locked: x.end_ms=x.start_ms+d
        self.tl_view._rebuild_scene()

    # ── Keyboard ──────────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        k, m = event.key(), event.modifiers()
        ctrl  = bool(m & Qt.ControlModifier)
        shift = bool(m & Qt.ShiftModifier)

        # Escape → back to Select tool
        if k == Qt.Key_Escape:
            self._set_tool(TOOL_SELECT); return

        # Backspace también borra (Delete está cubierto por el ShortcutManager)
        if k == Qt.Key_Backspace:
            self._on_delete_clips(); return
        # Ctrl+Y como alternativa a Ctrl+Shift+Z (Redo)
        if ctrl and k == Qt.Key_Y:
            self._do_redo(); return
        # NOTA: Space, Delete, Ctrl+Z/Shift+Z/C/V/A/S/L/U los maneja ShortcutManager
        # → eliminados de aquí para evitar dobles disparos.

        # Zoom + / -
        if k == Qt.Key_Plus  or k == Qt.Key_Equal:
            self.tl_view.set_zoom(self.tl_view.px_per_sec * 1.25)
            self._zoom_sl.setValue(int(self.tl_view.px_per_sec)); return
        if k == Qt.Key_Minus:
            self.tl_view.set_zoom(self.tl_view.px_per_sec / 1.25)
            self._zoom_sl.setValue(int(self.tl_view.px_per_sec)); return

        # Expand to adjacent marks
        if ctrl and shift and k == Qt.Key_Left:
            self._undo.snapshot(self.timeline.clips)
            self.tl_view.expand_to_prev_mark(); return
        if ctrl and shift and k == Qt.Key_Right:
            self._undo.snapshot(self.timeline.clips)
            self.tl_view.expand_to_next_mark(); return

        # Bookmarks
        num_key = None
        for qt_k, n in [(Qt.Key_0,0),(Qt.Key_1,1),(Qt.Key_2,2),(Qt.Key_3,3),(Qt.Key_4,4),
                        (Qt.Key_5,5),(Qt.Key_6,6),(Qt.Key_7,7),(Qt.Key_8,8),(Qt.Key_9,9)]:
            if k == qt_k: num_key = n; break
        if num_key is not None:
            if shift:   # Shift+N → set bookmark
                self.tl_view.bookmarks[num_key] = int(self.audio.get_time()*1000)
                self.tl_view._rebuild_scene()
                self.status.showMessage(f"📌 Bookmark {num_key} = {self.audio.get_time():.2f}s"); return
            elif ctrl:  # Ctrl+N → jump to bookmark
                t_ms = self.tl_view.bookmarks.get(num_key)
                if t_ms is not None:
                    self.audio.seek(t_ms/1000.0)
                    self.status.showMessage(f"📌 → Bookmark {num_key} = {t_ms/1000:.2f}s"); return

        # Seek arrows
        step = 0.1 if shift else 1.0
        if k == Qt.Key_Left:  self.audio.seek(max(0.0, self.audio.get_time()-step)); return
        if k == Qt.Key_Right: self.audio.seek(min(self.audio.duration_s, self.audio.get_time()+step)); return
        if k == Qt.Key_Home:  self.audio.seek(0.0); return
        if k == Qt.Key_End:   self.audio.seek(self.audio.duration_s); return

        super().keyPressEvent(event)

    # ── Tick ──────────────────────────────────────────────────────────────
    def _tick(self):
        try:
            t = self.audio.get_time()
            # Loop region: si está activa y el audio rebasa loop_end, vuelve al start
            ls = self.tl_view._loop_start_ms
            le = self.tl_view._loop_end_ms
            if (self.audio.playing and ls is not None and le is not None
                    and le > ls and t * 1000 >= le):
                self.audio.seek(ls / 1000.0)
                t = self.audio.get_time()
            self.tl_view.set_current_time(t)
            bar, beat = self.tl_view.ms_to_bar_beat(t*1000)
            m, s = int(t)//60, t%60
            self._time_lbl.setText(f"{bar}:{beat}  {m}:{s:04.1f}")
            if self.audio.playing and abs(t-self._last_scroll_t)>0.25:
                self._last_scroll_t = t
                x  = self.tl_view.time_to_x(t)
                vw = self.tl_view.viewport().width()
                sb = self.tl_view.horizontalScrollBar()
                if x>sb.value()+vw*0.80 or x<sb.value()+HEADER_W:
                    sb.setValue(max(0,int(x-vw*0.30)))
            frame = self._compute_frame(t)
            self.preview.update_frame(frame)
            # Refrescar minimap throttled (5 fps en vez de 30 — repaint completo es caro)
            if hasattr(self, 'minimap'):
                import time as _tt
                if not hasattr(self, '_minimap_last_t'):
                    self._minimap_last_t = 0.0
                _now = _tt.monotonic()
                if _now - self._minimap_last_t > 0.2:
                    self.minimap.update()
                    self._minimap_last_t = _now
            # Info de sección actual (si hay show_engine cargado)
            try:
                if self.show_engine and self.show_engine.state:
                    self.preview.set_time_info(t, self.show_engine.state.section_at(t))
                else:
                    self.preview.set_time_info(t, 0)
            except Exception:
                pass
            if self.send_artnet and self.show_engine and self.audio.playing:
                self.show_engine.send_frame([bytearray(frame[b].flatten().astype(np.uint8)) for b in range(NUM_BARS)])
        except Exception as e:
            import traceback
            print(f"[_tick error] {e}\n{traceback.format_exc()}")

    def _resolve_scope_bars(self, scope: str) -> List[int]:
        """
        Devuelve la lista de barras destino según el scope del clip.
          - 'per_bar' / 'global' → []  (se trata aparte)
          - 'group:NOMBRE' o 'group_set:NOMBRE' → barras resueltas del grupo
        """
        if not isinstance(scope, str):
            return []
        if scope.startswith('group:') or scope.startswith('group_set:'):
            target_name = scope.split(':', 1)[1]
            groups = getattr(self.timeline, 'groups', []) or []
            for g in groups:
                if g.name == target_name:
                    return g.resolve_bars(groups)
        return []

    # Cached audio context (avoid recreating dicts/arrays 30 fps)
    _CACHED_ACTX = None
    _BUCKET_MS = 500  # 0.5 s por bucket: típicamente 3-6 clips por bucket

    def _build_clip_bucket_index(self):
        """
        Construye un índice {bucket: [clips]} para encontrar clips activos
        en O(1)+filter en vez de iterar 1000+ clips por frame.
        """
        buckets = {}
        for c in self.timeline.clips:
            b_lo = max(0, c.start_ms // self._BUCKET_MS)
            b_hi = max(b_lo, c.end_ms // self._BUCKET_MS)
            for b in range(b_lo, b_hi + 1):
                buckets.setdefault(b, []).append(c)
        # Ordenar cada bucket por layer (para que el render respete capas)
        for b in buckets:
            buckets[b].sort(key=lambda c: c.layer)
        self._clip_bucket_index = buckets
        self._clip_bucket_index_n = len(self.timeline.clips)

    def _compute_frame(self, t_s):
        frame = np.zeros((NUM_BARS,LEDS,3),dtype=np.uint8)
        t_ms  = int(t_s*1000)
        # Cache audio context (era recreado en cada frame con arrays nuevos)
        if TimelineEditorWindow._CACHED_ACTX is None:
            TimelineEditorWindow._CACHED_ACTX = {
                'rms': 0.5, 'energy': 0.5, 'flux': 0.3, 'centroid': 4000, 'zcr': 0.2,
                'mfcc': np.zeros(13, dtype=np.float32),
                'chroma': np.full(12, 0.5, dtype=np.float32),
                'tonnetz': np.zeros(6, dtype=np.float32),
                'contrast': np.full(7, 30, dtype=np.float32),
                'mel_bands': np.full(8, -25, dtype=np.float32),
            }
        actx = TimelineEditorWindow._CACHED_ACTX
        # (Re)construir el bucket index si el número de clips cambió
        if (not hasattr(self, '_clip_bucket_index')
                or self._clip_bucket_index_n != len(self.timeline.clips)):
            self._build_clip_bucket_index()
        bucket = t_ms // self._BUCKET_MS
        candidates = self._clip_bucket_index.get(bucket, ())
        for clip in candidates:
            # Filtro fino: el clip debe contener t_ms
            if clip.start_ms > t_ms or clip.end_ms <= t_ms:
                continue
            # Clip muted individual: skip render
            if getattr(clip, 'muted', False):
                continue
            # Mute/Solo filter: si el track visual del clip está silenciado
            # (o si hay solos y este no lo es), saltamos el render.
            vt_chk = self.tl_view._visual_track_of_clip(clip)
            if not self.tl_view._track_is_audible(vt_chk):
                continue
            eff = self.library.get_effect(clip.effect_id)
            if not eff: continue
            try:
                # OPT: pasar el frame por referencia (sin copy). Los efectos NO
                # deben modificar bars_state — crean su propio array. Esto
                # ahorra ~3 KB copy × N clips × 30 fps.
                r = eff.render(elapsed_time=t_ms-clip.start_ms, bars_state=frame,
                               audio_context=actx, **clip.params)

                # Caso 1: clip apuntando a un grupo o grupo-de-grupos
                group_bars = self._resolve_scope_bars(clip.scope)
                if group_bars:
                    if r.shape == (1, LEDS, 3):
                        # efecto per-bar (1 fila): aplica esa fila a cada barra del grupo
                        for b in group_bars:
                            if 0 <= b < NUM_BARS:
                                frame[b] = np.maximum(frame[b], r[0])
                    elif r.shape == (NUM_BARS, LEDS, 3):
                        # efecto global (10 filas): coger las filas de las barras del grupo
                        for b in group_bars:
                            if 0 <= b < NUM_BARS:
                                frame[b] = np.maximum(frame[b], r[b])
                    continue

                # Caso 2 (original): per_bar / global
                if r.shape==(1,LEDS,3) and 0<=clip.track<NUM_BARS:
                    frame[clip.track] = np.maximum(frame[clip.track], r[0]) if clip.layer>0 else r[0]
                elif r.shape==(NUM_BARS,LEDS,3):
                    frame = np.maximum(frame,r) if clip.scope=='global' else (
                        frame.__setitem__((clip.track,), np.maximum(frame[clip.track],r[clip.track])) or frame)
            except: pass
        return frame


# ═══════════════════════════════════════════════════════════════
def main():
    import traceback, datetime

    # Escribir errores no capturados al disco además de consola
    _log = open(PROJECT_DIR / 'timeline_editor_crash.log', 'w', encoding='utf-8')

    def _log_write(msg: str):
        ts = datetime.datetime.now().strftime('%H:%M:%S.%f')
        line = f"[{ts}] {msg}\n"
        _log.write(line); _log.flush()
        print(line, end='')

    def _except_hook(t, v, tb):
        _log_write("=== EXCEPCIÓN NO CAPTURADA ===")
        _log_write(''.join(traceback.format_exception(t, v, tb)))
    sys.excepthook = _except_hook

    _log_write("Arrancando Timeline Editor v0.5")

    app = QApplication(sys.argv); app.setStyle('Fusion')
    pal = app.palette()
    pal.setColor(pal.Window,          QColor(18,18,26))
    pal.setColor(pal.WindowText,      QColor(220,220,230))
    pal.setColor(pal.Base,            QColor(22,22,34))
    pal.setColor(pal.AlternateBase,   QColor(28,28,40))
    pal.setColor(pal.Text,            QColor(220,220,230))
    pal.setColor(pal.Button,          QColor(40,40,58))
    pal.setColor(pal.ButtonText,      QColor(220,220,230))
    pal.setColor(pal.Highlight,       QColor(50,100,190))
    pal.setColor(pal.HighlightedText, Qt.white)
    app.setPalette(pal)

    try:
        _log_write("Creando TimelineEditorWindow...")
        win = TimelineEditorWindow()
        _log_write("Ventana creada OK — mostrando")
        win.show()
        _log_write("Entrando en event loop")
        code = app.exec_()
        _log_write(f"Event loop terminó con código {code}")
        _log.close()
        sys.exit(code)
    except Exception:
        _log_write("=== CRASH EN MAIN ===")
        _log_write(traceback.format_exc())
        _log.close()
        raise

if __name__ == '__main__':
    main()
