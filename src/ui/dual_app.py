"""
DUAL APP — Timeline Editor + Feedback en UNA ventana con dos PESTAÑAS.

QMainWindow principal con QTabWidget central:
  • Tab "🎨 Timeline"  -> editor de clips (timeline_editor.TimelineEditorWindow)
  • Tab "📊 Feedback" -> app de feedback + control real (FeedbackApp)

Solo se ve una pestaña a la vez. Esto elimina los problemas de:
  - Dos ShowEngines mandando Art-Net a las mismas IPs en paralelo.
  - Dos pygame.mixer.init() simultáneos.
  - Conflictos de teclado entre ventanas.

Lanzar:
    python dual_app.py
"""
import sys
import os
import traceback
from datetime import datetime
from pathlib import Path

# Windows console = cp1252 por defecto. Forzar UTF-8 evita crashes al
# imprimir emojis o flechas en cualquier punto de la app (Qt logs, etc).
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# Setup MINIMAL de sys.path ANTES de importar src._setup_paths
# (necesario porque src._setup_paths es lo que configura sys.path correctamente)
_root = Path(__file__).resolve().parent.parent.parent  # src/ui/ → show-designer/
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Setup centralizado de sys.path (única fuente de verdad)
from src._setup_paths import *

import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QToolBar, QPushButton, QSizePolicy, QFrame,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QFont, QPainter, QPen, QBrush, QPainterPath


NUM_BARS = 10
LEDS = 93


def _wrap_as_widget(main_win: QMainWindow) -> QWidget:
    """
    Convierte un QMainWindow en widget embebido extrayendo sus partes.

    QMainWindow no se deja embeber con setWindowFlags(Qt.Widget) — Qt sigue
    queriendo abrirlo como top-level. Solución: extraemos manualmente sus
    tres componentes (toolbar, central widget, statusbar) y los reapilamos
    verticalmente en un QWidget normal.
    """
    main_win.hide()
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    # 1) Toolbars (puede haber varias) -> arriba
    for tb in main_win.findChildren(QToolBar):
        if tb.parentWidget() is main_win:
            tb.setParent(container)
            layout.addWidget(tb)

    # 2) Central widget -> centro con stretch
    central = main_win.centralWidget()
    if central is not None:
        # takeCentralWidget desconecta el widget del QMainWindow
        central = main_win.takeCentralWidget()
        layout.addWidget(central, 1)

    # 3) StatusBar -> abajo
    sb = main_win.statusBar()
    if sb is not None:
        sb.setParent(container)
        layout.addWidget(sb)

    # Mantenemos una referencia al QMainWindow original para que sus signals
    # y atributos sigan vivos (TimelineEditorWindow tiene mucha lógica interna
    # ligada a self).
    container._embedded_main = main_win

    return container

# Imports de las dos apps
from src.ui.timeline_editor import TimelineEditorWindow
from src.ui.feedback_app_with_barras import FeedbackApp
# MCP bridge (Fase 1) — expone JSON-RPC en ws://127.0.0.1:9876
try:
    from src.mcp.mcp_bridge import MCPBridge
    HAS_MCP_BRIDGE = True
except Exception as e:
    print(f"[!] mcp_bridge no disponible: {e}")
    HAS_MCP_BRIDGE = False
# Viewer 3D (Fase 2) — sirve HTTP en :8080 + WebSocket en :9877
try:
    from src.viewer3d.viewer3d_server import Viewer3DServer
    HAS_VIEWER3D = True
except Exception as e:
    print(f"[!] viewer3d_server no disponible: {e}")
    HAS_VIEWER3D = False


from src._paths import PROJECT_DIR, VIEWER3D_DIR


# ─── Design System tokens (design handoff 2026-06-01) ──────────────────────
#  Superficies
DS_BG0     = "#0d0f12"
DS_BG1     = "#15181d"
DS_BG2     = "#1d2127"
DS_BG3     = "#272c34"
DS_INSET   = "#0a0c0f"
# Líneas
DS_LINE    = "#363c45"
DS_LINESOFT = "#2b3038"
DS_LINEST  = "#454c57"
# Texto
DS_TXT     = "#f3f4f6"
DS_TXT2    = "#aab1bc"
DS_TXT3    = "#7d838f"
DS_TXT4    = "#5a606b"
# Acentos
DS_ACC     = "#1fe39a"   # verde LED primario
DS_ACC2    = "#a779f0"   # violeta selección
DS_WARN    = "#e3c14f"
DS_BAD     = "#f0654b"

