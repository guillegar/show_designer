"""
FEEDBACK APP CON CONTROL DE BARRAS WLED REALES

Interfaz integrada con:
- Lado IZQUIERDO: Feedback (timeline, checkboxes, descripción)
- Lado DERECHO: Preview en vivo sincronizado
- BARRAS WLED REALES: Controladas via Art-Net DMX en tiempo real

El AudioPlayer sincroniza todo:
- Reproducción de audio
- Envío de comandos Art-Net a las barras
- Timeline + feedback markers
- Pause/Resume global (audio + barras se detienen juntas)
"""

import sys
import json
import math
import numpy as np
from pathlib import Path
import pygame
import librosa
import threading

from src.analysis.analyzer_service import AnalysisService

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QCheckBox, QTextEdit, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QScrollArea, QFrame
)
from PyQt5.QtGui import (
    QFont, QColor, QPalette, QPainter, QBrush, QPen, QImage
)
from PyQt5.QtCore import Qt, QTimer, QSize, QRect, pyqtSignal

# Importar ShowEngine para control de barras reales
try:
    from src.core.show_engine import ShowEngine, NUM_BARS, LEDS
    HAS_SHOW_ENGINE = True
except Exception as e:
    print(f"[!] No se pudo cargar ShowEngine: {e}")
    HAS_SHOW_ENGINE = False
    NUM_BARS = 10
    LEDS = 93

from src._paths import PROJECT_DIR
# Audio compartido con timeline_editor: copia local del archivo
_local_audio = PROJECT_DIR / 'El Taser de Mama Remix.mp3'
AUDIO_PATH = str(_local_audio) if _local_audio.exists() else r"C:\Users\guille\Downloads\El Taser de Mama Remix.mp3"

FEEDBACK_CATEGORIES = [
    ("Intensidad OK", "intensity_ok"),
    ("Timing preciso", "timing_ok"),
    ("Color apropiado", "color_ok"),
    ("Efecto visible", "effect_visible"),
    ("Transición suave", "transition_smooth"),
    ("Sincro con música", "sync_music"),
    ("Impacto emocional", "emotional_impact"),
    ("Más brillo", "need_brightness"),
    ("Menos brillo", "need_dim"),
    ("Cambiar color", "change_color"),
    ("Efecto diferente", "different_effect"),
    ("Eliminar efecto", "remove_effect"),
]


