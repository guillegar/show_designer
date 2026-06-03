"""
patch_panel.py — Patch UI para el rig (Fase 6).

Vista 2D top-down del escenario donde se ven las fixtures como items.
Permite arrastrar para reposicionar, añadir/borrar, editar propiedades.

Se integra como tercera pestaña en dual_app:
    [Timeline] [Feedback] [🎯 Patch]

Modelo: usa fixtures.FixtureRig directamente (referencia compartida con
el ShowEngine), así los cambios afectan al routing en tiempo real.
"""
from __future__ import annotations
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QMainWindow, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsEllipseItem,
    QGraphicsLineItem, QGraphicsTextItem, QGraphicsItem,
    QListWidget, QListWidgetItem, QComboBox, QLineEdit, QSpinBox,
    QDoubleSpinBox, QStatusBar, QMessageBox, QToolBar, QAction,
    QInputDialog, QFormLayout, QGroupBox, QScrollArea, QSlider, QSizePolicy,
)
from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import QColor, QBrush, QPen, QFont, QPainter

from src.core.fixtures import (
    FixtureRig, Fixture, FixtureProfile,
    list_available_profiles, load_profile, build_default_wled_rig,
)


# ─────────────────────────────────────────────────────────────────
# Constantes visuales
# ─────────────────────────────────────────────────────────────────
PX_PER_METER = 60        # 1 metro = 60 píxeles
STAGE_BG = QColor(14, 16, 22)
GRID_COLOR_MAJOR = QColor(40, 40, 56)
GRID_COLOR_MINOR = QColor(28, 28, 38)
STAGE_BOUNDS_COLOR = QColor(70, 70, 100)
SELECTED_BORDER = QColor(255, 230, 30)

# Colores por tipo de fixture
FIXTURE_COLORS = {
    'led_strip': QColor(80, 180, 240),
    'moving_head': QColor(230, 120, 60),
    'dimmer': QColor(220, 220, 100),
    'laser': QColor(220, 60, 200),
    'rgb_par': QColor(100, 200, 120),
    'default': QColor(150, 150, 180),
}


# ─────────────────────────────────────────────────────────────────
# FixtureItem — representación gráfica de un Fixture
# ─────────────────────────────────────────────────────────────────
class FixtureItem(QGraphicsRectItem):
    """
    Item arrastrable que representa una Fixture en el plano.
    Su posición en escena corresponde a la posición física X/Z (top-down).
    """
    def __init__(self, fixture: Fixture, kind: str = 'default',
                 num_channels: int = 1):
        # Tamaño según tipo (px)
        if kind == 'led_strip':
            w, h = 12, 36
        elif kind == 'moving_head':
            w, h = 28, 28
        elif kind == 'dimmer':
            w, h = 18, 18
        else:
            w, h = 22, 22
        super().__init__(-w/2, -h/2, w, h)

        self.fixture = fixture
        self.kind = kind
        self.num_channels = num_channels

        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

        color = FIXTURE_COLORS.get(kind, FIXTURE_COLORS['default'])
        self.setBrush(QBrush(color))
        self.setPen(QPen(color.lighter(150), 1.5))
        self.setZValue(10)

        # Etiqueta encima
        label = fixture.label or fixture.fixture_id
        self.label_item = QGraphicsTextItem(label, parent=self)
        self.label_item.setDefaultTextColor(QColor(220, 220, 230))
        self.label_item.setFont(QFont("Segoe UI", 7, QFont.Bold))
        lbr = self.label_item.boundingRect()
        self.label_item.setPos(-lbr.width()/2, -h/2 - lbr.height() - 1)

        # Indicador universe abajo
        univ_text = f"U{fixture.universe}"
        self.univ_item = QGraphicsTextItem(univ_text, parent=self)
        self.univ_item.setDefaultTextColor(QColor(150, 180, 210))
        self.univ_item.setFont(QFont("Consolas", 7))
        ur = self.univ_item.boundingRect()
        self.univ_item.setPos(-ur.width()/2, h/2 + 1)

        # Posición inicial = posición física
        self._set_scene_pos_from_fixture()

    def _set_scene_pos_from_fixture(self):
        """Convierte position (x,y,z metros) → (scene_x, scene_z) px."""
        x, _y, z = self.fixture.position
        # Y=up no afecta a la vista top-down
        self.setPos(x * PX_PER_METER, z * PX_PER_METER)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            # Actualizar fixture.position al arrastrar
            new_pos: QPointF = value
            x_m = new_pos.x() / PX_PER_METER
            z_m = new_pos.y() / PX_PER_METER
            y_m = self.fixture.position[1]
            self.fixture.position = (round(x_m, 3), y_m, round(z_m, 3))
            # Avisar al panel
            if hasattr(self.scene(), 'fixture_moved'):
                self.scene().fixture_moved.emit(self.fixture.fixture_id)
        if change == QGraphicsItem.ItemSelectedChange:
            sel = bool(value)
            color = FIXTURE_COLORS.get(self.kind, FIXTURE_COLORS['default'])
            if sel:
                self.setPen(QPen(SELECTED_BORDER, 2.5))
            else:
                self.setPen(QPen(color.lighter(150), 1.5))
        return super().itemChange(change, value)