GLOBAL_QSS = """
QWidget {
    background: #0d0f12;
    color: #f3f4f6;
    font-family: "Segoe UI", "Helvetica Neue", system-ui, sans-serif;
    font-size: 12px;
}
QMainWindow, QDialog { background: #0d0f12; }
/* ── Scrollbars ── */
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #272c34; border-radius: 5px; min-height: 20px; margin: 2px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 0;
}
QScrollBar::handle:horizontal {
    background: #272c34; border-radius: 5px; min-width: 20px; margin: 2px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::corner { background: transparent; }
/* ── Toolbar ── */
QToolBar {
    background: #1d2127;
    border-bottom: 1px solid #363c45;
    spacing: 6px;
    padding: 3px 8px;
}
QToolBar::separator { background: #363c45; width: 1px; margin: 4px 3px; }
/* ── StatusBar ── */
QStatusBar {
    background: #15181d;
    border-top: 1px solid #363c45;
    color: #7d838f;
    font-size: 11px;
}
/* ── Buttons ── */
QPushButton {
    background: #1d2127;
    color: #f3f4f6;
    border: 1px solid #363c45;
    border-radius: 8px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton:hover { background: #272c34; border-color: #454c57; }
QPushButton:pressed { background: #0d0f12; }
QPushButton:checked {
    background: rgba(31,227,154,0.16);
    color: #1fe39a;
    border-color: rgba(31,227,154,0.40);
}
QPushButton:disabled { color: #5a606b; border-color: #2b3038; }
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 3px 6px;
    color: #aab1bc;
}
QToolButton:hover { background: #272c34; color: #f3f4f6; }
QToolButton:checked {
    background: rgba(31,227,154,0.16);
    color: #1fe39a;
    border-color: rgba(31,227,154,0.40);
}
/* ── Combo ── */
QComboBox {
    background: #1d2127;
    color: #f3f4f6;
    border: 1px solid #363c45;
    border-radius: 8px;
    padding: 4px 8px;
}
QComboBox:hover { border-color: #454c57; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: #1d2127;
    border: 1px solid #363c45;
    selection-background-color: rgba(31,227,154,0.16);
    selection-color: #1fe39a;
    outline: none;
}
/* ── Inputs ── */
QLineEdit, QSpinBox, QDoubleSpinBox {
    background: #0a0c0f;
    color: #f3f4f6;
    border: 1px solid #2b3038;
    border-radius: 5px;
    padding: 4px 8px;
    selection-background-color: rgba(31,227,154,0.25);
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: rgba(31,227,154,0.50);
}
QSpinBox::up-button, QSpinBox::down-button { width: 0; }
/* ── Label ── */
QLabel { background: transparent; color: #f3f4f6; }
/* ── GroupBox ── */
QGroupBox {
    border: 1px solid #363c45;
    border-radius: 8px;
    margin-top: 8px;
    font-weight: 700;
    color: #aab1bc;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
/* ── Splitter ── */
QSplitter::handle { background: #363c45; }
QSplitter::handle:hover { background: #454c57; }
/* ── Tables ── */
QTableWidget {
    background: #0d0f12;
    gridline-color: #2b3038;
    alternate-background-color: #15181d;
    outline: none;
}
QTableWidget::item { padding: 4px 8px; color: #aab1bc; }
QTableWidget::item:selected {
    background: rgba(31,227,154,0.16);
    color: #1fe39a;
}
QHeaderView::section {
    background: #1d2127;
    color: #5a606b;
    font-size: 10px;
    padding: 5px 8px;
    border: none;
    border-bottom: 1px solid #363c45;
    font-weight: 700;
}
/* ── Slider ── */
QSlider::groove:horizontal {
    background: #272c34;
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #1fe39a;
    width: 14px; height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}
QSlider::sub-page:horizontal { background: #1fe39a; border-radius: 2px; }
/* ── Checkbox ── */
QCheckBox { color: #aab1bc; spacing: 6px; }
QCheckBox::indicator {
    width: 15px; height: 15px;
    border: 1.5px solid #454c57;
    border-radius: 4px;
    background: #0a0c0f;
}
QCheckBox::indicator:checked { background: #1fe39a; border-color: #1fe39a; }
/* ── Tabs ── */
QTabWidget::pane {
    border: none;
    background: #0d0f12;
}
QTabBar {
    background: #15181d;
}
QTabBar::tab {
    background: #15181d;
    color: #7d838f;
    padding: 10px 20px;
    font-size: 12px;
    font-weight: 600;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
}
QTabBar::tab:selected {
    color: #f3f4f6;
    background: #15181d;
    border-bottom: 2px solid #1fe39a;
}
QTabBar::tab:hover:!selected { color: #aab1bc; background: #1d2127; }
/* ── Menus ── */
QMenu {
    background: #15181d;
    border: 1px solid #363c45;
    border-radius: 8px;
    padding: 4px 0;
}
QMenu::item { padding: 6px 24px; color: #aab1bc; }
QMenu::item:selected { background: rgba(31,227,154,0.12); color: #f3f4f6; }
QMenu::separator { height: 1px; background: #363c45; margin: 4px 8px; }
/* ── Tooltips ── */
QToolTip {
    background: #1d2127;
    color: #f3f4f6;
    border: 1px solid #363c45;
    border-radius: 5px;
    padding: 4px 8px;
}
/* ── List ── */
QListWidget {
    background: #0a0c0f;
    border: 1px solid #2b3038;
    border-radius: 5px;
    outline: none;
}
QListWidget::item { padding: 4px 8px; color: #aab1bc; }
QListWidget::item:selected {
    background: rgba(31,227,154,0.16);
    color: #1fe39a;
}
QListWidget::item:hover { background: #1d2127; }
"""


def apply_design_system(app: QApplication):
    """Aplica el design system del handoff 2026-06-01 a toda la app."""
    app.setStyle('Fusion')
    # Palette base para que Qt no interfiera con el QSS
    pal = app.palette()
    pal.setColor(pal.Window,          QColor(0x0d, 0x0f, 0x12))
    pal.setColor(pal.WindowText,      QColor(0xf3, 0xf4, 0xf6))
    pal.setColor(pal.Base,            QColor(0x0a, 0x0c, 0x0f))
    pal.setColor(pal.AlternateBase,   QColor(0x15, 0x18, 0x1d))
    pal.setColor(pal.Text,            QColor(0xf3, 0xf4, 0xf6))
    pal.setColor(pal.Button,          QColor(0x1d, 0x21, 0x27))
    pal.setColor(pal.ButtonText,      QColor(0xf3, 0xf4, 0xf6))
    pal.setColor(pal.Highlight,       QColor(0x1f, 0xe3, 0x9a))
    pal.setColor(pal.HighlightedText, QColor(0x0d, 0x0f, 0x12))
    pal.setColor(pal.Mid,             QColor(0x27, 0x2c, 0x34))
    pal.setColor(pal.Dark,            QColor(0x15, 0x18, 0x1d))
    pal.setColor(pal.Shadow,          QColor(0x00, 0x00, 0x00))
    app.setPalette(pal)
    app.setStyleSheet(GLOBAL_QSS)