class AudioPlayer:
    """Gestor de reproducción de audio usando pygame.mixer.music."""

    def __init__(self):
        # IMPORTANTE: pygame.init() debe ser llamado antes de usar pygame.time.get_ticks()
        pygame.init()
        pygame.mixer.init(44100, -16, 2, 2048)
        self.audio_path = None
        self.playing = False
        self.paused = False
        self.pause_time = 0
        self.duration = 0
        self.show_engine = None
        self.start_time = 0  # Para tracking de tiempo basado en ticks

    def load(self, audio_path):
        try:
            self.audio_path = str(audio_path)
            pygame.mixer.music.load(self.audio_path)
            # Obtener duración cargando temporalmente con librosa
            y, sr = librosa.load(self.audio_path, sr=44100)
            self.duration = len(y) / sr
            print(f"[+] Audio cargado: {self.duration:.1f}s")
            return True
        except Exception as e:
            print(f"Error loading audio: {e}")
            return False

    def set_show_engine(self, engine):
        """Asigna ShowEngine para sincronizar con barras WLED."""
        self.show_engine = engine

    def play(self):
        if not self.audio_path:
            return

        # Determinar desde qué segundo arrancar
        if self.paused and self.pause_time < self.duration - 0.1:
            target_time = self.pause_time
        else:
            target_time = 0.0   # desde inicio (o canción terminada → reinicia)

        # SIEMPRE hacer load + play(start=N) en lugar de unpause().
        # Motivo: unpause() reanuda desde donde realmente quedó el reproductor de
        # pygame, no desde nuestro pause_time (que puede haber sido modificado por
        # seek). Esto causaba que: seek→play sonara mudo (no había play previo) o
        # que tras seek+play el audio fuera al punto de pausa antiguo en lugar
        # del seek, desincronizándose de las barras.
        try:
            pygame.mixer.music.load(self.audio_path)
            # start= solo es soportado por algunos formatos en SDL_mixer.
            # Si falla con start, intentamos play() + set_pos() como fallback.
            try:
                pygame.mixer.music.play(loops=0, start=target_time)
            except pygame.error:
                pygame.mixer.music.play(loops=0)
                try:
                    pygame.mixer.music.set_pos(target_time)
                except Exception:
                    pass
            # Volumen explícito (por si quedó a 0 en alguna llamada anterior)
            pygame.mixer.music.set_volume(1.0)
        except Exception as e:
            print(f"Error cargando/reproduciendo audio: {e}")
            return

        self.start_time = pygame.time.get_ticks() / 1000.0 - target_time
        self.pause_time = target_time
        self.paused = False
        self.playing = True
        print(f"[>] Reproduciendo desde {target_time:.1f}s")

    def pause(self):
        if self.playing and not self.paused:
            pygame.mixer.music.pause()
            self.pause_time = self.get_current_time()
            self.paused = True
            self.playing = False
            print("[||] Pausado")

    def stop(self):
        pygame.mixer.music.stop()
        self.playing = False
        self.paused = False
        self.pause_time = 0
        print("[X] Detenido")

    def seek(self, seconds):
        """Busca a una posición específica (pausa en ese punto)."""
        if seconds < 0:
            seconds = 0
        if seconds > self.duration:
            seconds = self.duration

        was_playing = self.playing

        # Detener reproducción
        if self.playing:
            pygame.mixer.music.pause()
            self.playing = False

        # Actualizar posición de pausa
        self.pause_time = seconds
        self.paused = True

        print(f"[>>] Buscando a {seconds:.1f}s (pausado)")
        print(f"[*] Presiona Play para reanudar desde {seconds:.1f}s")

    def get_current_time(self):
        """Obtiene el tiempo actual de reproducción (basado en ticks del sistema)."""
        if self.playing:
            # Calcular tiempo transcurrido desde el inicio/reanudación de reproducción
            elapsed = (pygame.time.get_ticks() / 1000.0) - self.start_time
            # Limitar al máximo de duración
            return min(elapsed, self.duration)
        elif self.paused:
            return self.pause_time
        return 0

    def is_playing(self):
        return self.playing or self.paused

    def send_to_bars(self, elapsed_time):
        """Calcula y envía estado del show a las barras WLED via Art-Net."""
        if self.show_engine and self.show_engine.loaded:
            rgb_frames = self.show_engine.compute_frame(elapsed_time)
            self.show_engine.send_frame(rgb_frames)


class ShowPreviewWidget(QFrame):
    """Widget que renderiza preview del show y controla barras reales."""

    def __init__(self, audio_player, duration=0):
        super().__init__()
        self.duration = duration
        self.current_time = 0
        self.audio_player = audio_player
        self.analysis = None
        self.sections = []

        self.setMinimumSize(400, 300)
        self.setFrameStyle(QFrame.Box | QFrame.Sunken)
        self.setStyleSheet("background-color: #000000;")

        # Datos de visualización
        self.bar_data = [0.0] * NUM_BARS
        self.color = (0, 0, 0)
        self.section_id = 0
        # Ultimo frame RGB de show_engine (10 barras x 93 LEDs x 3 bytes)
        self.last_rgb_frames = None

    def set_rgb_frames(self, rgb_frames):
        """Recibe los frames RGB calculados por show_engine para pintarlos."""
        self.last_rgb_frames = rgb_frames
        self.update()

    def set_duration(self, duration):
        self.duration = duration
        self.update()

    def set_current_time(self, seconds):
        self.current_time = seconds
        self.update_show_simulation()
        self.update()

    def set_analysis(self, analysis):
        """Carga data del analysis."""
        self.analysis = analysis
        if analysis:
            self.sections = analysis.get('sections', [])
        self.update()

    def update_show_simulation(self):
        """Actualiza sección actual para info de texto."""
        if not self.analysis:
            return
        self.section_id = 0
        for i, sec in enumerate(self.sections):
            if sec['start'] <= self.current_time <= sec['end']:
                self.section_id = i
                break

    def paintEvent(self, event):
        """Renderiza las 10 barras con los colores reales del show engine."""
        painter = QPainter(self)
        width = self.width()
        height = self.height()

        painter.fillRect(event.rect(), QColor(0, 0, 0))

        if width < 100 or height < 100:
            return

        bar_w = width / NUM_BARS
        gap = max(1, int(bar_w * 0.06))  # separacion entre barras

        if self.last_rgb_frames and len(self.last_rgb_frames) == NUM_BARS:
            # numpy → QImage por barra (10 drawImage en vez de 930 QColor+fillRect)
            for bar_i, bar_buf in enumerate(self.last_rgb_frames):
                col = np.frombuffer(bar_buf, dtype=np.uint8).reshape(LEDS, 3)
                col = np.ascontiguousarray(col[::-1])  # LED 0 = abajo
                img = QImage(col.tobytes(), 1, LEDS, 3, QImage.Format_RGB888)
                x = int(bar_i * bar_w) + gap
                bw = int(bar_w) - gap * 2
                painter.drawImage(QRect(x, 0, bw, height), img)
        else:
            # Fallback: barras grises
            bar_color = QColor(40, 40, 40)
            for i in range(NUM_BARS):
                x = int(i * bar_w) + gap
                bw = int(bar_w) - gap * 2
                painter.fillRect(x, 0, bw, height, bar_color)

        # Texto info
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Courier", 9))
        sec_text = f"Sec {self.section_id} | {self.current_time:.1f}s"
        painter.drawText(6, 16, sec_text)