# ─────────────────────────────────────────────────────────────────
# PatchScene — QGraphicsScene con grid y signals
# ─────────────────────────────────────────────────────────────────
class PatchScene(QGraphicsScene):
    fixture_moved = pyqtSignal(str)        # fixture_id
    fixture_selected = pyqtSignal(str)     # fixture_id o ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(STAGE_BG))

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        # Grid mayor cada 1 metro, menor cada 0.5 metro
        major = PX_PER_METER
        minor = PX_PER_METER / 2
        left = int(rect.left() / minor) * minor
        right = int(rect.right() / minor + 1) * minor
        top = int(rect.top() / minor) * minor
        bottom = int(rect.bottom() / minor + 1) * minor

        pen_minor = QPen(GRID_COLOR_MINOR, 1, Qt.DotLine)
        pen_major = QPen(GRID_COLOR_MAJOR, 1)
        x = left
        while x <= right:
            painter.setPen(pen_major if abs(x % major) < 0.01 else pen_minor)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += minor
        y = top
        while y <= bottom:
            painter.setPen(pen_major if abs(y % major) < 0.01 else pen_minor)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += minor

        # Ejes X (rojo) y Z (azul) centrales
        painter.setPen(QPen(QColor(200, 80, 80, 140), 1.5))
        painter.drawLine(QPointF(rect.left(), 0), QPointF(rect.right(), 0))
        painter.setPen(QPen(QColor(80, 130, 220, 140), 1.5))
        painter.drawLine(QPointF(0, rect.top()), QPointF(0, rect.bottom()))


# ─────────────────────────────────────────────────────────────────
# ChannelEditorWidget — sliders DMX para fixture no-LED (v1.7 Fase 5)
# ─────────────────────────────────────────────────────────────────

