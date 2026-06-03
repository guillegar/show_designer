"""
Sistema de atajos de teclado configurables.

Define una lista de ACCIONES disponibles (Play, Pause, Undo, etc.) con
sus atajos por defecto, los persiste en `shortcuts.json` y ofrece un
diálogo `ShortcutsDialog` para reasignarlos.

Uso desde timeline_editor:
    from shortcuts import ShortcutManager, ShortcutsDialog
    self.shortcuts = ShortcutManager(self)
    self.shortcuts.register('play', 'Reproducir', self._on_play)
    ...
    self.shortcuts.bind_all()
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAction, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QKeySequenceEdit,
    QMessageBox, QShortcut,
)

from src._paths import PROJECT_DIR
SHORTCUTS_FILE = PROJECT_DIR / 'shortcuts.json'


@dataclass
class ShortcutAction:
    """Una acción del editor que puede tener un atajo asignado."""
    key_id: str          # identificador único, ej. 'play'
    label: str           # texto visible, ej. 'Reproducir'
    default_key: str     # atajo por defecto, ej. 'Space'
    current_key: str = ''
    callback: Optional[Callable] = field(default=None, repr=False)
    qshortcut: Optional[QShortcut] = field(default=None, repr=False)

    def __post_init__(self):
        if not self.current_key:
            self.current_key = self.default_key


class ShortcutManager:
    """Centraliza el registro y la asignación de atajos."""

    def __init__(self, parent_widget):
        self.parent = parent_widget
        self.actions: Dict[str, ShortcutAction] = {}
        self._loaded_overrides: Dict[str, str] = self._load()

    def register(self, key_id: str, label: str, callback: Callable,
                 default_key: str = '') -> ShortcutAction:
        """Registra una acción. Si hay override en disco, la usa."""
        override = self._loaded_overrides.get(key_id)
        action = ShortcutAction(
            key_id=key_id, label=label, default_key=default_key,
            current_key=(override if override is not None else default_key),
            callback=callback,
        )
        self.actions[key_id] = action
        return action

    def bind_all(self):
        """
        Crea o reconfigura los QShortcut tras llamar a register().

        Usa ApplicationShortcut porque cuando el TimelineEditorWindow se
        embebe en tabs (con Qt.Widget flag), WindowShortcut no dispara — el
        widget ya no es ventana top-level. ApplicationShortcut funciona desde
        cualquier widget con foco en la aplicación.
        """
        for action in self.actions.values():
            # Reciclar QShortcut si existe; si no, crear
            if action.qshortcut is not None:
                action.qshortcut.setKey(QKeySequence(action.current_key))
            else:
                seq = QKeySequence(action.current_key) if action.current_key else QKeySequence()
                action.qshortcut = QShortcut(seq, self.parent)
                action.qshortcut.setContext(Qt.ApplicationShortcut)
                action.qshortcut.activated.connect(action.callback)

    def save(self):
        data = {a.key_id: a.current_key for a in self.actions.values()}
        try:
            with open(SHORTCUTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[!] No se pudo guardar shortcuts: {e}")

    def _load(self) -> Dict[str, str]:
        if not SHORTCUTS_FILE.is_file():
            return {}
        try:
            with open(SHORTCUTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] No se pudo cargar shortcuts: {e}")
            return {}


class ShortcutsDialog(QDialog):
    """Diálogo modal para editar los atajos de teclado del editor."""

    def __init__(self, manager: ShortcutManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Atajos de teclado")
        self.resize(560, 480)
        self.setStyleSheet("""
            QDialog {background:#181828; color:#ccc;}
            QTableWidget {background:#141420; color:#ddd; gridline-color:#333;
                          selection-background-color:#2a4a8a;}
            QHeaderView::section {background:#252540; color:#aae; padding:4px; border:none;}
            QPushButton {background:#252540; color:#ddd; padding:6px 14px; border:1px solid #444;
                         border-radius:3px; font-weight:bold;}
            QPushButton:hover {background:#353555;}
            QKeySequenceEdit {background:#1e1e30; color:#fff; padding:4px;}
        """)

        lay = QVBoxLayout(self)

        # Tabla
        actions = list(manager.actions.values())
        self.table = QTableWidget(len(actions), 3)
        self.table.setHorizontalHeaderLabels(["Acción", "Atajo actual", "Reasignar"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)

        self._editors: Dict[int, QKeySequenceEdit] = {}
        for row, action in enumerate(actions):
            # Columna 0: label
            it_lbl = QTableWidgetItem(action.label)
            it_lbl.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 0, it_lbl)
            # Columna 1: atajo actual
            it_cur = QTableWidgetItem(action.current_key or '—')
            it_cur.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 1, it_cur)
            # Columna 2: editor
            ed = QKeySequenceEdit(QKeySequence(action.current_key))
            ed.setMaximumWidth(160)
            self._editors[row] = ed
            self.table.setCellWidget(row, 2, ed)
        lay.addWidget(self.table)

        # Botones
        btn_row = QHBoxLayout()
        btn_reset = QPushButton("⟲ Restaurar defaults")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_save  = QPushButton("✔ Aplicar y guardar")
        btn_save.clicked.connect(self._apply_and_save)
        btn_cancel = QPushButton("✗ Cancelar")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_reset); btn_row.addStretch()
        btn_row.addWidget(btn_cancel); btn_row.addWidget(btn_save)
        lay.addLayout(btn_row)

    def _reset_defaults(self):
        for row, action in enumerate(self.manager.actions.values()):
            self._editors[row].setKeySequence(QKeySequence(action.default_key))

    def _apply_and_save(self):
        # Detectar duplicados
        new_keys = {}
        for row, action in enumerate(self.manager.actions.values()):
            key_str = self._editors[row].keySequence().toString()
            if key_str:
                if key_str in new_keys:
                    QMessageBox.warning(
                        self, "Conflicto",
                        f"El atajo '{key_str}' está asignado a más de una acción.\n"
                        f"Quita el duplicado antes de guardar.")
                    return
                new_keys[key_str] = action.key_id
        # Aplicar
        for row, action in enumerate(self.manager.actions.values()):
            new_key = self._editors[row].keySequence().toString()
            action.current_key = new_key
        self.manager.bind_all()
        self.manager.save()
        self.accept()