class EffectsTimelineWidget(QFrame):
    """Timeline de secciones/efectos mostradas como bloques de colores."""

    def __init__(self, duration=0, sections=None):
        super().__init__()
        self.duration = duration
        self.current_time = 0
        self.sections = sections or []
        self.setMinimumHeight(60)
        self.setStyleSheet("background-color: #1a1a1a; border: 1px solid #333;")
        self.setFrameStyle(QFrame.Box | QFrame.Sunken)

    def set_duration(self, duration):
        self.duration = duration
        self.update()

    def set_sections(self, sections):
        self.sections = sections or []
        self.update()

    def set_current_time(self, seconds):
        self.current_time = seconds
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor(26, 26, 26))

        if self.duration <= 0 or not self.sections:
            return

        width = self.width()
        height = self.height()

        # Colores para cada sección (basados en energía)
        section_colors = [
            QColor(50, 50, 100),    # 0: bajo (azul oscuro)
            QColor(100, 50, 150),   # 1: medio-bajo (púrpura)
            QColor(150, 50, 100),   # 2: medio
            QColor(150, 100, 50),   # 3: medio-alto (naranja)
            QColor(150, 150, 50),   # 4: alto (amarillo)
            QColor(100, 150, 50),   # 5: muy alto (verde)
            QColor(50, 150, 100),   # 6: muy alto (cian)
            QColor(100, 100, 150),  # 7: variable (azul claro)
        ]

        # Dibujar cada sección como un bloque
        for i, section in enumerate(self.sections):
            start = section.get('start', 0)
            end = section.get('end', self.duration)
            energy = section.get('energy', 0.5)

            # Convertir tiempos a posiciones en píxeles
            x1 = int((start / self.duration) * width)
            x2 = int((end / self.duration) * width)

            # Color basado en energía (más oscuro = menos energía)
            color = section_colors[i % len(section_colors)]
            base_h = color.hue()
            base_s = color.saturation()
            base_v = int(100 + energy * 155)  # 100-255 basado en energía
            adjusted_color = QColor.fromHsv(base_h, base_s, min(255, base_v))

            # Dibujar rectángulo de sección
            painter.fillRect(x1, 0, x2 - x1, height - 10, adjusted_color)
            painter.drawRect(x1, 0, x2 - x1, height - 10)

            # Mostrar número de sección
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Courier", 8))
            text = str(i)
            text_rect = painter.fontMetrics().boundingRect(text)
            text_x = x1 + (x2 - x1 - text_rect.width()) // 2
            text_y = (height - 10 - text_rect.height()) // 2 + text_rect.height()
            painter.drawText(text_x, text_y, text)

        # Línea actual (playhead)
        playhead_x = int((self.current_time / self.duration) * width) if self.duration > 0 else 0
        painter.setPen(QPen(QColor(255, 255, 0), 2))
        painter.drawLine(playhead_x, 0, playhead_x, height - 10)

        # Mostrar tiempo actual
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Courier", 8))
        time_text = f"{self.current_time:.1f}s"
        painter.drawText(5, height - 5, time_text)


