"""
analyzer_panel.py — Tab Analyzer para curar el análisis musical (Fase C v1.6).

Lo que pinta:
  • Waveform horizontal con bandera de tiempo (playhead) sincronizada con audio
  • Overlays toggleables: beats, downbeats, kicks, snares, hats, secciones,
    cue seeds, eventos manuales, eventos disabled
  • Right panel con:
      - Tabla de SECCIONES editables (name + type combo)
      - Tabla de EVENTOS con filtro y acciones (disable / delete)
      - Sliders de umbrales y botón "Guardar curación"

Conecta con `analyzer_service.AnalysisService`. Cuando algo de la curación
cambia, llama `curation.save()` y emite la señal `curation_changed` para que
el timeline principal repinte sus overlays.

API pública:
  panel = AnalyzerPanel(analysis_service, get_playhead_sec, parent=None)
  panel.curation_changed → señal sin args, emitida al guardar curación
  panel.set_playhead(t_sec)  # llamar desde shared_tick
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

import numpy as np

from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QRectF
from PyQt5.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont, QFontMetrics, QPolygonF,
    QPixmap, QImage,
)
from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QCheckBox,
    QTableWidget, QTableWidgetItem, QComboBox, QHeaderView, QSlider,
    QSplitter, QGroupBox, QSpinBox, QDoubleSpinBox, QMessageBox,
    QAbstractItemView, QMenu, QLineEdit, QFrame, QInputDialog,
    QScrollArea, QShortcut, QToolButton, QCompleter,
)
from PyQt5.QtGui import QKeySequence

from src.analysis.analyzer_service import (
    AnalysisService, SECTION_TYPES, EVENT_KINDS, Event, Section,
)


# ───────────────────────────────────────────────────────────────
# Colores (paleta consistente con timeline_editor)
# ───────────────────────────────────────────────────────────────

C_BG          = QColor(14,  14,  20)
C_WAVE        = QColor(80, 140, 220, 200)
C_WAVE_DIM    = QColor(50,  90, 160, 100)
C_PLAYHEAD    = QColor(255, 220, 80)
C_BEAT        = QColor( 60, 200, 120, 130)
C_DOWNBEAT    = QColor( 90, 255, 150, 200)
C_KICK        = QColor(255,  80,  80, 200)
C_SNARE       = QColor( 80, 160, 255, 200)
C_HAT         = QColor(255, 220,  80, 180)
C_SECTION     = QColor(255, 120, 240, 220)
C_SECTION_LBL = QColor(255, 200, 250)
C_MANUAL      = QColor(255, 255, 100, 220)
C_DISABLED    = QColor(140, 140, 140, 120)
C_CUE_SEED    = QColor(120, 220, 255, 200)


# ───────────────────────────────────────────────────────────────
# WaveformCanvas — renderiza waveform + overlays + playhead
# ───────────────────────────────────────────────────────────────

class WaveformCanvas(QWidget):
    """Widget custom que pinta la waveform anotada con overlays.

    El canvas tiene un ANCHO INTERNO que crece con el zoom (zoom_factor):
    a zoom=1.0, todo el audio cabe en `base_width_px`. A zoom=5.0, ocupa
    5× ese ancho y se muestra dentro de un QScrollArea horizontal.

    Emite:
      time_clicked(float)         → click izquierdo en una posición temporal
      section_dbl_clicked(int)    → doble click sobre una sección (abre editor)
      context_at(float, QPoint)   → click derecho con tiempo + posición global
      zoom_changed(float)         → zoom_factor cambió
    """
    time_clicked        = pyqtSignal(float)
    section_dbl_clicked = pyqtSignal(int)
    context_at          = pyqtSignal(float, object)  # (time_sec, QPoint global)
    zoom_changed        = pyqtSignal(float)

    BASE_WIDTH_PX = 1200      # ancho a zoom = 1.0 (todo el audio visible)
    MIN_ZOOM = 1.0
    MAX_ZOOM = 40.0           # 48000 px max (limita memoria del cache)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setMouseTracking(True)
        self.peaks: np.ndarray = np.zeros(1, dtype=np.float32)
        self.energy: np.ndarray = np.zeros(1, dtype=np.float32)  # Energy curve for visualization
        self.duration_s: float = 0.0
        # Zoom: 1.0 = todo el audio en BASE_WIDTH_PX
        self._zoom = 1.0
        # Cache del fondo (waveform + overlays estáticos). Sólo el playhead
        # se pinta dinámicamente encima. Reduce el coste del repaint de
        # ~30 fps de TODO el canvas a sólo copiar un pixmap + 1 línea.
        self._bg_cache: Optional[QPixmap] = None
        self._bg_cache_key = None  # tupla que invalida el cache
        # Overlays
        self.beats: List[float] = []
        self.downbeats: List[float] = []
        self.kicks: List[float] = []
        self.snares: List[float] = []
        self.hats: List[float] = []
        self.sections: List[Section] = []
        self.manual_events: List[Event] = []
        self.disabled_events: List[tuple] = []  # (t, kind, tol_ms)
        self.cue_seeds: List[dict] = []
        # Toggles
        self.show_beats = False
        self.show_downbeats = True
        self.show_kicks = True
        self.show_snares = False
        self.show_hats = False
        self.show_sections = True
        self.show_manual = True
        self.show_disabled = True
        self.show_cue_seeds = True
        self.show_energy = False  # Energy visualization toggle
        # Playhead
        self.playhead_s: float = 0.0
        # Scroll/zoom no implementado todavía: vista completa scaleada al width.
        self._hovered_section: Optional[Section] = None

    # ── Datos ──────────────────────────────────────────────────
    def set_waveform(self, peaks: np.ndarray, duration_s: float):
        self.peaks = peaks
        self.duration_s = float(duration_s)
        self.invalidate_bg_cache()

    def set_energy(self, energy: np.ndarray):
        """Set the energy curve for visualization (normalized 0-1)."""
        self.energy = energy if energy is not None else np.zeros(1, dtype=np.float32)
        self.invalidate_bg_cache()

    def set_overlays(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        self.invalidate_bg_cache()

    def set_playhead(self, t_sec: float):
        if abs(t_sec - self.playhead_s) < 1e-3:
            return
        # OPT: solo invalidar la franja afectada (vieja + nueva posición),
        # no todo el canvas. El fondo viene de pixmap cacheado y la línea
        # vertical solo cubre unos 16-20 px de ancho.
        old_x = int(self.time_to_x(self.playhead_s))
        new_x = int(self.time_to_x(float(t_sec)))
        self.playhead_s = float(t_sec)
        H = self.height()
        lo = min(old_x, new_x) - 10
        hi = max(old_x, new_x) + 10
        self.update(lo, 0, hi - lo, H)

    # ── Zoom ───────────────────────────────────────────────────
    @property
    def zoom_factor(self) -> float:
        return self._zoom

    def virtual_width(self) -> int:
        """Ancho que el canvas debería tener (resp. a su parent scroll)."""
        return int(self.BASE_WIDTH_PX * self._zoom)

    def sizeHint(self):
        from PyQt5.QtCore import QSize
        return QSize(self.virtual_width(), 200)

    def minimumSizeHint(self):
        from PyQt5.QtCore import QSize
        return QSize(self.virtual_width(), 180)

    def set_zoom(self, z: float, anchor_x: Optional[float] = None,
                 viewport_width: Optional[int] = None):
        """Cambia el zoom manteniendo `anchor_x` (en coord del canvas) en su
        sitio relativo dentro del viewport (si se pasa)."""
        z = max(self.MIN_ZOOM, min(self.MAX_ZOOM, float(z)))
        if abs(z - self._zoom) < 1e-3:
            return
        # tiempo del ancla actual
        anchor_t = self.x_to_time(anchor_x) if anchor_x is not None else None
        self._zoom = z
        # Reajustar tamaño
        self.updateGeometry()
        self.resize(self.virtual_width(), self.height())
        self.update()
        self.zoom_changed.emit(self._zoom)
        # Devolvemos la nueva x del ancla para que el parent reajuste el scroll
        if anchor_t is not None:
            self._anchor_new_x = self.time_to_x(anchor_t)
        else:
            self._anchor_new_x = None

    # ── Coordenadas ───────────────────────────────────────────
    def time_to_x(self, t: float) -> float:
        if self.duration_s <= 0:
            return 0.0
        return (t / self.duration_s) * self.virtual_width()

    def x_to_time(self, x: float) -> float:
        w = self.virtual_width()
        if w <= 0:
            return 0.0
        return (x / w) * self.duration_s

    # ── Painting ──────────────────────────────────────────────
    def _cache_key(self):
        """Tupla que identifica el estado del fondo. Si cambia → cache dirty."""
        return (
            self.width(), self.height(),
            int(self.duration_s * 1000),
            self.show_beats, self.show_downbeats, self.show_kicks,
            self.show_snares, self.show_hats, self.show_sections,
            self.show_manual, self.show_disabled, self.show_cue_seeds,
            self.show_energy, len(self.energy),
            len(self.beats), len(self.downbeats), len(self.kicks),
            len(self.snares), len(self.hats), len(self.sections),
            len(self.manual_events), len(self.disabled_events),
            len(self.cue_seeds),
        )

    def invalidate_bg_cache(self):
        self._bg_cache = None
        self._bg_cache_key = None
        self.update()

    def paintEvent(self, ev):
        # Si el cache es válido, solo copia + dibuja el playhead
        key = self._cache_key()
        if self._bg_cache is None or self._bg_cache_key != key \
                or self._bg_cache.width() != self.width() \
                or self._bg_cache.height() != self.height():
            self._render_background_pixmap(key)

        p = QPainter(self)
        # Copia del cached background (clip al rect dirty para más velocidad)
        if self._bg_cache is not None:
            p.drawPixmap(ev.rect(), self._bg_cache, ev.rect())

        # Playhead encima (línea + triángulo arriba)
        if 0 <= self.playhead_s <= self.duration_s:
            H = self.height()
            x = self.time_to_x(self.playhead_s)
            if ev.rect().left() - 8 <= x <= ev.rect().right() + 8:
                p.setRenderHint(QPainter.Antialiasing, True)
                p.setPen(QPen(C_PLAYHEAD, 2))
                p.drawLine(int(x), 0, int(x), H)
                tri = QPolygonF([
                    QPointF(x - 6, 0), QPointF(x + 6, 0), QPointF(x, 8),
                ])
                p.setBrush(QBrush(C_PLAYHEAD))
                p.setPen(Qt.NoPen)
                p.drawPolygon(tri)
        p.end()

    def _render_background_pixmap(self, key):
        """Renderiza waveform + overlays estáticos en un QPixmap cacheado.
        Caro (1200..240000 columnas), pero solo se hace cuando cambia algo."""
        W = max(1, self.width())
        H = max(1, self.height())
        pix = QPixmap(W, H)
        pix.fill(C_BG)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing, True)
        self._paint_background(p, W, H)
        p.end()
        self._bg_cache = pix
        self._bg_cache_key = key

    def _paint_background(self, p: QPainter, W: int, H: int):
        mid = H / 2.0

        # 1) Waveform (peaks → barras simétricas) — vectorizado con numpy
        if len(self.peaks) > 1 and self.duration_s > 0:
            n = len(self.peaks)
            # Para cada columna pixel x ∈ [0, W), tomamos el max de peaks
            # en su rango asignado. Calculado en batch (mucho más rápido
            # que un drawLine por columna en Python puro).
            xs = np.arange(W, dtype=np.int64)
            i0 = (xs * n) // W
            # Si W >= n, ppp = 0 → cada columna mira 1 peak. Si W << n, ppp > 1.
            ppp = max(1, n // max(1, W))
            i1 = np.minimum(n, i0 + ppp)
            # Para evitar bucle Python: tomamos peaks[i0] (suficiente cuando ppp=1)
            if ppp == 1:
                amps = self.peaks[i0]
            else:
                # Cuando hay agregación: hacemos un loop más compacto pero
                # sólo afecta a pocos pixels (zoom < 1, hoy no usamos).
                amps = np.empty(W, dtype=np.float32)
                for k in range(W):
                    amps[k] = self.peaks[i0[k]:i1[k]].max() if i1[k] > i0[k] else 0
            h_arr = (amps * (H * 0.45)).astype(np.int32)
            top = (mid - h_arr).astype(np.int32)
            bot = (mid + h_arr).astype(np.int32)
            # Construir todas las líneas como un array de QLineF en una pasada
            from PyQt5.QtCore import QLineF
            lines = [QLineF(int(xs[k]), int(top[k]), int(xs[k]), int(bot[k]))
                     for k in range(W)]
            p.setPen(QPen(C_WAVE, 1))
            p.drawLines(lines)

        # 1.5) Energy visualization (semi-transparent band)
        if self.show_energy and len(self.energy) > 1 and self.duration_s > 0:
            n_energy = len(self.energy)
            xs = np.arange(W, dtype=np.int64)
            i0 = (xs * n_energy) // W
            ppp = max(1, n_energy // max(1, W))
            i1 = np.minimum(n_energy, i0 + ppp)
            if ppp == 1:
                energy_vals = self.energy[i0]
            else:
                energy_vals = np.empty(W, dtype=np.float32)
                for k in range(W):
                    energy_vals[k] = self.energy[i0[k]:i1[k]].max() if i1[k] > i0[k] else 0
            # Energy curve as upper band (0-1 normalized)
            energy_h = (energy_vals * (H * 0.35)).astype(np.int32)
            energy_top = (mid - energy_h).astype(np.int32)
            # Build polygon for filled band
            poly_pts = []
            for k in range(W):
                poly_pts.append(QPointF(int(xs[k]), int(energy_top[k])))
            for k in range(W - 1, -1, -1):
                poly_pts.append(QPointF(int(xs[k]), int(mid)))
            from PyQt5.QtGui import QPolygonF
            poly = QPolygonF(poly_pts)
            # Semi-transparent orange/yellow energy color
            energy_color = QColor(255, 180, 60, 80)
            p.setBrush(QBrush(energy_color))
            p.setPen(Qt.NoPen)
            p.drawPolygon(poly)

        # 2) Boundaries de sección (líneas verticales con label)
        if self.show_sections and self.sections:
            f = QFont('Consolas', 9, QFont.Bold)
            p.setFont(f)
            fm = QFontMetrics(f)
            for s in self.sections:
                x = self.time_to_x(s.start)
                # Línea vertical
                p.setPen(QPen(C_SECTION, 1.5, Qt.DashLine))
                p.drawLine(int(x), 0, int(x), H)
                # Label: nombre curado o "section_N"
                label = s.name if s.name else s.label
                if s.type:
                    label += f"  [{s.type}]"
                p.setPen(QPen(C_SECTION_LBL))
                p.drawText(int(x) + 4, 12, label)

        # 3) Downbeats (más prominentes que beats)
        if self.show_downbeats and self.downbeats:
            p.setPen(QPen(C_DOWNBEAT, 1.5))
            for t in self.downbeats:
                x = self.time_to_x(t)
                p.drawLine(int(x), int(mid + H * 0.20), int(x), int(mid + H * 0.38))

        # 4) Beats (tick fino)
        if self.show_beats and self.beats:
            p.setPen(QPen(C_BEAT, 1.0))
            for t in self.beats:
                x = self.time_to_x(t)
                p.drawLine(int(x), int(mid + H * 0.30), int(x), int(mid + H * 0.40))

        # 5) Kicks (puntos rojos arriba)
        if self.show_kicks and self.kicks:
            p.setPen(QPen(C_KICK, 2))
            for t in self.kicks:
                x = self.time_to_x(t)
                p.drawLine(int(x), int(mid - H * 0.40), int(x), int(mid - H * 0.20))

        # 6) Snares
        if self.show_snares and self.snares:
            p.setPen(QPen(C_SNARE, 1.5))
            for t in self.snares:
                x = self.time_to_x(t)
                p.drawLine(int(x), int(mid - H * 0.25), int(x), int(mid - H * 0.10))

        # 7) Hats
        if self.show_hats and self.hats:
            p.setPen(QPen(C_HAT, 1.0))
            for t in self.hats:
                x = self.time_to_x(t)
                p.drawLine(int(x), int(mid - H * 0.13), int(x), int(mid - H * 0.06))

        # 8) Eventos manuales (icono ✚)
        if self.show_manual and self.manual_events:
            p.setPen(QPen(C_MANUAL, 2))
            for ev in self.manual_events:
                x = self.time_to_x(ev.time_sec)
                p.drawLine(int(x), int(mid - H * 0.45), int(x), int(mid + H * 0.45))
                # marca cruz arriba
                p.drawLine(int(x) - 4, 18, int(x) + 4, 18)
                p.drawLine(int(x), 14, int(x), 22)

        # 9) Eventos disabled (tachado tenue)
        if self.show_disabled and self.disabled_events:
            p.setPen(QPen(C_DISABLED, 1, Qt.DotLine))
            for (t, kind, tol_ms) in self.disabled_events:
                x = self.time_to_x(t)
                p.drawLine(int(x) - 4, int(mid), int(x) + 4, int(mid))
                p.drawLine(int(x), int(mid) - 4, int(x), int(mid) + 4)

        # 10) Cue seeds
        if self.show_cue_seeds and self.cue_seeds:
            p.setPen(QPen(C_CUE_SEED, 2, Qt.DashLine))
            for cs in self.cue_seeds:
                x = self.time_to_x(cs.get('time_sec', 0))
                p.drawLine(int(x), 0, int(x), int(H * 0.10))
        # Playhead se pinta DINÁMICAMENTE en paintEvent (no aquí).

    def wheelEvent(self, ev):
        """Ctrl+wheel → zoom in/out manteniendo el cursor como ancla.
        Sin Ctrl → scroll horizontal en el QScrollArea padre."""
        if ev.modifiers() & Qt.ControlModifier:
            anchor_x = ev.x()
            factor = 1.25 if ev.angleDelta().y() > 0 else 1.0 / 1.25
            self.set_zoom(self._zoom * factor, anchor_x=anchor_x)
            ev.accept()
            return
        # Scroll horizontal: subir la rueda recula tiempo, bajarla avanza
        scroll = self._find_parent_scroll()
        if scroll is not None:
            sb = scroll.horizontalScrollBar()
            delta = ev.angleDelta().y()
            # paso ≈ 80px por click de rueda (proporcional al delta)
            sb.setValue(sb.value() - int(delta * 0.5))
            ev.accept()
        else:
            super().wheelEvent(ev)

    def _find_parent_scroll(self):
        """Busca el QScrollArea ancestro (si existe)."""
        w = self.parent()
        while w is not None:
            if isinstance(w, QScrollArea):
                return w
            w = w.parent()
        return None

    # ── Eventos de ratón ──────────────────────────────────────
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            t = self.x_to_time(ev.x())
            self.time_clicked.emit(t)
        elif ev.button() == Qt.RightButton:
            t = self.x_to_time(ev.x())
            self.context_at.emit(t, ev.globalPos())

    def mouseDoubleClickEvent(self, ev):
        t = self.x_to_time(ev.x())
        # Buscar sección que contiene ese tiempo
        for s in self.sections:
            if s.start <= t < s.end:
                self.section_dbl_clicked.emit(s.idx)
                return


# ───────────────────────────────────────────────────────────────
# Tabla de Secciones
# ───────────────────────────────────────────────────────────────

class SectionTable(QTableWidget):
    """Tabla editable: idx | name | type | start | end | duration."""
    section_edited = pyqtSignal(int, str, str)  # idx, name, type

    HEADERS = ['#', 'Nombre', 'Tipo', 'Inicio', 'Fin', 'Dur']

    def __init__(self, parent=None):
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.DoubleClicked
                             | QAbstractItemView.EditKeyPressed)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.itemChanged.connect(self._on_item_changed)
        self._loading = False

    def load_sections(self, sections: List[Section]):
        self._loading = True
        self.setRowCount(len(sections))
        for row, s in enumerate(sections):
            self.setItem(row, 0, QTableWidgetItem(str(s.idx)))
            self.item(row, 0).setFlags(self.item(row, 0).flags() & ~Qt.ItemIsEditable)
            self.setItem(row, 1, QTableWidgetItem(s.name))
            # Combo de tipo con autocomplete
            combo = QComboBox()
            combo.setEditable(True)  # libre permitido
            combo.addItem('')  # sin tipo
            for t in SECTION_TYPES:
                combo.addItem(t)
            if s.type:
                if s.type not in SECTION_TYPES:
                    combo.addItem(s.type)
                combo.setCurrentText(s.type)
            # Agregar autocomplete
            completer = QCompleter(SECTION_TYPES + [''], combo)
            completer.setCaseSensitivity(False)
            combo.setCompleter(completer)
            combo.currentTextChanged.connect(
                lambda new_type, r=row: self._on_type_changed(r, new_type)
            )
            self.setCellWidget(row, 2, combo)
            self.setItem(row, 3, QTableWidgetItem(f"{s.start:.2f}"))
            self.item(row, 3).setFlags(self.item(row, 3).flags() & ~Qt.ItemIsEditable)
            self.setItem(row, 4, QTableWidgetItem(f"{s.end:.2f}"))
            self.item(row, 4).setFlags(self.item(row, 4).flags() & ~Qt.ItemIsEditable)
            self.setItem(row, 5, QTableWidgetItem(f"{s.duration:.2f}"))
            self.item(row, 5).setFlags(self.item(row, 5).flags() & ~Qt.ItemIsEditable)
        self._loading = False

    def _on_item_changed(self, item):
        if self._loading:
            return
        if item.column() != 1:
            return
        row = item.row()
        idx = int(self.item(row, 0).text())
        name = item.text()
        combo: QComboBox = self.cellWidget(row, 2)
        type_ = combo.currentText() if combo else ''
        self.section_edited.emit(idx, name, type_)

    def _on_type_changed(self, row: int, new_type: str):
        if self._loading:
            return
        idx = int(self.item(row, 0).text())
        name_item = self.item(row, 1)
        name = name_item.text() if name_item else ''
        self.section_edited.emit(idx, name, new_type)


# ───────────────────────────────────────────────────────────────
# Tabla de Eventos
# ───────────────────────────────────────────────────────────────

class EventTable(QTableWidget):
    HEADERS = ['Tiempo', 'Tipo', 'Origen', 'Acción']
    event_disable_requested = pyqtSignal(float, str)
    event_delete_manual_requested = pyqtSignal(float, str)

    def __init__(self, parent=None):
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.horizontalHeader().setStretchLastSection(True)

    def load_events(self, events: List[Event]):
        self.setRowCount(len(events))
        for row, e in enumerate(events):
            self.setItem(row, 0, QTableWidgetItem(f"{e.time_sec:.3f}"))
            self.setItem(row, 1, QTableWidgetItem(e.kind))
            origin = e.source
            self.setItem(row, 2, QTableWidgetItem(origin))
            if origin == 'manual':
                btn = QPushButton('🗑 borrar')
                btn.clicked.connect(lambda _, t=e.time_sec, k=e.kind:
                                    self.event_delete_manual_requested.emit(t, k))
            else:
                btn = QPushButton('✖ disable')
                btn.clicked.connect(lambda _, t=e.time_sec, k=e.kind:
                                    self.event_disable_requested.emit(t, k))
            self.setCellWidget(row, 3, btn)


# ───────────────────────────────────────────────────────────────
# AnalyzerPanel — composición principal
# ───────────────────────────────────────────────────────────────

class AnalyzerPanel(QWidget):
    curation_changed = pyqtSignal()
    seek_requested   = pyqtSignal(float)   # cuando el usuario click en waveform
    play_requested   = pyqtSignal()
    pause_requested  = pyqtSignal()
    stop_requested   = pyqtSignal()

    def __init__(self, analysis: AnalysisService,
                 waveform_peaks: Optional[np.ndarray] = None,
                 parent=None):
        super().__init__(parent)
        self.analysis = analysis
        self._waveform_peaks = waveform_peaks if waveform_peaks is not None \
                               else np.zeros(1, dtype=np.float32)

        # Layout: Splitter horizontal — waveform a la izquierda, paneles a la derecha
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        # --- Barra superior con transport + toggles ---
        top = QHBoxLayout()
        top.addWidget(QLabel(f"<b>🎵 Analyzer</b> — {self.analysis.summary.get('file', '?')}"))
        # Transport
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(38)
        self.btn_play.setToolTip("Play / Pause (Espacio)")
        self.btn_play.clicked.connect(self._on_play_toggle)
        self.btn_stop = QPushButton("■")
        self.btn_stop.setFixedWidth(32)
        self.btn_stop.setToolTip("Stop (vuelve al inicio)")
        self.btn_stop.clicked.connect(self._on_stop)
        top.addWidget(self.btn_play)
        top.addWidget(self.btn_stop)
        # Zoom
        self.btn_zoom_out = QPushButton("➖")
        self.btn_zoom_out.setFixedWidth(32)
        self.btn_zoom_out.setToolTip("Zoom out (Ctrl+-)")
        self.btn_zoom_in = QPushButton("➕")
        self.btn_zoom_in.setFixedWidth(32)
        self.btn_zoom_in.setToolTip("Zoom in (Ctrl++)")
        self.btn_zoom_fit = QPushButton("⤢")
        self.btn_zoom_fit.setFixedWidth(32)
        self.btn_zoom_fit.setToolTip("Zoom fit (Ctrl+0)")
        self.btn_zoom_out.clicked.connect(lambda: self._apply_zoom_step(1/1.5))
        self.btn_zoom_in.clicked.connect(lambda: self._apply_zoom_step(1.5))
        self.btn_zoom_fit.clicked.connect(self._zoom_fit)
        top.addWidget(self.btn_zoom_out)
        top.addWidget(self.btn_zoom_in)
        top.addWidget(self.btn_zoom_fit)
        self.zoom_lbl = QLabel("1.0x")
        self.zoom_lbl.setStyleSheet("color:#aaa; font-family:Consolas; min-width:42px;")
        top.addWidget(self.zoom_lbl)
        top.addStretch()
        self.tog_energy = QCheckBox('energía')
        self.tog_beats = QCheckBox('beats')
        self.tog_downbeats = QCheckBox('downbeats')
        self.tog_downbeats.setChecked(True)
        self.tog_kicks = QCheckBox('kicks')
        self.tog_kicks.setChecked(True)
        self.tog_snares = QCheckBox('snares')
        self.tog_hats = QCheckBox('hats')
        self.tog_sections = QCheckBox('secciones')
        self.tog_sections.setChecked(True)
        self.tog_manual = QCheckBox('manuales')
        self.tog_manual.setChecked(True)
        self.tog_disabled = QCheckBox('disabled')
        self.tog_disabled.setChecked(True)
        for w in (self.tog_energy, self.tog_beats, self.tog_downbeats, self.tog_kicks,
                  self.tog_snares, self.tog_hats, self.tog_sections,
                  self.tog_manual, self.tog_disabled):
            w.toggled.connect(self._on_toggle)
            top.addWidget(w)
        root.addLayout(top)

        # --- Splitter principal ---
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # Lado izquierdo: waveform canvas dentro de scroll + label info
        left = QWidget()
        leftL = QVBoxLayout(left)
        leftL.setContentsMargins(0, 0, 0, 0)
        self.canvas = WaveformCanvas()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)   # respetar nuestro sizeHint
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.canvas)
        self.scroll.setStyleSheet("QScrollArea{border:1px solid #2a2a40;}")
        leftL.addWidget(self.scroll, 1)
        self.info_lbl = QLabel("")
        self.info_lbl.setStyleSheet("color:#aaa; font-family:Consolas; font-size:10px;")
        leftL.addWidget(self.info_lbl)
        splitter.addWidget(left)
        self.canvas.zoom_changed.connect(self._on_zoom_changed)

        # Lado derecho: sub-paneles
        right = QWidget()
        rightL = QVBoxLayout(right)
        rightL.setContentsMargins(0, 0, 0, 0)

        # Secciones
        gb_sec = QGroupBox("Secciones (doble-click sobre canvas para editar)")
        gl = QVBoxLayout(gb_sec)
        self.section_table = SectionTable()
        gl.addWidget(self.section_table)
        rightL.addWidget(gb_sec, 1)

        # Eventos
        gb_ev = QGroupBox("Eventos")
        ge = QVBoxLayout(gb_ev)
        evFilterRow = QHBoxLayout()
        evFilterRow.addWidget(QLabel("Filtrar tipo:"))
        self.cb_event_kind = QComboBox()
        self.cb_event_kind.addItems(['kick', 'snare', 'hat',
                                     'onsets_all', 'onsets_percussive',
                                     'bass', 'mid', 'high_mid',
                                     'presence', 'brilliance'])
        self.cb_event_kind.currentTextChanged.connect(self._refresh_events_table)
        evFilterRow.addWidget(self.cb_event_kind, 1)
        ge.addLayout(evFilterRow)
        self.event_table = EventTable()
        ge.addWidget(self.event_table, 1)
        rightL.addWidget(gb_ev, 1)

        # Acciones
        gb_actions = QGroupBox("Acciones")
        ga = QHBoxLayout(gb_actions)
        self.btn_save = QPushButton("💾 Guardar curación")
        self.btn_apply = QPushButton("🔄 Aplicar a Timeline (markers)")
        self.btn_seed_cue = QPushButton("➕ Cue seed en playhead")
        self.tog_snap = QCheckBox("📌 Snap a beats")
        self.tog_snap.setToolTip("Al editar secciones, alinear a beats/downbeats más cercanos")
        ga.addWidget(self.btn_save)
        ga.addWidget(self.btn_apply)
        ga.addWidget(self.btn_seed_cue)
        ga.addWidget(self.tog_snap)
        rightL.addWidget(gb_actions)

        splitter.addWidget(right)
        splitter.setSizes([900, 600])

        # --- Cargar datos iniciales ---
        self._load_canvas()
        self._refresh_sections_table()
        self._refresh_events_table()

        # --- Conexiones ---
        self.canvas.time_clicked.connect(self._on_canvas_click)
        self.canvas.section_dbl_clicked.connect(self._on_section_dbl)
        self.canvas.context_at.connect(self._on_canvas_context)
        self.section_table.section_edited.connect(self._on_section_edited)
        self.event_table.event_disable_requested.connect(self._on_event_disable)
        self.event_table.event_delete_manual_requested.connect(self._on_event_delete_manual)
        self.btn_save.clicked.connect(self._save_curation)
        self.btn_apply.clicked.connect(self._apply_to_timeline)
        self.btn_seed_cue.clicked.connect(self._add_cue_seed_at_playhead)

        self._current_playhead = 0.0

        # Atajos locales (solo activos cuando este panel tiene foco)
        sc_space = QShortcut(QKeySequence(Qt.Key_Space), self)
        sc_space.setContext(Qt.WidgetWithChildrenShortcut)
        sc_space.activated.connect(self._on_play_toggle)
        sc_zoom_in = QShortcut(QKeySequence("Ctrl++"), self)
        sc_zoom_in.setContext(Qt.WidgetWithChildrenShortcut)
        sc_zoom_in.activated.connect(lambda: self._apply_zoom_step(1.5))
        sc_zoom_in2 = QShortcut(QKeySequence("Ctrl+="), self)
        sc_zoom_in2.setContext(Qt.WidgetWithChildrenShortcut)
        sc_zoom_in2.activated.connect(lambda: self._apply_zoom_step(1.5))
        sc_zoom_out = QShortcut(QKeySequence("Ctrl+-"), self)
        sc_zoom_out.setContext(Qt.WidgetWithChildrenShortcut)
        sc_zoom_out.activated.connect(lambda: self._apply_zoom_step(1/1.5))
        sc_zoom_fit = QShortcut(QKeySequence("Ctrl+0"), self)
        sc_zoom_fit.setContext(Qt.WidgetWithChildrenShortcut)
        sc_zoom_fit.activated.connect(self._zoom_fit)

    # ── Public API ────────────────────────────────────────────
    def set_playhead(self, t_sec: float, is_playing: bool = False):
        self._set_playhead_calls = getattr(self, '_set_playhead_calls', 0) + 1
        self._last_set_playhead_t = float(t_sec)
        self._current_playhead = float(t_sec)
        self.canvas.set_playhead(t_sec)
        section = self.analysis.section_at(t_sec)
        if section:
            lbl = section.name or section.label
            self.info_lbl.setText(f"t={t_sec:.2f}s  ·  sección {section.idx} «{lbl}»"
                                  + (f" [{section.type}]" if section.type else ""))
        else:
            self.info_lbl.setText(f"t={t_sec:.2f}s")
        # Auto-scroll si el playhead se sale del viewport visible
        if is_playing and self.canvas.duration_s > 0:
            self._auto_scroll_to_playhead()
        # Mantener botón Play sincronizado con el estado real
        self.btn_play.setText("⏸" if is_playing else "▶")

    def _auto_scroll_to_playhead(self):
        """Si el playhead sale por el borde, scroll para que vuelva al
        25-75% del viewport visible. No interfiere si el usuario hace
        scroll manualmente mientras está parado."""
        sb = self.scroll.horizontalScrollBar()
        viewport_w = self.scroll.viewport().width()
        x = self.canvas.time_to_x(self._current_playhead)
        left = sb.value()
        right = left + viewport_w
        margin = viewport_w * 0.25
        if x < left + margin or x > right - margin:
            # Centrar el playhead en el viewport
            new_left = int(x - viewport_w * 0.4)
            new_left = max(0, min(new_left, sb.maximum()))
            sb.setValue(new_left)

    def refresh_all(self):
        """Re-carga overlays + tablas desde el servicio. Llamar cuando algo
        externo (MCP) haya tocado la curación."""
        self._load_canvas()
        self._refresh_sections_table()
        self._refresh_events_table()

    # ── Internals ─────────────────────────────────────────────
    def _load_canvas(self):
        svc = self.analysis
        summary = svc.summary
        dur = float(summary.get('duration_s') or 1.0)
        self.canvas.set_waveform(self._waveform_peaks, dur)
        sections = svc.list_sections()
        beats = svc.list_beats()
        downbeats = svc.list_downbeats()
        kicks = [e.time_sec for e in svc.list_events('kick')]
        snares = [e.time_sec for e in svc.list_events('snare')]
        hats = [e.time_sec for e in svc.list_events('hat')]
        manuals = list(svc.curation.manual_events)
        disabled = list(svc.curation.disabled_events)
        cue_seeds = list(svc.curation.cue_seeds)
        # Load energy curve (flux = spectral energy)
        # If available from features_range, use it. Otherwise empty.
        try:
            energy_data = svc.features_range(0, dur, downsample_to=1200, names=[])
            if energy_data and isinstance(energy_data, dict) and 'features' in energy_data:
                features = energy_data['features']
                if features and len(features) > 0 and isinstance(features[0], dict):
                    # Extract first feature column as energy proxy
                    flux_list = [f.get('flux', 0.0) for f in features]
                    flux = np.array(flux_list, dtype=np.float32)
                    # Normalize to 0-1
                    flux_max = np.max(flux) if len(flux) > 0 else 1.0
                    if flux_max > 0:
                        flux = flux / flux_max
                    self.canvas.set_energy(flux)
                else:
                    self.canvas.set_energy(np.zeros(1, dtype=np.float32))
            else:
                self.canvas.set_energy(np.zeros(1, dtype=np.float32))
        except Exception as e:
            # Energy visualization is optional; continue if unavailable
            self.canvas.set_energy(np.zeros(1, dtype=np.float32))
        self.canvas.sections = sections
        self.canvas.beats = beats
        self.canvas.downbeats = downbeats
        self.canvas.kicks = kicks
        self.canvas.snares = snares
        self.canvas.hats = hats
        self.canvas.manual_events = manuals
        self.canvas.disabled_events = disabled
        self.canvas.cue_seeds = cue_seeds
        self.canvas.invalidate_bg_cache()

    def _refresh_sections_table(self):
        self.section_table.load_sections(self.analysis.list_sections())

    def _refresh_events_table(self):
        kind = self.cb_event_kind.currentText() or 'kick'
        # Mostrar TODOS los eventos del kind (no filtramos por rango aquí;
        # son 30-100 típicamente).
        evs = self.analysis.list_events(kind)
        # Añadir las marcas disabled como filas también
        cur = self.analysis.curation
        disabled_evs = [Event(time_sec=t, kind=k, source='disabled')
                        for (t, k, tol) in cur.disabled_events if k == kind]
        evs = list(evs) + disabled_evs
        evs.sort(key=lambda e: e.time_sec)
        self.event_table.load_events(evs)

    # ── Transport (play/pause/stop) ───────────────────────────
    def _on_play_toggle(self):
        # El estado real lo lleva el audio del timeline; emite el toggle.
        tl = getattr(self, '_timeline_editor', None)
        if tl is not None and hasattr(tl, 'audio'):
            if tl.audio.playing:
                self.pause_requested.emit()
            else:
                self.play_requested.emit()
        else:
            # Sin timeline editor, solo emite y que el dual_app decida
            self.play_requested.emit()

    def _on_stop(self):
        self.stop_requested.emit()

    # ── Zoom ──────────────────────────────────────────────────
    def _apply_zoom_step(self, factor: float):
        # Centrar el zoom en el viewport visible
        sb = self.scroll.horizontalScrollBar()
        vp_w = self.scroll.viewport().width()
        center_canvas_x = sb.value() + vp_w / 2.0
        self.canvas.set_zoom(self.canvas.zoom_factor * factor,
                             anchor_x=center_canvas_x)

    def _zoom_fit(self):
        # Zoom 1.0 = todo el audio cabe en BASE_WIDTH_PX (ajustar al viewport
        # actual, no al BASE).
        vp_w = self.scroll.viewport().width()
        target_zoom = max(WaveformCanvas.MIN_ZOOM,
                          vp_w / WaveformCanvas.BASE_WIDTH_PX)
        self.canvas.set_zoom(target_zoom)
        self.scroll.horizontalScrollBar().setValue(0)

    def _on_zoom_changed(self, z: float):
        # Tras un set_zoom con ancla, reposicionar el scrollbar para que el
        # ancla quede donde estaba (visualmente fijo bajo el cursor).
        anchor_new_x = getattr(self.canvas, '_anchor_new_x', None)
        if anchor_new_x is not None:
            sb = self.scroll.horizontalScrollBar()
            vp_w = self.scroll.viewport().width()
            # Tratamos de mantener el cursor en su posición relativa anterior
            # (cuando set_zoom guardó _anchor_new_x).
            # Centramos por defecto, simple:
            new_left = int(anchor_new_x - vp_w / 2.0)
            sb.setValue(max(0, min(new_left, sb.maximum())))
            self.canvas._anchor_new_x = None
        self.zoom_lbl.setText(f"{z:.1f}x")

    def _on_toggle(self):
        self.canvas.show_beats = self.tog_beats.isChecked()
        self.canvas.show_downbeats = self.tog_downbeats.isChecked()
        self.canvas.show_kicks = self.tog_kicks.isChecked()
        self.canvas.show_snares = self.tog_snares.isChecked()
        self.canvas.show_hats = self.tog_hats.isChecked()
        self.canvas.show_sections = self.tog_sections.isChecked()
        self.canvas.show_manual = self.tog_manual.isChecked()
        self.canvas.show_disabled = self.tog_disabled.isChecked()
        self.canvas.invalidate_bg_cache()

    def _on_canvas_click(self, t: float):
        # Seek al timeline
        self.seek_requested.emit(t)

    def _on_section_dbl(self, idx: int):
        # Buscar la fila en la tabla y poner foco
        for row in range(self.section_table.rowCount()):
            item = self.section_table.item(row, 0)
            if item and int(item.text()) == idx:
                self.section_table.selectRow(row)
                self.section_table.editItem(self.section_table.item(row, 1))
                return

    def _on_canvas_context(self, t: float, global_pos):
        m = QMenu(self)
        a_kick = m.addAction(f"+ Kick manual @ {t:.3f}s")
        a_snare = m.addAction(f"+ Snare manual @ {t:.3f}s")
        a_cue = m.addAction(f"+ Cue seed @ {t:.3f}s")
        m.addSeparator()
        a_seek = m.addAction("⏵ Seek aquí")
        chosen = m.exec_(global_pos)
        if chosen == a_kick:
            self._add_manual_event(t, 'kick')
        elif chosen == a_snare:
            self._add_manual_event(t, 'snare')
        elif chosen == a_cue:
            name, ok = QInputDialog.getText(self, "Cue seed",
                                            f"Nombre del cue en {t:.2f}s:")
            if ok and name:
                self.analysis.curation.add_cue_seed(t, name)
                self._save_curation(silent=True)
        elif chosen == a_seek:
            self.seek_requested.emit(t)

    def _snap_to_beats(self, t_sec: float) -> float:
        """Snap time to nearest beat/downbeat. Returns snapped time."""
        downbeats = self.canvas.downbeats
        beats = self.canvas.beats
        if not downbeats and not beats:
            return t_sec
        # Prefer snapping to downbeats first
        all_grid = sorted(set(list(downbeats) + list(beats)))
        if not all_grid:
            return t_sec
        # Find closest grid point
        closest = min(all_grid, key=lambda b: abs(b - t_sec))
        return float(closest)

    def _on_section_edited(self, idx: int, name: str, type_: str):
        self.analysis.curation.set_section_label(idx, name=name, type=type_)
        self._save_curation(silent=True)

    def _on_event_disable(self, t: float, kind: str):
        self.analysis.curation.disable_event(t, kind, tolerance_ms=20)
        self._save_curation(silent=True)

    def _on_event_delete_manual(self, t: float, kind: str):
        cur = self.analysis.curation
        cur.manual_events = [e for e in cur.manual_events
                             if not (e.kind == kind and abs(e.time_sec - t) < 1e-3)]
        cur._dirty = True
        self._save_curation(silent=True)

    def _add_manual_event(self, t: float, kind: str):
        name, ok = QInputDialog.getText(self, f"Manual {kind}",
                                        f"Nombre (opcional) para {kind} @ {t:.2f}s:")
        if not ok:
            return
        self.analysis.curation.add_manual_event(t, kind, name=name or '')
        self._save_curation(silent=True)

    def _add_cue_seed_at_playhead(self):
        t = self._current_playhead
        name, ok = QInputDialog.getText(self, "Cue seed",
                                        f"Nombre del cue en {t:.2f}s:")
        if ok and name:
            self.analysis.curation.add_cue_seed(t, name)
            self._save_curation(silent=True)

    def _save_curation(self, silent: bool = False):
        try:
            self.analysis.curation.save()
        except Exception as e:
            QMessageBox.warning(self, "Curación",
                                f"Error guardando: {e}")
            return
        self.refresh_all()
        self.curation_changed.emit()
        if not silent:
            QMessageBox.information(self, "Curación",
                                    f"Guardado en {self.analysis.curation.path}")

    def _apply_to_timeline(self):
        """Convierte la curación en markers + cue points del timeline.

        Esto requiere acceso al timeline_editor, que se inyecta vía atributo
        `_timeline_editor` (puesto por dual_app al crear el panel).
        """
        tl = getattr(self, '_timeline_editor', None)
        if tl is None:
            QMessageBox.warning(self, "Aplicar", "Timeline no disponible.")
            return

        # Section labels → time markers del timeline_editor
        # (los time_markers viven en tl.tl_view, no en tl.timeline)
        view = getattr(tl, 'tl_view', None)
        applied_sections = 0
        if view is not None:
            for s in self.analysis.list_sections():
                if not s.name and not s.type:
                    continue
                label = s.name or s.label
                if s.type:
                    label += f" [{s.type}]"
                t_ms = int(s.start * 1000)
                # Eliminar markers viejos cerca de ese tiempo
                view.time_markers = [m for m in view.time_markers
                                     if abs(m.get('time_ms', 0) - t_ms) > 50]
                view.time_markers.append({
                    'time_ms': t_ms,
                    'name': label,
                    'color': '#ff77dd',
                })
                applied_sections += 1

        # Cue seeds → cue_points si hay slot libre
        applied_cues = 0
        for seed in self.analysis.curation.cue_seeds:
            for cp in tl.timeline.cue_points:
                if not cp.is_set():
                    cp.time_ms = int(seed['time_sec'] * 1000)
                    cp.name = seed.get('name', '')
                    applied_cues += 1
                    break

        # Refrescar UI
        if hasattr(tl, 'tl_view'):
            tl.tl_view._rebuild_scene()
        if hasattr(tl, '_refresh_cue_buttons'):
            tl._refresh_cue_buttons()

        QMessageBox.information(self, "Aplicar",
            f"Aplicado: {applied_sections} markers, {applied_cues} cue points.")