# ─── ScrubBar: barra de progreso global con click para seek ────────────────
class ScrubBar(QWidget):
    """Barra de transporte en la parte inferior: tiempo, scrubber y sección.

    Se actualiza cada tick desde TabbedDualApp._link_renders (shared_tick).
    """
    seek_requested = pyqtSignal(float)  # segundos

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setObjectName("ScrubBar")
        self._t    = 0.0
        self._dur  = 1.0
        self._sec  = ""
        self._bar  = 1
        self._beat = 1
        self._playing = False
        # Colores del design system
        self._c_bg      = QColor(0x15, 0x18, 0x1d)
        self._c_border  = QColor(0x36, 0x3c, 0x45)
        self._c_track   = QColor(0x0a, 0x0c, 0x0f)
        self._c_fill    = QColor(0x1f, 0xe3, 0x9a, 45)
        self._c_head    = QColor(0x1f, 0xe3, 0x9a)
        self._c_txt     = QColor(0xf3, 0xf4, 0xf6)
        self._c_txt3    = QColor(0x7d, 0x83, 0x8f)
        self._c_acc     = QColor(0x1f, 0xe3, 0x9a)
        self.setStyleSheet("ScrubBar { background: #15181d; "
                           "border-top: 1px solid #363c45; }")
        self._font_mono = QFont("Consolas", 11, QFont.Bold)
        self._font_mono.setStyleHint(QFont.Monospace)
        self._font_small = QFont("Segoe UI", 9)

    def update_state(self, t: float, dur: float,
                     sec: str = "", bar: int = 1, beat: int = 1,
                     playing: bool = False):
        self._t  = max(0.0, t)
        self._dur = max(0.001, dur)
        self._sec = sec
        self._bar = bar
        self._beat = beat
        self._playing = playing
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            scrub_x0, scrub_w = self._scrub_rect()
            pct = (ev.x() - scrub_x0) / max(1, scrub_w)
            pct = max(0.0, min(1.0, pct))
            self.seek_requested.emit(pct * self._dur)

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.LeftButton:
            scrub_x0, scrub_w = self._scrub_rect()
            pct = (ev.x() - scrub_x0) / max(1, scrub_w)
            pct = max(0.0, min(1.0, pct))
            self.seek_requested.emit(pct * self._dur)

    def _scrub_rect(self):
        """Retorna (x0, width) del área del scrubber."""
        pad_l = 130  # ancho reservado para reloj
        pad_r = 160  # ancho reservado para meta
        return pad_l, max(1, self.width() - pad_l - pad_r)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Fondo
        p.fillRect(0, 0, w, h, self._c_bg)
        # Borde superior
        p.setPen(QPen(self._c_border, 1))
        p.drawLine(0, 0, w, 0)

        # ── Reloj ──────────────────────────────────────────────────
        t = self._t
        m_cur, s_cur = int(t) // 60, t % 60
        dur = self._dur
        m_dur, s_dur = int(dur) // 60, dur % 60
        time_str = f"{m_cur}:{s_cur:04.1f}"
        dur_str  = f"/ {m_dur}:{s_dur:04.1f}"

        p.setFont(self._font_mono)
        p.setPen(self._c_txt)
        fm = p.fontMetrics()
        p.drawText(12, (h + fm.ascent() - fm.descent()) // 2 - 5, time_str)

        p.setFont(self._font_small)
        p.setPen(self._c_txt3)
        fm2 = p.fontMetrics()
        p.drawText(12 + 84, (h + fm2.ascent() - fm2.descent()) // 2 - 3, dur_str)

        # ── Scrubber ───────────────────────────────────────────────
        sx0, sw = self._scrub_rect()
        sy = 13; sh = h - 26
        r = 4  # border-radius

        # Track
        path_track = QPainterPath()
        path_track.addRoundedRect(sx0, sy, sw, sh, r, r)
        p.fillPath(path_track, QBrush(self._c_track))
        p.setPen(QPen(self._c_border, 1))
        p.drawPath(path_track)

        # Fill hasta playhead
        pct = self._t / self._dur
        fill_w = int(pct * sw)
        if fill_w > 0:
            path_fill = QPainterPath()
            path_fill.addRoundedRect(sx0, sy, fill_w, sh, r, r)
            p.fillPath(path_fill, QBrush(self._c_fill))

        # Playhead
        ph_x = sx0 + fill_w
        p.setPen(QPen(self._c_head, 2))
        p.drawLine(ph_x, sy - 2, ph_x, sy + sh + 2)
        # Punto en el playhead
        p.setBrush(QBrush(self._c_head))
        p.setPen(Qt.NoPen)
        p.drawEllipse(ph_x - 4, sy - 5, 8, 8)

        # ── Meta derecha: sección + compás ─────────────────────────
        meta_x = sx0 + sw + 12
        p.setFont(self._font_small)
        fm3 = p.fontMetrics()

        # Sección (texto muted)
        p.setPen(self._c_txt3)
        p.drawText(meta_x, (h + fm3.ascent() - fm3.descent()) // 2 - 8,
                   self._sec or "—")

        # Compás (verde)
        p.setFont(self._font_mono)
        fm4 = p.fontMetrics()
        bar_str = f"{self._bar}.{self._beat}"
        p.setPen(self._c_acc)
        p.drawText(meta_x, (h + fm4.ascent() - fm4.descent()) // 2 + 8,
                   bar_str)

        p.end()


class TabbedDualApp(QMainWindow):
    """Ventana contenedora con tabs para Timeline y Feedback."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Show Designer — Timeline + Feedback")
        self.resize(1500, 900)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        # El QSS global ya estiliza los tabs — sin override aquí

        # ── v1.8 F3: Inicializar ProjectManager antes que cualquier otra cosa ──
        # ensure_migrated() crea projects/el_taser/ si es la primera vez y
        # establece pm.current para que TimelineEditorWindow lo encuentre.
        _project_name = "Show Designer"
        try:
            from src.io.project_manager import get_manager
            _pm = get_manager()
            _proj = _pm.ensure_migrated()
            _project_name = _proj.name if _proj else "Show Designer"
            print(f"[dual] Proyecto activo: {_project_name!r}")
        except Exception as _e:
            print(f"[!] ProjectManager: {_e}")
            _proj = None

        # --- Tab 1: Timeline Editor ---
        print("[dual] Creando Timeline Editor...")
        try:
            self.timeline_win = TimelineEditorWindow()
        except Exception:
            print("[!] Error creando Timeline Editor:")
            traceback.print_exc()
            self.timeline_win = self._error_widget("Timeline Editor falló al cargar")

        self.tabs.addTab(_wrap_as_widget(self.timeline_win), "Timeline")

        # --- Tab 2: Feedback App ---
        print("[dual] Creando Feedback App...")
        try:
            self.feedback_win = FeedbackApp()
        except Exception:
            print("[!] Error creando Feedback App:")
            traceback.print_exc()
            self.feedback_win = self._error_widget("Feedback App falló al cargar")

        self.tabs.addTab(_wrap_as_widget(self.feedback_win), "Live · Feedback")

        # --- Tab 3: Patch Panel ---
        print("[dual] Creando Patch Panel...")
        self.patch_win = None
        try:
            from patch_panel import PatchPanelWindow
            rig = getattr(self.timeline_win, 'fixture_rig', None)
            self.patch_win = PatchPanelWindow(rig=rig)
            # Si patch cambia el rig, lo persistimos y refrescamos viewer3d layout
            self.patch_win.rig_changed.connect(self._on_rig_changed)
            self.tabs.addTab(_wrap_as_widget(self.patch_win), "Patch")
        except Exception:
            print("[!] Error creando Patch Panel:")
            traceback.print_exc()

        # --- Tab 4: Analyzer (Fase C v1.6) ---
        print("[dual] Creando Analyzer Panel...")
        self.analyzer_panel = None
        try:
            from analyzer_panel import AnalyzerPanel
            svc = getattr(self.timeline_win, 'analysis', None)
            # Reusar peaks de la waveform ya cargada por timeline_editor
            wf = getattr(self.timeline_win, 'waveform', None)
            peaks = wf.peaks if (wf is not None and hasattr(wf, 'peaks')) else None
            if svc is not None and svc.has_analysis:
                self.analyzer_panel = AnalyzerPanel(svc, waveform_peaks=peaks)
                # Para que "Aplicar a Timeline" pueda crear markers/cues
                self.analyzer_panel._timeline_editor = self.timeline_win
                # Click en waveform -> seek
                self.analyzer_panel.seek_requested.connect(self._seek_all)
                # Transport
                self.analyzer_panel.play_requested.connect(self._play_all)
                self.analyzer_panel.pause_requested.connect(self._pause_all)
                self.analyzer_panel.stop_requested.connect(self._stop_all)
                # Curación cambiada -> refrescar overlays del timeline
                self.analyzer_panel.curation_changed.connect(
                    self._refresh_timeline_overlays
                )
                self.tabs.addTab(self.analyzer_panel, "Analyzer")
                print(f"[dual] Analyzer panel listo "
                      f"(song={svc.summary.get('song_id', '?')})")
            else:
                print("[!] No hay AnalysisService disponible, tab Analyzer omitida")
        except Exception:
            print("[!] Error creando Analyzer Panel:")
            traceback.print_exc()

        # ── Shell: Topbar + Tabs + ScrubBar ─────────────────────────────────
        self._topbar_artnet_on = False  # estado del LED pulsante
        self._scrub_bar = ScrubBar()
        self._scrub_bar.seek_requested.connect(self._seek_all)

        shell = QWidget()
        shell_vbox = QVBoxLayout(shell)
        shell_vbox.setContentsMargins(0, 0, 0, 0)
        shell_vbox.setSpacing(0)
        shell_vbox.addWidget(self._build_topbar(_project_name))
        shell_vbox.addWidget(self.tabs, 1)
        shell_vbox.addWidget(self._scrub_bar)
        self.setCentralWidget(shell)

        # ── COMPARTIR SHOW ENGINE entre las dos pestañas ──────────────────
        # Sin esto cada tab tiene su propio socket UDP -> dos streams Art-Net
        # compitiendo en las mismas IPs. Lo unificamos: el feedback usa el
        # mismo objeto que el timeline.
        self._share_show_engine()

        # ── UNIFICAR RENDER: ambas pestañas pintan EL MISMO show ─────────
        # El Timeline (con sus clips) es la fuente; el Feedback solo muestra
        # ese mismo frame en su preview. Solo un Art-Net stream activo.
        self._link_renders()

        # Cuando cambias de pestaña, transfiere el tiempo + estado de
        # reproducción de una a otra para "ver el mismo show".
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Atajos rápidos de tab: Ctrl+1/2/3/4 -> Timeline/Feedback/Patch/Analyzer
        # Ctrl+M también enfoca la tab Analyzer (mnemónico "Music").
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        for i in range(self.tabs.count()):
            QShortcut(QKeySequence(f"Ctrl+{i+1}"), self,
                      activated=lambda idx=i: self.tabs.setCurrentIndex(idx))
        # Ctrl+M -> analyzer (último tab si está)
        if self.analyzer_panel is not None:
            idx = self.tabs.indexOf(self.analyzer_panel)
            if idx >= 0:
                QShortcut(QKeySequence("Ctrl+M"), self,
                          activated=lambda i=idx: self.tabs.setCurrentIndex(i))

        # ── MCP Bridge (Fase 1) — servidor JSON-RPC sobre WebSocket ──────
        # Permite que mcp_show_server.py (cliente MCP de Claude) controle
        # la app remotamente: play, pause, seek, list_clips, trigger_cue, etc.
        self.mcp_bridge = None
        if HAS_MCP_BRIDGE:
            try:
                # provider devuelve timeline_win pero le inyectamos referencia
                # a dual para que el bridge pueda llamar _refresh_patch
                def _provider():
                    tw = self.timeline_win
                    if tw is not None:
                        tw._dual_window = self
                    return tw
                self.mcp_bridge = MCPBridge(app_provider=_provider)
                self.mcp_bridge.start()
                print("[dual] MCP bridge arrancado en ws://127.0.0.1:9876")
            except Exception as e:
                print(f"[!] No se pudo arrancar MCP bridge: {e}")

        # ── Viewer 3D (Fase 2) — sirve viewer3d/ y envía frames RGB ──────
        self.viewer3d = None
        if HAS_VIEWER3D:
            try:
                self.viewer3d = Viewer3DServer(num_bars=NUM_BARS, leds_per_bar=LEDS)
                self.viewer3d.start()
                print("[dual] Viewer 3D arrancado: http://localhost:8080/  (WS :9877)")
            except Exception as e:
                print(f"[!] No se pudo arrancar Viewer 3D: {e}")

        print("[dual] Listo. Tab activa idx=0 (Timeline Editor)")

    def _link_renders(self):
        """
        Hace que ambas pestañas muestren EL MISMO show: el Timeline es la
        única fuente del frame RGB, el Feedback solo lo refleja.

        - El _tick del Timeline lee el tiempo de la tab activa (su audio
          o el del feedback).
        - El render del frame se hace UNA vez (en el Timeline).
        - Ese frame se pinta en `timeline.preview` Y en `feedback.show_preview_widget`.
        - Art-Net se envía UNA vez cuando cualquier audio está playing.
        - El _update_ui del Feedback se simplifica: solo actualiza sus
          timelines visuales, NO calcula frame ni envía Art-Net.
        """
        tl = self.timeline_win
        fb = self.feedback_win
        if not (hasattr(tl, 'preview') and hasattr(fb, 'show_preview_widget')):
            print("[!] No se pudo unificar renders: faltan preview widgets")
            return

        def shared_get_time():
            """Tiempo del audio MASTER. Reglas:
              • Si tl.audio está playing → su tiempo.
              • Si fb.audio_player está playing → su tiempo.
              • Si ninguno está playing → tiempo de la tab activa
                (tl para idx=0, idx=2 Patch e idx=3 Analyzer; fb para idx=1).
            Patch y Analyzer NO tienen audio propio: leen del master (tl).
            """
            try:
                if getattr(tl.audio, 'playing', False):
                    return tl.audio.get_time()
                if getattr(fb.audio_player, 'playing', False):
                    return fb.audio_player.get_current_time()
                # Idle: lee del audio que corresponde a la tab activa
                if self.tabs.currentIndex() == 1:
                    return fb.audio_player.get_current_time()
                return tl.audio.get_time()
            except Exception:
                return 0.0

        def any_playing():
            try:
                return bool(getattr(tl.audio, 'playing', False)) or \
                       bool(getattr(fb.audio_player, 'playing', False))
            except Exception:
                return False

        # Conservamos el método original de cómputo del frame
        compute_frame_fn = tl._compute_frame

        # Throttle state: bajamos FPS cuando no hay playback
        self._tick_state = {'last_idle_t': 0.0, 'last_t': -1.0}

        def shared_tick():
            try:
                import time as _tt
                playing_now = any_playing()
                # Si NO está playing, reducir tick a ~10 fps (cada 100ms)
                if not playing_now:
                    now = _tt.monotonic()
                    if now - self._tick_state['last_idle_t'] < 0.1:
                        return
                    self._tick_state['last_idle_t'] = now

                t = shared_get_time()
                # Si el tiempo no cambió (pausado en mismo frame) y no hay playing,
                # saltarse cómputo costoso de frame. Pero SIEMPRE mandar DMX al
                # viewer porque manual_channels pueden cambiar sin mover t
                # (patch panel sliders, set_fixture_channel MCP, etc.).
                if not playing_now and abs(t - self._tick_state['last_t']) < 0.001:
                    if self.viewer3d is not None:
                        try:
                            if tl.show_engine and hasattr(tl.show_engine,
                                                           'get_fixture_dmx_states'):
                                dmx_states = tl.show_engine.get_fixture_dmx_states(
                                    t,
                                    audio_context=None,
                                    rgb_frames_by_bar=None,
                                    timeline=getattr(tl, 'timeline', None),
                                )
                                if dmx_states:
                                    self.viewer3d.broadcast_dmx_state(dmx_states)
                        except Exception:
                            pass
                    return
                self._tick_state['last_t'] = t

                tl.tl_view.set_current_time(t)
                try:
                    bar, beat = tl.tl_view.ms_to_bar_beat(t * 1000)
                    m, s = int(t) // 60, t % 60
                    tl._time_lbl.setText(f"{bar}:{beat}  {m}:{s:04.1f}")
                except Exception:
                    pass

                # 1) Calcular frame UNA sola vez (timeline = fuente)
                frame = compute_frame_fn(t)

                # 1b) Broadcast al viewer 3D (si hay clientes conectados)
                if self.viewer3d is not None:
                    try:
                        self.viewer3d.broadcast_frame(frame)
                    except Exception:
                        pass
                    # v1.7 Fase 4 — estado DMX de movers/strobes
                    try:
                        if tl.show_engine and hasattr(tl.show_engine,
                                                       'get_fixture_dmx_states'):
                            dmx_states = tl.show_engine.get_fixture_dmx_states(
                                t,
                                audio_context=None,
                                rgb_frames_by_bar=None,
                                timeline=getattr(tl, 'timeline', None),
                            )
                            if dmx_states:
                                self.viewer3d.broadcast_dmx_state(dmx_states)
                    except Exception:
                        pass

                # 1c) Sincronizar playhead con la tab Analyzer SIEMPRE.
                # Actualizar el atributo es barato; el repaint del canvas
                # ocurre solo cuando el widget está visible (Qt optimiza).
                if self.analyzer_panel is not None:
                    try:
                        self.analyzer_panel.set_playhead(t, is_playing=playing_now)
                    except Exception:
                        pass

                # 2) Pintar preview del Timeline
                tl.preview.update_frame(frame)
                try:
                    if tl.show_engine and tl.show_engine.state:
                        tl.preview.set_time_info(t, tl.show_engine.state.section_at(t))
                    else:
                        tl.preview.set_time_info(t, 0)
                except Exception:
                    pass

                # 3) Empujar el MISMO frame al preview del Feedback
                # OPT: solo si la tab del Feedback está activa o se está reproduciendo.
                if playing_now or self.tabs.currentIndex() == 1:
                    try:
                        rgb_list = [bytearray(frame[b].flatten().astype(np.uint8))
                                    for b in range(NUM_BARS)]
                        fb.show_preview_widget.set_rgb_frames(rgb_list)
                        fb.show_preview_widget.set_current_time(t)
                        if tl.show_engine and tl.show_engine.state:
                            fb.show_preview_widget.section_id = \
                                tl.show_engine.state.section_at(t)
                    except Exception as e:
                        print(f"[!] cross-paint: {e}")
                else:
                    rgb_list = None

                # 4) Art-Net: enviar cuando CUALQUIER audio está playing
                if playing_now and getattr(tl, 'send_artnet', False) and tl.show_engine:
                    if rgb_list is None:
                        rgb_list = [bytearray(frame[b].flatten().astype(np.uint8))
                                    for b in range(NUM_BARS)]
                    tl.show_engine.send_frame(rgb_list)

                # 5) Actualizar ScrubBar y topbar
                try:
                    dur_s = getattr(tl, 'timeline', None)
                    dur_s = (dur_s.duration_ms / 1000.0) if dur_s else 1.0
                    bar_n, beat_n = 1, 1
                    try:
                        bar_n, beat_n = tl.tl_view.ms_to_bar_beat(t * 1000)
                    except Exception:
                        pass
                    sec_name = ""
                    try:
                        # Intentar obtener nombre de sección desde el AnalysisService
                        analysis = getattr(tl, 'analysis', None)
                        if analysis and analysis.has_analysis:
                            secs = analysis.list_sections(with_curated=True)
                            cur = None
                            for s in reversed(secs):
                                if t >= s.get('start_sec', 0):
                                    cur = s
                                    break
                            if cur:
                                sec_name = cur.get('name', '') or cur.get('type', '')
                    except Exception:
                        pass
                    self._scrub_bar.update_state(
                        t, dur_s, sec_name, bar_n, beat_n, playing_now)
                    self._update_topbar_tick(t, playing_now)
                except Exception:
                    pass
            except Exception as e:
                print(f"[shared_tick] {e}")

        # Reconectar el timer del Timeline a la versión compartida
        try:
            tl.render_timer.timeout.disconnect()
        except Exception:
            pass
        tl.render_timer.timeout.connect(shared_tick)

        # Simplificar el tick del Feedback: solo UI, NO frame ni Art-Net
        def fb_minimal_tick():
            try:
                elapsed = fb.audio_player.get_current_time()
                if hasattr(fb, 'timeline') and fb.timeline:
                    fb.timeline.set_current_time(elapsed)
                if hasattr(fb, 'effects_timeline') and fb.effects_timeline:
                    fb.effects_timeline.set_current_time(elapsed)
                # Auto-pause al final
                if fb.audio_player.playing and elapsed >= 273.3:
                    fb.audio_player.pause()
            except Exception as e:
                print(f"[fb_minimal_tick] {e}")

        try:
            fb.update_timer.timeout.disconnect()
        except Exception:
            pass
        fb.update_timer.timeout.connect(fb_minimal_tick)

        print("[dual] Render unificado: el Timeline pinta ambas pestañas + un único Art-Net")

    def _share_show_engine(self):
        """Hace que feedback use el ShowEngine del timeline. Un único socket Art-Net."""
        try:
            tl = self.timeline_win
            fb = self.feedback_win
            if not (hasattr(tl, 'show_engine') and tl.show_engine):
                return
            if not (hasattr(fb, 'show_engine') and fb.show_engine):
                return
            if fb.show_engine is tl.show_engine:
                return  # ya compartido
            # Cerrar el socket UDP del feedback antes de reemplazar el objeto
            try:
                fb.show_engine.sock.close()
            except Exception:
                pass
            fb.show_engine = tl.show_engine
            if hasattr(fb, 'audio_player') and hasattr(fb.audio_player, 'set_show_engine'):
                fb.audio_player.set_show_engine(tl.show_engine)
            print("[dual] ShowEngine compartido entre ambas pestañas (un solo socket Art-Net)")
        except Exception as e:
            print(f"[!] No se pudo compartir ShowEngine: {e}")

    def _refresh_patch(self):
        """Re-pinta el patch panel tras cambios externos (vía MCP)."""
        if self.patch_win is not None:
            try:
                self.patch_win._rebuild_scene()
                self._sync_rig_to_viewer3d()
            except Exception as e:
                print(f"[!] _refresh_patch: {e}")

    def _refresh_analyzer_overlays(self):
        """Refresca la tab Analyzer tras cambios de curación (vía MCP)."""
        if self.analyzer_panel is not None:
            try:
                self.analyzer_panel.refresh_all()
            except Exception as e:
                print(f"[!] _refresh_analyzer_overlays: {e}")
        # También refresca los overlays del timeline
        self._refresh_timeline_overlays()

    def _refresh_timeline_overlays(self):
        """Recalcula el dict de markers del timeline_editor a partir del
        servicio (incluye nombres curados) y fuerza re-paint."""
        try:
            tl = self.timeline_win
            svc = getattr(tl, 'analysis', None)
            if svc is None:
                return
            tl.markers = {
                'beats':    svc.list_beats(),
                'sections': [s.start for s in svc.list_sections()],
                'kicks':    [e.time_sec for e in svc.list_events('kick')],
            }
            if hasattr(tl, 'tl_view'):
                tl.tl_view.markers = tl.markers
                tl.tl_view._rebuild_scene()
        except Exception as e:
            print(f"[!] _refresh_timeline_overlays: {e}")

    def _seek_all(self, t_sec: float):
        """Mueve el cursor de reproducción a t_sec en TODAS las tabs.

        Lo usa el AnalyzerPanel cuando haces click sobre la waveform.
        """
        try:
            tl = self.timeline_win
            fb = self.feedback_win
            if hasattr(tl, 'audio'):
                tl.audio.seek(float(t_sec))
            if hasattr(fb, 'audio_player'):
                fb.audio_player.seek(float(t_sec))
        except Exception as e:
            print(f"[!] _seek_all: {e}")

    def _play_all(self):
        """Inicia reproducción en el audio activo (timeline = master)."""
        try:
            tl = self.timeline_win
            if hasattr(tl, 'audio'):
                tl.audio.play(tl.audio.get_time())
        except Exception as e:
            print(f"[!] _play_all: {e}")

    def _pause_all(self):
        try:
            tl = self.timeline_win
            if hasattr(tl, 'audio'):
                tl.audio.pause()
        except Exception as e:
            print(f"[!] _pause_all: {e}")

    def _stop_all(self):
        try:
            tl = self.timeline_win
            if hasattr(tl, 'audio'):
                tl.audio.stop()
                tl.audio.seek(0.0)
            fb = self.feedback_win
            if hasattr(fb, 'audio_player'):
                fb.audio_player.seek(0.0)
        except Exception as e:
            print(f"[!] _stop_all: {e}")

    def _on_rig_changed(self):
        """Cuando el patch panel modifica el rig, regenera el layout 3D y persiste."""
        try:
            if self.patch_win is None or self.patch_win.rig is None:
                return
            # Re-exportar rig_layout.json para el viewer 3D
            self._sync_rig_to_viewer3d()
        except Exception as e:
            print(f"[!] _on_rig_changed: {e}")

    def _sync_rig_to_viewer3d(self):
        """Genera viewer3d/rig_layout.json desde el FixtureRig actual."""
        try:
            import json
            from pathlib import Path
            rig = self.patch_win.rig if self.patch_win else None
            if rig is None:
                return
            fixtures_json = []
            for fx in rig.fixtures:
                prof = rig.get_profile(fx.profile_id)
                entry = {
                    "id": fx.fixture_id,
                    "type": prof.kind if prof else "led_strip",
                    "leds": prof.led_count if prof else 93,
                    "position": list(fx.position),
                    "rotation": list(fx.rotation),
                    "length": 1.0,
                }
                # v1.7 Fase 4 — metadata + canales para movers/strobes en JS
                if prof is not None and prof.kind != 'led_strip':
                    entry["channels"] = list(prof.channel_map.keys())
                    md = prof.metadata or {}
                    entry["metadata"] = {
                        "max_pan_deg": float(md.get("max_pan_deg", 540.0)),
                        "max_tilt_deg": float(md.get("max_tilt_deg", 270.0)),
                        "beam_angle_deg": float(md.get(
                            "beam_angle_deg",
                            md.get("beam_angle_min_deg", 22.0))),
                    }
                fixtures_json.append(entry)
            layout = {
                "_comment": "Auto-generated from FixtureRig via patch_panel.",
                "stage": {"width": 12.0, "depth": 6.0,
                          "floor_color": "#1a1a22",
                          "background_color": "#06080c"},
                "fixtures": fixtures_json,
            }
            target = VIEWER3D_DIR / "rig_layout.json"
            with open(target, "w", encoding="utf-8") as f:
                json.dump(layout, f, indent=2)
            # Avisar al browser para que recargue el layout sin refrescar la página
            if self.viewer3d is not None:
                self.viewer3d.broadcast_reload_layout()
        except Exception as e:
            print(f"[!] _sync_rig_to_viewer3d: {e}")

    def _build_topbar(self, project_name: str = "Show Designer") -> QWidget:
        """Construye la topbar de 50px con logo, pill de proyecto y chips."""
        bar = QWidget()
        bar.setFixedHeight(50)
        bar.setObjectName("TopBar")
        bar.setStyleSheet("""
            #TopBar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1d2127, stop:1 #15181d);
                border-bottom: 1px solid #363c45;
            }
        """)
        hbox = QHBoxLayout(bar)
        hbox.setContentsMargins(14, 0, 14, 0)
        hbox.setSpacing(12)

        # ── Logo ──────────────────────────────────────────────────
        logo_mark = QWidget()
        logo_mark.setFixedSize(26, 26)
        logo_mark.setStyleSheet("""
            background: qradialgradient(cx:0.35, cy:0.30, radius:1,
                fx:0.35, fy:0.30,
                stop:0 #1fe39a, stop:1 #0da86b);
            border-radius: 7px;
        """)
        hbox.addWidget(logo_mark)

        logo_lbl = QLabel()
        logo_lbl.setText('<span style="font-weight:800;font-size:14px;'
                         'letter-spacing:2px;color:#f3f4f6;">LUC'
                         '<span style="color:#1fe39a;">ES</span></span>')
        logo_lbl.setStyleSheet("background:transparent;")
        hbox.addWidget(logo_lbl)

        # Separador vertical
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #363c45;")
        hbox.addWidget(sep)

        # ── Pill de proyecto ──────────────────────────────────────
        # BPM desde timeline si disponible
        bpm_str = ""
        try:
            svc = getattr(self.timeline_win, 'analysis', None)
            if svc and svc.has_analysis:
                bpm_val = svc.summary.get('bpm', 0)
                if bpm_val:
                    bpm_str = f" · {bpm_val:.1f} BPM"
        except Exception:
            pass

        pill = QLabel(f'<span style="color:#1fe39a;font-size:8px;">●</span>'
                      f' <b style="color:#f3f4f6;">{project_name}</b>'
                      f'<span style="color:#5a606b;font-family:Consolas;font-size:10px;">'
                      f'{bpm_str}</span>')
        pill.setStyleSheet("""
            QLabel {
                background: #0d0f12;
                border: 1px solid #2b3038;
                border-radius: 999px;
                padding: 4px 12px;
                font-size: 12px;
            }
        """)
        hbox.addWidget(pill)

        # ── Spacer ────────────────────────────────────────────────
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        hbox.addWidget(spacer)

        # ── Chip ART-NET ──────────────────────────────────────────
        self._artnet_chip = QLabel("● ART-NET · 10 univ.")
        self._artnet_chip.setStyleSheet("""
            QLabel {
                background: #0d0f12;
                border: 1px solid #2b3038;
                border-radius: 8px;
                padding: 4px 10px;
                font-family: Consolas;
                font-size: 11px;
                color: #5a606b;
            }
        """)
        hbox.addWidget(self._artnet_chip)

        # ── Chip FPS ─────────────────────────────────────────────
        self._fps_chip = QLabel("0 fps")
        self._fps_chip.setFixedWidth(56)
        self._fps_chip.setAlignment(Qt.AlignCenter)
        self._fps_chip.setStyleSheet("""
            QLabel {
                background: #0d0f12;
                border: 1px solid #2b3038;
                border-radius: 8px;
                padding: 4px 8px;
                font-family: Consolas;
                font-size: 11px;
                color: #5a606b;
            }
        """)
        hbox.addWidget(self._fps_chip)

        # ── Botón Guardar ─────────────────────────────────────────
        self._save_btn = QPushButton("💾")
        self._save_btn.setFixedSize(32, 32)
        self._save_btn.setToolTip("Guardar show (Ctrl+S)")
        self._save_btn.setStyleSheet("""
            QPushButton {
                background: #0d0f12;
                border: 1px solid #2b3038;
                border-radius: 8px;
                font-size: 14px;
                padding: 0;
            }
            QPushButton:hover { background: #272c34; border-color: #454c57; }
        """)
        self._save_btn.clicked.connect(self._on_save_clicked)
        hbox.addWidget(self._save_btn)

        # ── Contador de FPS ──────────────────────────────────────
        self._fps_counter = {'frames': 0, 'last': 0.0}
        import time as _tt
        self._fps_counter['last'] = _tt.monotonic()

        return bar

    def _on_save_clicked(self):
        """Delega el guardado al timeline."""
        try:
            self.timeline_win.save_show()
        except Exception as e:
            print(f"[topbar] save: {e}")

    def _update_topbar_tick(self, t: float, playing: bool):
        """Llamado desde shared_tick para actualizar chips de la topbar."""
        import time as _tt
        try:
            # LED ART-NET
            color = "#1fe39a" if playing else "#5a606b"
            self._artnet_chip.setStyleSheet(f"""
                QLabel {{
                    background: #0d0f12;
                    border: 1px solid #2b3038;
                    border-radius: 8px;
                    padding: 4px 10px;
                    font-family: Consolas;
                    font-size: 11px;
                    color: {color};
                }}
            """)
            # FPS
            fc = self._fps_counter
            fc['frames'] += 1
            now = _tt.monotonic()
            elapsed = now - fc['last']
            if elapsed >= 1.0:
                fps = fc['frames'] / elapsed
                self._fps_chip.setText(f"{fps:.0f} fps")
                fc['frames'] = 0
                fc['last'] = now
        except Exception:
            pass

    def _error_widget(self, msg: str) -> QWidget:
        """Widget de placeholder cuando una tab falla al cargar."""
        w = QWidget()
        lay = QVBoxLayout()
        lbl = QLabel(f"<h2 style='color:#cc5555'>{msg}</h2>"
                     f"<p style='color:#888'>Revisa la consola para el traceback.</p>")
        lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(lbl)
        w.setLayout(lay)
        return w

    def _on_tab_changed(self, idx: int):
        """
        Transfiere tiempo + estado de reproducción entre Timeline (idx=0)
        y Feedback (idx=1). Patch (idx=2) y Analyzer (idx=3) NO tocan el
        audio: comparten el reloj con la tab activa antes del cambio.
        """
        try:
            tl = getattr(self.tabs.widget(0), '_embedded_main', None) or self.timeline_win
            fb = getattr(self.tabs.widget(1), '_embedded_main', None) or self.feedback_win

            # Patch / Analyzer: NO mover el cursor, NO parar reproducción
            if idx >= 2:
                return

            if idx == 1:
                # Saliendo del Timeline, entrando al Feedback
                if hasattr(tl, 'audio') and hasattr(fb, 'audio_player'):
                    t = tl.audio.get_time()
                    was_playing = bool(getattr(tl.audio, 'playing', False))
                    if was_playing:
                        tl.audio.pause()
                    fb.audio_player.seek(t)
                    if was_playing:
                        fb.audio_player.play()
                    print(f"[dual] -> Feedback @ t={t:.2f}s  playing={was_playing}")
            else:
                # Saliendo del Feedback, entrando al Timeline
                if hasattr(fb, 'audio_player') and hasattr(tl, 'audio'):
                    t = fb.audio_player.get_current_time()
                    was_playing = bool(getattr(fb.audio_player, 'playing', False))
                    if was_playing:
                        fb.audio_player.pause()
                    tl.audio.seek(t)
                    if was_playing:
                        tl.audio.play(t)
                    print(f"[dual] -> Timeline @ t={t:.2f}s  playing={was_playing}")
        except Exception as e:
            print(f"[!] Error sincronizando al cambiar de tab: {e}")
            import traceback
            traceback.print_exc()

    def closeEvent(self, event):
        """Cerrar limpia recursos en ambas tabs."""
        try:
            if hasattr(self.timeline_win, 'audio'):
                self.timeline_win.audio.stop()
        except Exception:
            pass
        try:
            if hasattr(self.feedback_win, 'audio_player'):
                self.feedback_win.audio_player.stop()
        except Exception:
            pass
        super().closeEvent(event)


_CRASH_LOG = Path(__file__).parent / "crash.log"


def _crash_write(text):
    """Escribe a crash.log con open/flush/close — sobrevive a stdout redirigido."""
    try:
        with open(_CRASH_LOG, 'a', encoding='utf-8') as f:
            f.write(text + "\n")
            f.flush()
    except Exception:
        pass


def _install_global_excepthook():
    """v1.9 F2/F4/F11 — Excepciones no capturadas en slots Qt no matan la app.

    Sin esto, una excepción en un signal handler de Qt llega a sys.excepthook
    por defecto que en Python 3.11+ termina el proceso. Instalamos uno que
    loguea y deja vivir la app — fail-soft en lugar de fail-hard.

    v1.9 F4: añadido throttling para evitar el caso "Qt re-entrante" en el
    que un slot lanza la MISMA excepción cada frame (ej. error de pintado
    en _rebuild_scene). Sin throttling, el excepthook imprimía miles de
    tracebacks por segundo y la UI se congelaba aunque técnicamente
    siguiera viva. Ahora solo loguea una vez cada 2 segundos por tipo
    de excepción y notifica visualmente al usuario.

    v1.9 F11: además de print, escribe a crash.log via open/flush/close
    (el patrón que sí survice a stdout redirigido a archivo bloqueante).
    Sin throttle para el archivo — queremos el primer traceback siempre.
    """
    import traceback as _tb
    import time as _time

    _last_log_by_key = {}    # key = (exc_type, filename, lineno) → ts
    _THROTTLE_SEC = 2.0

    def _hook(exc_type, exc_value, exc_tb):
        # Permitir Ctrl+C como antes
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        try:
            # Clave de throttling: tipo + última línea del traceback
            tb_last = exc_tb
            while tb_last and tb_last.tb_next:
                tb_last = tb_last.tb_next
            fname = tb_last.tb_frame.f_code.co_filename if tb_last else '?'
            lineno = tb_last.tb_lineno if tb_last else 0
            key = (exc_type, fname, lineno)
            now = _time.monotonic()
            last = _last_log_by_key.get(key, 0.0)

            # Escribir a crash.log siempre (sin throttle) — el archivo
            # sobrevive a stdout bloqueante en modo redirigido.
            lines = _tb.format_exception(exc_type, exc_value, exc_tb)
            msg = (f"[{datetime.now().isoformat(timespec='seconds')}] "
                   f"[unhandled] {exc_type.__name__}: {exc_value}\n"
                   + "".join(lines))
            _crash_write(msg)

            if now - last < _THROTTLE_SEC:
                return    # throttle: misma excepción repetida → silencio en consola
            _last_log_by_key[key] = now

            print("=" * 70)
            print(f"[unhandled] {exc_type.__name__}: {exc_value}")
            _tb.print_tb(exc_tb)
            print("=" * 70)
        except Exception:
            # Si hasta el log falla, delegar al hook original
            sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook


def main():
    _install_global_excepthook()

    # v1.9 F11 — line-buffering para que los prints lleguen aunque el proceso
    # muera antes de vaciar el buffer de bloque (modo redirigido en Windows).
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    _crash_write(f"\n===== ARRANQUE {datetime.now().isoformat(timespec='seconds')} "
                 f"pid={os.getpid()} =====")

    app = QApplication(sys.argv)
    apply_design_system(app)

    win = TabbedDualApp()
    win.show()

    app.aboutToQuit.connect(
        lambda: _crash_write("[aboutToQuit] cierre limpio de Qt")
    )

    print("[dual] Entrando en event loop")
    try:
        return app.exec_()
    except Exception as e:
        _crash_write(f"[exec_ exception] {type(e).__name__}: {e}\n"
                     + traceback.format_exc())
        raise


if __name__ == '__main__':
    sys.exit(main())