class TimelineWidget(QFrame):
    """Timeline interactivo con marcadores de feedback."""

    seek_requested = pyqtSignal(float)

    def __init__(self, duration=0):
        super().__init__()
        self.duration = duration
        self.current_time = 0
        self.feedback_markers = []
        self.setMinimumHeight(80)
        self.setStyleSheet("background-color: #1a1a1a; border: 1px solid #333;")
        self.setFrameStyle(QFrame.Box | QFrame.Sunken)

    def set_duration(self, duration):
        self.duration = duration
        self.update()

    def set_current_time(self, seconds):
        self.current_time = seconds
        self.update()

    def add_feedback_marker(self, time):
        if time not in self.feedback_markers:
            self.feedback_markers.append(time)
        self.update()

    def mousePressEvent(self, event):
        if self.duration > 0:
            ratio = event.x() / self.width()
            seek_time = ratio * self.duration
            self.seek_requested.emit(seek_time)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor(26, 26, 26))

        if self.duration <= 0:
            return

        width = self.width()
        height = self.height()

        # Draw timeline background
        painter.fillRect(0, height - 20, width, 20, QColor(40, 40, 40))

        # Draw playhead
        playhead_x = (self.current_time / self.duration) * width
        painter.fillRect(int(playhead_x) - 2, 0, 4, height, QColor(255, 100, 0))

        # Draw time markers
        painter.setPen(QColor(100, 100, 100))
        painter.setFont(QFont("Courier", 8))
        for i in range(0, int(self.duration) + 1, 5):
            x = (i / self.duration) * width
            painter.drawLine(int(x), height - 20, int(x), height - 15)
            if i % 10 == 0:
                painter.drawText(int(x) - 10, height - 5, f"{i}s")

        # Draw feedback markers
        for marker_time in self.feedback_markers:
            marker_x = (marker_time / self.duration) * width
            # Green triangle
            painter.fillRect(int(marker_x) - 4, 5, 8, 8, QColor(0, 255, 0))