class ChannelEditorWidget(QWidget):
    """Panel con sliders 0-255 para cada canal DMX de un fixture no-LED.

    Se muestra en el panel lateral del PatchPanel cuando se selecciona un
    fixture que NO es led_strip. Los valores se guardan en
    `fixture.manual_channels` (0..1 normalizado) y el ShowEngine los recoge
    en el siguiente tick para broadcast al viewer 3D.
    """

    _SLIDER_STYLE = (
        "QSlider::groove:horizontal{background:#1a1a2a; height:4px; border-radius:2px;} "
        "QSlider::handle:horizontal{background:#5588cc; width:10px; height:10px; "
        "margin:-3px 0; border-radius:5px;} "
        "QSlider::sub-page:horizontal{background:#4477bb; border-radius:2px;}"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fixture = None
        self._sliders: dict = {}     # ch_name → (slider, val_label)
        self._blocked = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(2)

        title = QLabel("📊 Canales DMX")
        title.setStyleSheet("color:#aaddff; font-size:10px; font-weight:bold;")
        outer.addWidget(title)

        # Botón "limpiar overrides"
        btn_clear = QPushButton("⊘ Limpiar overrides")
        btn_clear.setStyleSheet(
            "QPushButton{background:#252540; color:#aaa; border:1px solid #444; "
            "border-radius:2px; padding:2px 6px; font-size:9px;} "
            "QPushButton:hover{background:#353555; color:#eee;}"
        )
        btn_clear.clicked.connect(self._clear_all)
        outer.addWidget(btn_clear)

        # Scroll area con los sliders
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setMaximumHeight(260)
        self._scroll.setStyleSheet(
            "QScrollArea{background:#0c0c18; border:1px solid #2a2a40;} "
            "QScrollBar:vertical{width:8px; background:#0c0c18;} "
            "QScrollBar::handle:vertical{background:#333355; border-radius:4px;}"
        )
        self._inner = QWidget()
        self._inner_lay = QVBoxLayout(self._inner)
        self._inner_lay.setContentsMargins(4, 2, 4, 2)
        self._inner_lay.setSpacing(1)
        self._scroll.setWidget(self._inner)
        outer.addWidget(self._scroll)

    def load_fixture(self, fixture, profile):
        """Carga los sliders para los canales del fixture/profile dados."""
        self._fixture = fixture
        self._sliders.clear()

        # Limpiar inner widget
        while self._inner_lay.count():
            item = self._inner_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if profile is None or not profile.channel_map or profile.kind == 'led_strip':
            self.hide()
            return

        # Canales ordenados por offset (posición DMX)
        channels = sorted(profile.channel_map.items(), key=lambda kv: kv[1])

        manual = getattr(fixture, 'manual_channels', {}) or {}

        self._blocked = True
        for ch_name, offset in channels:
            row = QWidget()
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(4)

            lbl = QLabel(f"{ch_name}")
            lbl.setFixedWidth(80)
            lbl.setStyleSheet("color:#99aabb; font-size:9px;")
            row_lay.addWidget(lbl)

            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 255)
            slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            slider.setFixedHeight(16)
            slider.setStyleSheet(self._SLIDER_STYLE)
            current = int(round(manual.get(ch_name, 0.0) * 255))
            slider.setValue(current)
            row_lay.addWidget(slider)

            val_lbl = QLabel(str(current))
            val_lbl.setFixedWidth(26)
            val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val_lbl.setStyleSheet("color:#ccd; font-size:9px; font-family:Consolas;")
            row_lay.addWidget(val_lbl)

            self._sliders[ch_name] = (slider, val_lbl)

            # Closure captura ch_name
            def _make_handler(ch):
                def _on_change(v):
                    if self._blocked or self._fixture is None:
                        return
                    self._sliders[ch][1].setText(str(v))
                    if not hasattr(self._fixture, 'manual_channels') or \
                            self._fixture.manual_channels is None:
                        self._fixture.manual_channels = {}
                    self._fixture.manual_channels[ch] = v / 255.0
                return _on_change

            slider.valueChanged.connect(_make_handler(ch_name))
            self._inner_lay.addWidget(row)

        self._blocked = False
        self._inner_lay.addStretch()
        self.show()

    def refresh_values(self):
        """Actualiza los sliders con los valores actuales de manual_channels."""
        if self._fixture is None:
            return
        manual = getattr(self._fixture, 'manual_channels', {}) or {}
        self._blocked = True
        for ch_name, (slider, val_lbl) in self._sliders.items():
            v = int(round(manual.get(ch_name, 0.0) * 255))
            slider.setValue(v)
            val_lbl.setText(str(v))
        self._blocked = False

    def _clear_all(self):
        if self._fixture is None:
            return
        if hasattr(self._fixture, 'manual_channels'):
            self._fixture.manual_channels.clear()
        self._blocked = True
        for _slider, val_lbl in self._sliders.values():
            _slider.setValue(0)
            val_lbl.setText("0")
        self._blocked = False


# ─────────────────────────────────────────────────────────────────
# PatchPanelWindow — la pestaña entera
# ─────────────────────────────────────────────────────────────────
class PatchPanelWindow(QMainWindow):
    """Panel de patch — pestaña en dual_app."""

    rig_changed = pyqtSignal()    # se emite tras cualquier modificación

    def __init__(self, rig: Optional[FixtureRig] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Patch")
        self.rig = rig if rig is not None else build_default_wled_rig()

        central = QWidget(); self.setCentralWidget(central)
        lay = QHBoxLayout(central); lay.setSpacing(4); lay.setContentsMargins(4, 4, 4, 4)

        # ── Scene + view ────────────────────────────────────────────
        self.scene = PatchScene()
        self.scene.setSceneRect(-10 * PX_PER_METER, -8 * PX_PER_METER,
                                20 * PX_PER_METER, 16 * PX_PER_METER)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setStyleSheet("border: 1px solid #2a2a40;")
        self.view.setDragMode(QGraphicsView.RubberBandDrag)
        self.scene.fixture_moved.connect(self._on_fixture_moved)
        self.scene.selectionChanged.connect(self._on_selection_changed)

        lay.addWidget(self.view, stretch=1)

        # ── Side panel ──────────────────────────────────────────────
        side = QWidget()
        side.setFixedWidth(260)
        side.setStyleSheet("background: #161623; color: #ccc;")
        side_lay = QVBoxLayout(side); side_lay.setSpacing(6)

        title = QLabel("  PATCH")
        title.setStyleSheet("background:#202032; color:#bbb; font-size:10px; "
                            "font-weight:bold; padding:6px 0; letter-spacing:2px;")
        side_lay.addWidget(title)

        # Lista de fixtures
        side_lay.addWidget(QLabel("Fixtures en el rig:"))
        self.list_w = QListWidget()
        self.list_w.setMaximumHeight(160)
        self.list_w.setStyleSheet(
            "QListWidget{background:#0e0e18; color:#ddd; border:1px solid #2a2a40; font-size:10px;}"
            "QListWidget::item{padding:3px 6px;}"
            "QListWidget::item:selected{background:#2a4a8a;}"
        )
        self.list_w.itemClicked.connect(self._on_list_click)
        side_lay.addWidget(self.list_w)

        # Botones
        btn_row = QHBoxLayout()
        b_add = QPushButton("+ Añadir")
        b_del = QPushButton("🗑 Borrar")
        b_save = QPushButton("💾 Guardar rig")
        for b in (b_add, b_del, b_save):
            b.setStyleSheet("QPushButton{background:#252540; color:#ddd; "
                            "padding:4px 8px; border:1px solid #444; border-radius:3px; "
                            "font-size:10px;} "
                            "QPushButton:hover{background:#353555;}")
        b_add.clicked.connect(self._add_fixture_dialog)
        b_del.clicked.connect(self._delete_selected)
        b_save.clicked.connect(self._save_rig)
        btn_row.addWidget(b_add); btn_row.addWidget(b_del); btn_row.addWidget(b_save)
        side_lay.addLayout(btn_row)

        # Properties (editable)
        side_lay.addWidget(QLabel("Propiedades:"))
        self.props = QGroupBox()
        self.props.setStyleSheet("QGroupBox{background:#0e0e18; border:1px solid #2a2a40; "
                                  "color:#ccc; padding:4px;} "
                                  "QLabel{color:#aaa; font-size:10px;} "
                                  "QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox{"
                                  "background:#1a1a2a; color:#ddd; border:1px solid #333; "
                                  "padding:2px; font-size:10px;}")
        self.props_form = QFormLayout(self.props); self.props_form.setVerticalSpacing(4)
        self._build_props_form()
        side_lay.addWidget(self.props)

        # v1.7 Fase 5 — editor de canales DMX para fixtures no-LED
        self.channel_editor = ChannelEditorWidget()
        self.channel_editor.hide()
        side_lay.addWidget(self.channel_editor)

        side_lay.addStretch()

        lay.addWidget(side)

        # Status
        self.status = QStatusBar()
        self.status.setStyleSheet("background:#161623; color:#9ad; font-size:10px;")
        self.setStatusBar(self.status)
        self.status.showMessage(f"{len(self.rig.fixtures)} fixtures cargados")

        self._current_item: Optional[FixtureItem] = None
        self._rebuild_scene()

    # ── Properties form ─────────────────────────────────────────
    def _build_props_form(self):
        self.f_label = QLineEdit()
        self.f_label.editingFinished.connect(lambda: self._set_prop('label', self.f_label.text()))
        self.props_form.addRow("Label:", self.f_label)

        self.f_profile = QComboBox()
        for pid in list_available_profiles():
            self.f_profile.addItem(pid)
        self.f_profile.currentTextChanged.connect(lambda t: self._set_prop('profile_id', t))
        self.props_form.addRow("Profile:", self.f_profile)

        self.f_universe = QSpinBox(); self.f_universe.setRange(1, 32768)
        self.f_universe.editingFinished.connect(lambda: self._set_prop('universe', self.f_universe.value()))
        self.props_form.addRow("Universe:", self.f_universe)

        self.f_dmx = QSpinBox(); self.f_dmx.setRange(1, 512)
        self.f_dmx.editingFinished.connect(lambda: self._set_prop('dmx_start', self.f_dmx.value()))
        self.props_form.addRow("DMX start:", self.f_dmx)

        self.f_x = QDoubleSpinBox(); self.f_x.setRange(-50, 50); self.f_x.setDecimals(2)
        self.f_x.editingFinished.connect(self._update_pos_from_form)
        self.props_form.addRow("X (m):", self.f_x)

        self.f_y = QDoubleSpinBox(); self.f_y.setRange(-10, 10); self.f_y.setDecimals(2)
        self.f_y.editingFinished.connect(self._update_pos_from_form)
        self.props_form.addRow("Y / altura (m):", self.f_y)

        self.f_z = QDoubleSpinBox(); self.f_z.setRange(-50, 50); self.f_z.setDecimals(2)
        self.f_z.editingFinished.connect(self._update_pos_from_form)
        self.props_form.addRow("Z (m):", self.f_z)

        self.f_ip = QLineEdit()
        self.f_ip.editingFinished.connect(lambda: self._set_prop('target_ip', self.f_ip.text() or None))
        self.props_form.addRow("Art-Net IP:", self.f_ip)

        self._set_props_enabled(False)

    def _set_props_enabled(self, enabled: bool):
        for w in (self.f_label, self.f_profile, self.f_universe, self.f_dmx,
                  self.f_x, self.f_y, self.f_z, self.f_ip):
            w.setEnabled(enabled)

    # ── Render ──────────────────────────────────────────────────
    def _rebuild_scene(self):
        # Conservar selección
        prev_sel = self._current_item.fixture.fixture_id if self._current_item else None

        # Limpiar items de fixtures (no toca el background grid)
        for it in list(self.scene.items()):
            if isinstance(it, FixtureItem):
                self.scene.removeItem(it)

        # Recrear items
        for fx in self.rig.fixtures:
            prof = self.rig.get_profile(fx.profile_id)
            kind = prof.kind if prof else 'default'
            ch = prof.num_channels if prof else 1
            item = FixtureItem(fx, kind=kind, num_channels=ch)
            self.scene.addItem(item)

        # Lista lateral
        self.list_w.clear()
        for fx in self.rig.fixtures:
            it = QListWidgetItem(f"  {fx.fixture_id}  ·  U{fx.universe}/{fx.dmx_start}")
            it.setData(Qt.UserRole, fx.fixture_id)
            self.list_w.addItem(it)

        # Restaurar selección
        if prev_sel:
            self._select_by_id(prev_sel)

    def _find_item_by_id(self, fixture_id: str) -> Optional[FixtureItem]:
        for it in self.scene.items():
            if isinstance(it, FixtureItem) and it.fixture.fixture_id == fixture_id:
                return it
        return None

    def _select_by_id(self, fixture_id: str):
        item = self._find_item_by_id(fixture_id)
        if item:
            self.scene.clearSelection()
            item.setSelected(True)
            self._current_item = item
            self._load_props_from(item.fixture)

    # ── Properties sync ─────────────────────────────────────────
    def _load_props_from(self, fx: Fixture):
        for w in (self.f_label, self.f_profile, self.f_universe, self.f_dmx,
                  self.f_x, self.f_y, self.f_z, self.f_ip):
            w.blockSignals(True)
        self.f_label.setText(fx.label)
        idx = self.f_profile.findText(fx.profile_id)
        if idx >= 0: self.f_profile.setCurrentIndex(idx)
        self.f_universe.setValue(fx.universe)
        self.f_dmx.setValue(fx.dmx_start)
        self.f_x.setValue(fx.position[0])
        self.f_y.setValue(fx.position[1])
        self.f_z.setValue(fx.position[2])
        self.f_ip.setText(fx.target_ip or "")
        for w in (self.f_label, self.f_profile, self.f_universe, self.f_dmx,
                  self.f_x, self.f_y, self.f_z, self.f_ip):
            w.blockSignals(False)
        # Mostrar/ocultar editor de canales según si es LED o no
        prof = self.rig.get_profile(fx.profile_id)
        if prof and prof.kind != 'led_strip' and prof.channel_map:
            self.channel_editor.load_fixture(fx, prof)
        else:
            self.channel_editor.hide()
        self._set_props_enabled(True)

    def _set_prop(self, key: str, value):
        if self._current_item is None: return
        fx = self._current_item.fixture
        setattr(fx, key, value)
        self._rebuild_scene()
        self.status.showMessage(f"{fx.fixture_id}.{key} = {value}", 2000)
        self.rig_changed.emit()

    def _update_pos_from_form(self):
        if self._current_item is None: return
        fx = self._current_item.fixture
        fx.position = (round(self.f_x.value(), 3),
                       round(self.f_y.value(), 3),
                       round(self.f_z.value(), 3))
        self._current_item._set_scene_pos_from_fixture()
        self.rig_changed.emit()

    # ── Signals ─────────────────────────────────────────────────
    def _on_selection_changed(self):
        sel = [it for it in self.scene.selectedItems() if isinstance(it, FixtureItem)]
        if len(sel) == 1:
            self._current_item = sel[0]
            self._load_props_from(sel[0].fixture)
            # sync list
            self.list_w.blockSignals(True)
            for i in range(self.list_w.count()):
                it = self.list_w.item(i)
                if it.data(Qt.UserRole) == sel[0].fixture.fixture_id:
                    self.list_w.setCurrentRow(i); break
            self.list_w.blockSignals(False)
        else:
            self._current_item = None
            self._set_props_enabled(False)
            self.channel_editor.hide()

    def _on_fixture_moved(self, fixture_id: str):
        # Solo refrescar properties si es el seleccionado
        if self._current_item and self._current_item.fixture.fixture_id == fixture_id:
            self._load_props_from(self._current_item.fixture)
        self.rig_changed.emit()

    def _on_list_click(self, item: QListWidgetItem):
        fid = item.data(Qt.UserRole)
        if fid: self._select_by_id(fid)

    # ── Acciones ────────────────────────────────────────────────
    def _add_fixture_dialog(self):
        profiles = list_available_profiles()
        if not profiles:
            QMessageBox.warning(self, "Sin profiles",
                                "No hay profiles en profiles/. Crea uno primero.")
            return
        profile_id, ok = QInputDialog.getItem(self, "Profile",
                                              "Tipo de fixture:", profiles, 0, False)
        if not ok: return
        # Auto-asignar siguiente fixture_id libre
        i = 0
        while True:
            cand = f"{profile_id.split('_')[0]}_{i}"
            if not self.rig.by_id(cand): break
            i += 1
        # Universo siguiente libre
        used = set(f.universe for f in self.rig.fixtures)
        univ = 1
        while univ in used: univ += 1
        new_fx = Fixture(
            fixture_id=cand, profile_id=profile_id,
            universe=univ, dmx_start=1,
            position=(0.0, 1.0, 0.0), label=cand,
        )
        self.rig.fixtures.append(new_fx)
        self._rebuild_scene()
        self._select_by_id(cand)
        self.status.showMessage(f"Añadido {cand} (universe {univ})", 3000)
        self.rig_changed.emit()

    def _delete_selected(self):
        sel = [it for it in self.scene.selectedItems() if isinstance(it, FixtureItem)]
        if not sel: return
        names = [it.fixture.fixture_id for it in sel]
        r = QMessageBox.question(self, "Borrar",
                                 f"¿Borrar {len(sel)} fixture(s)?\n\n" + ", ".join(names))
        if r != QMessageBox.Yes: return
        for it in sel:
            self.rig.fixtures.remove(it.fixture)
        self._rebuild_scene()
        self.status.showMessage(f"Borrados {len(sel)} fixtures", 3000)
        self.rig_changed.emit()

    def _save_rig(self):
        try:
            self.rig.save()
            self.status.showMessage("Rig guardado en fixtures.json", 3000)
        except Exception as e:
            QMessageBox.warning(self, "Error guardando", str(e))


# Self-test (standalone)
if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    rig = build_default_wled_rig()
    w = PatchPanelWindow(rig)
    w.resize(1100, 700)
    w.show()
    sys.exit(app.exec_())