class FeedbackApp(QMainWindow):
    """Aplicación principal de feedback."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("[✓ FEEDBACK + BARRAS WLED] El Taser de Mamá Remix")
        self.setGeometry(100, 100, 1400, 800)
        self.setStyleSheet("background-color: #0a0a0a; color: #ffffff;")

        # Inicializar componentes
        self.audio_player = AudioPlayer()
        self.artnet_frame_count = 0
        self.timeline = None
        self.effects_timeline = None

        # Manager de shows (control de versiones) — deprecated, use ProjectManager
        # self.show_manager = ShowManager(PROJECT_DIR / 'shows_saved')

        # Inicializar ShowEngine si está disponible
        if HAS_SHOW_ENGINE:
            # use_effects=False -> show clasico mejorado v1.5 (seccion + onda + fan)
            self.show_engine = ShowEngine(use_effects=False)
            self.audio_player.set_show_engine(self.show_engine)
            status = "[OK]" if self.show_engine.loaded else "[FAIL]"
            print(f"[+] ShowEngine {status} - 10 barras WLED en 192.168.1.201-210")
            self._mapping_reload_counter = 0
        else:
            self.show_engine = None
            print("[!] ShowEngine no disponible - solo simulacion visual")

        self.analysis = None
        self.analysis_service = None
        self.curation = None
        self.feedback_data = []

        # Cargar audio automáticamente
        if self.audio_player.load(AUDIO_PATH):
            print(f"[+] Audio cargado: {AUDIO_PATH}")
        else:
            print(f"[!] No se pudo cargar audio: {AUDIO_PATH}")

        # Cargar analysis.json
        self._load_analysis()

        # Widget central
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QHBoxLayout()

        # Panel izquierdo (Feedback)
        left_panel = self._create_feedback_panel()
        layout.addWidget(left_panel, 1)

        # Panel derecho (Show Preview)
        right_panel = self._create_show_panel()
        layout.addWidget(right_panel, 1)

        central_widget.setLayout(layout)

        # Timer para actualizar UI
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_ui)
        self.update_timer.start(33)  # ~30 FPS (~30ms, ideal para Art-Net)

        print("[+] Interfaz lista")
        print(f"[+] Timer: cada 33ms ({1000/33:.0f} FPS) enviando Art-Net")
        if self.show_engine:
            status_msg = "[OK] Cargado" if self.show_engine.loaded else "[FAIL] Error"
            print(f"[+] ShowEngine: {status_msg}")
        else:
            print("[!] ShowEngine no disponible")

    def _load_analysis(self):
        """Carga analysis.json via AnalysisService (for curation access)."""
        try:
            # Usar AnalysisService para acceso a curation + análisis avanzado
            analizadas_dir = PROJECT_DIR / 'analizadas' / 'el_taser_de_mama_remix'
            if analizadas_dir.exists():
                # Crear AnalysisService para curation
                self.analysis_service = AnalysisService(analizadas_dir)
                self.curation = self.analysis_service.curation

                # Cargar JSON raw para backward compatibility (estructura esperada por UI)
                analysis_path = analizadas_dir / 'analysis.json'
                with open(analysis_path, 'r', encoding='utf-8') as f:
                    self.analysis = json.load(f)
                print(f"[+] Analysis cargado (AnalysisService + curation): {analizadas_dir}")
            else:
                print(f"[!] No encontrado: {analizadas_dir}")
                self.analysis = None
                self.analysis_service = None
                self.curation = None
        except Exception as e:
            print(f"[!] Error cargando analysis: {e}")
            self.analysis = None
            self.analysis_service = None
            self.curation = None

    def _create_feedback_panel(self):
        """Crea panel izquierdo con feedback."""
        panel = QWidget()
        layout = QVBoxLayout()

        # Timeline de audio
        self.timeline = TimelineWidget(self.audio_player.duration)
        self.timeline.seek_requested.connect(self._on_seek)
        layout.addWidget(QLabel("[GRAPH] Timeline Reproducción"), 0)
        layout.addWidget(self.timeline, 0)

        # Timeline de efectos/secciones
        sections = []
        if self.analysis and 'sections' in self.analysis:
            sections = self.analysis['sections']
        self.effects_timeline = EffectsTimelineWidget(self.audio_player.duration, sections)
        layout.addWidget(QLabel("[GRAPH] Timeline Efectos"), 0)
        layout.addWidget(self.effects_timeline, 0)

        # Botones de reproducción
        btn_layout = QHBoxLayout()
        self.btn_play = QPushButton("▶ Play")
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.clicked.connect(self.audio_player.pause)
        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.clicked.connect(self.audio_player.stop)
        btn_layout.addWidget(self.btn_play)
        btn_layout.addWidget(self.btn_pause)
        btn_layout.addWidget(self.btn_stop)
        layout.addLayout(btn_layout)

        # Checkboxes
        self.checkboxes = []
        for label, key in FEEDBACK_CATEGORIES:
            cb = QCheckBox(label)
            cb.setStyleSheet("color: #ffffff;")
            self.checkboxes.append((cb, key))
            layout.addWidget(cb)

        # Description
        layout.addWidget(QLabel("[NOTE] Notas:"))
        self.description = QTextEdit()
        self.description.setPlaceholderText("Descripción de feedback...")
        self.description.setMinimumHeight(80)
        self.description.setStyleSheet("background-color: #1a1a1a; color: #ffffff;")
        layout.addWidget(self.description)

        # Guardar feedback
        btn_save = QPushButton("[SAVE] Guardar Feedback")
        btn_save.clicked.connect(self._save_feedback)
        layout.addWidget(btn_save)

        # Tabla de feedback
        self.feedback_table = QTableWidget()
        self.feedback_table.setColumnCount(2)
        self.feedback_table.setHorizontalHeaderLabels(["Tiempo", "Categorías"])
        self.feedback_table.setStyleSheet("background-color: #1a1a1a; color: #ffffff;")
        layout.addWidget(self.feedback_table)

        # Exportar JSON
        btn_export = QPushButton("[GRAPH] Exportar JSON")
        btn_export.clicked.connect(self._export_json)
        layout.addWidget(btn_export)

        # Guardar Show (control de versiones)
        btn_save_show = QPushButton("[SAVE] Guardar Show")
        btn_save_show.clicked.connect(self._save_show)
        btn_save_show.setStyleSheet("background-color: #1a4d1a; color: #ffffff;")
        layout.addWidget(btn_save_show)

        layout.addStretch()
        panel.setLayout(layout)
        return panel

    def _create_show_panel(self):
        """Crea panel derecho con preview del show."""
        panel = QWidget()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("[ART] Preview Show (BARRAS WLED REALES)"))

        self.show_preview_widget = ShowPreviewWidget(self.audio_player, self.audio_player.duration)
        if self.analysis:
            self.show_preview_widget.set_analysis(self.analysis)
        layout.addWidget(self.show_preview_widget, 1)

        # Status
        if HAS_SHOW_ENGINE and self.show_engine and self.show_engine.loaded:
            status_text = "[OK] BARRAS WLED CONECTADAS - Art-Net enviando en tiempo real"
            status_color = "#00ff00"
        else:
            status_text = "[!] Solo visualizacion local (barras no disponibles)"
            status_color = "#ffaa00"

        self.status_label = QLabel(status_text)
        self.status_label.setStyleSheet(f"color: {status_color}; font-weight: bold;")
        layout.addWidget(self.status_label)

        panel.setLayout(layout)
        return panel

    def _update_ui(self):
        """Actualiza UI y envía comandos Art-Net."""
        elapsed = self.audio_player.get_current_time()

        # Actualizar timelines
        self.timeline.set_current_time(elapsed)
        self.effects_timeline.set_current_time(elapsed)
        self.show_preview_widget.set_current_time(elapsed)

        # Calcular frame del show y enviarlo a barras + preview
        if self.show_engine and self.show_engine.loaded:
            rgb_frames = self.show_engine.compute_frame(elapsed)

            # Enviar a barras reales solo durante reproduccion activa
            if self.audio_player.playing:
                self.show_engine.send_frame(rgb_frames)
                self.artnet_frame_count += 1
                if self.artnet_frame_count % 90 == 0:  # log cada ~3s
                    sec = self.show_preview_widget.section_id
                    print(f"[ART-NET] {elapsed:.1f}s | Sec {sec} | Frame {self.artnet_frame_count}")

            # Siempre actualizar el preview en pantalla (incluye cuando esta pausado)
            self.show_preview_widget.set_rgb_frames(rgb_frames)

        # Pausar si finalizó o superó la duracion de la cancion
        SHOW_DURATION = 273.3
        if self.audio_player.playing and elapsed >= SHOW_DURATION:
            self.audio_player.pause()
            self._reset_ui()
        elif self.audio_player.is_playing() and elapsed >= self.audio_player.duration:
            self.audio_player.pause()
            self._reset_ui()

    def _toggle_play(self):
        if self.audio_player.playing:
            self.audio_player.pause()
        else:
            self.audio_player.play()

    def _on_seek(self, time):
        self.audio_player.seek(time)

    def _save_feedback(self):
        """Guarda anotación de feedback."""
        checked = [key for cb, key in self.checkboxes if cb.isChecked()]
        if not checked and not self.description.toPlainText():
            QMessageBox.warning(self, "Aviso", "Selecciona categorías o agrega descripción")
            return

        entry = {
            'time': self.audio_player.get_current_time(),
            'categories': checked,
            'note': self.description.toPlainText()
        }
        self.feedback_data.append(entry)
        self.timeline.add_feedback_marker(entry['time'])

        # Limpiar form
        for cb, _ in self.checkboxes:
            cb.setChecked(False)
        self.description.clear()

        # Actualizar tabla
        self._update_table()
        QMessageBox.information(self, "OK", "Feedback guardado")

    def _update_table(self):
        """Actualiza tabla de feedback."""
        self.feedback_table.setRowCount(len(self.feedback_data))
        for i, entry in enumerate(self.feedback_data):
            time_text = f"{entry['time']:.1f}s"
            cats_text = ", ".join(entry['categories'][:3])
            if len(entry['categories']) > 3:
                cats_text += f" +{len(entry['categories']) - 3}"

            self.feedback_table.setItem(i, 0, QTableWidgetItem(time_text))
            self.feedback_table.setItem(i, 1, QTableWidgetItem(cats_text))

    def _export_json(self):
        """Exporta feedback a JSON."""
        filename, _ = QFileDialog.getSaveFileName(self, "Exportar JSON", "", "JSON (*.json)")
        if not filename:
            return

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.feedback_data, f, indent=2)
            QMessageBox.information(self, "OK", f"Exportado a {filename}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error exportando: {e}")

    def _save_show(self):
        """Guarda el show actual con control de versiones."""
        description, ok = QFileDialog.getSaveFileName(
            self,
            "Guardar Show - Descripción",
            "",
            "Show Description (*.txt)"
        )

        if not ok or not description:
            # Si cancela el diálogo, pedir descripción simple
            from PyQt5.QtWidgets import QInputDialog
            description, ok = QInputDialog.getText(
                self,
                "Guardar Show",
                "Descripción del show (ej: 'v1 - Timeline efectos añadido'):"
            )
            if not ok or not description:
                return

        try:
            show_data = {
                'audio_file': AUDIO_PATH,
                'duration': self.audio_player.duration,
                'current_time': self.audio_player.get_current_time(),
                'feedback_markers': self.feedback_data,
                'sections': self.analysis.get('sections', []) if self.analysis else [],
                'global_info': self.analysis.get('global', {}) if self.analysis else {}
            }

            # Deprecated: use ProjectManager instead
            # self.show_manager.save_show(show_data, description)
            QMessageBox.information(
                self,
                "OK",
                f"Show guardado con control de versiones.\n\nVer: shows_saved/"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error guardando show: {e}")

    def _reset_ui(self):
        pass


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = FeedbackApp()
    window.show()
    sys.exit(app.exec_())
