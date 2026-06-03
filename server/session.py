"""
session.py — ShowSession: dueño headless del modelo + motor (sin Qt).

Replica la construcción que hacía `TimelineEditorWindow.__init__`
(src/ui/timeline_editor.py) pero sin ninguna dependencia de PyQt5:

    timeline      Timeline      (clips/grupos/cues/markers)      ← projects/<slug>/show.json
    fixture_rig   FixtureRig    (fixtures + perfiles)            ← projects/<slug>/rig.json
    analysis      AnalysisService (beats/secciones/eventos)     ← analizadas/<slug>/
    library       EffectLibrary   (51 efectos pixel)
    channel_lib   ChannelEffectLibrary (24 efectos de canal)
    show_engine   ShowEngine    (Art-Net / router / DMX states)
    audio         HeadlessAudioPlayer  (reloj maestro)

Expone exactamente los atributos que leen los 52 handlers del bridge
(`timeline / show_engine / fixture_rig / analysis / library / audio`), de modo
que `dispatcher.py` puede portar esos handlers casi sin cambios.

`compute_frame(t)` es un port Qt-free de `TimelineEditorWindow._compute_frame`,
la ruta autorizada que renderiza los clips del timeline a RGB (el motor corre
con `use_effects=False`; el render real lo hace la EffectLibrary aquí).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from src.core.effects_engine import EffectLibrary, NUM_BARS, LEDS_PER_BAR
from src.core.timeline_model import Timeline, make_default_groups, NUM_TRACKS
from src.core.show_engine import ShowEngine
from src.io.project_manager import get_manager
from src._paths import PROJECT_DIR, VIEWER3D_DIR

LEDS = LEDS_PER_BAR
_BUCKET_MS = 500


class _NullView:
    """Shim Qt-free de `app.tl_view`: absorbe refrescos de UI sin hacer nada.

    Los handlers del bridge tocan métodos/atributos de la vista del timeline
    (rebuild de escena, snap, caches). Aquí no hay UI: los datos se exponen como
    listas/valores reales y los métodos son no-ops. El navegador refetchea vía el
    evento `model_changed` del stream.
    """
    def __init__(self):
        self._snap_grid = 0.25      # 1/4 de beat (igual que el default del editor)
        self._snap_on = True
        self._layers_cache = {}
        self.selected_clips = []
        self.time_markers = []

    def __getattr__(self, name):
        # Cualquier método desconocido (_rebuild_scene, _update_snap_pts, ...) → no-op
        return lambda *a, **k: None


class _NullProps:
    """Shim Qt-free de `app.props` (panel de propiedades). Todo no-op."""
    def __getattr__(self, name):
        return lambda *a, **k: None


class ShowSession:
    """Estado vivo de un show, headless. Reloj maestro = audio del PC."""

    def __init__(self, slug: Optional[str] = None,
                 on_change: Optional[Callable[[str], None]] = None):
        self.on_change = on_change
        self._rev = 0   # se incrementa en cada notify_changed → el navegador refetchea

        # ── Proyecto activo ──────────────────────────────────────────────────
        self.pm = get_manager()
        self.pm.ensure_migrated()
        self.project = self.pm.open_project(slug) if slug else self.pm.current
        if self.project is None:
            self.project = self.pm.current
        print(f"[session] Proyecto: {self.project.name!r} ({self.project.slug})")

        audio_file = Path(self.project.audio_path)
        show_file = self.project.show_file
        rig_file = self.project.rig_file
        analysis_slug = self.project.analysis_slug

        # ── Librerías de efectos ─────────────────────────────────────────────
        self.library = EffectLibrary()
        try:
            from src.core.channel_effects import ChannelEffectLibrary
            self.channel_lib = ChannelEffectLibrary()
        except Exception as e:
            print(f"[session] ChannelEffectLibrary no disponible: {e}")
            self.channel_lib = None

        # Banco de presets (global + por proyecto)
        from server.presets import PresetBank
        self.presets = PresetBank(self.library, self.channel_lib,
                                  project_file=self.project.folder / "presets.json")
        print(f"[session] Presets: {len(self.presets.list())} (banco efectos)")

        # ── Análisis (AnalysisService normaliza v1/v2→v3 + curación) ─────────
        from src.analysis.analyzer_service import AnalysisService, default_service, ANALIZADAS_DIR
        if analysis_slug:
            try:
                self.analysis = AnalysisService(ANALIZADAS_DIR / analysis_slug)
            except Exception:
                self.analysis = default_service()
        else:
            self.analysis = default_service()
        summary = self.analysis.summary
        self.bpm = float(summary.get('bpm') or 128.0)
        dur_s = float(summary.get('duration_s') or 165.0)
        print(f"[session] BPM {self.bpm} ({summary.get('bpm_source','?')}), "
              f"dur {dur_s:.1f}s, downbeats={summary.get('downbeats_source','?')}")

        # ── Timeline ─────────────────────────────────────────────────────────
        dur_ms = int(dur_s * 1000)
        loaded = Timeline.load(show_file) if show_file.is_file() else Timeline.load()
        if loaded.clips:
            self.timeline = loaded
            self.timeline.duration_ms = dur_ms
        else:
            self.timeline = loaded
            self.timeline.duration_ms = dur_ms
        if not getattr(self.timeline, 'groups', None):
            self.timeline.groups = make_default_groups()
        print(f"[session] Timeline: {len(self.timeline.clips)} clips, "
              f"{len(self.timeline.groups)} grupos")

        # ── FixtureRig ───────────────────────────────────────────────────────
        try:
            from src.core.fixtures import FixtureRig, build_default_wled_rig, DEFAULT_RIG_FILE
            rig_source = rig_file if rig_file.is_file() else \
                (DEFAULT_RIG_FILE if DEFAULT_RIG_FILE.is_file() else None)
            if rig_source:
                self.fixture_rig = FixtureRig.load(rig_source)
            else:
                self.fixture_rig = build_default_wled_rig()
            print(f"[session] Rig: {len(self.fixture_rig.fixtures)} fixtures")
        except Exception as e:
            print(f"[session] No se pudo cargar rig: {e}")
            self.fixture_rig = None

        # Regenerar rig_layout.json del visor 3D desde el rig real (en la web
        # nadie lo regeneraba → el visor mostraba un patch obsoleto de 14
        # fixtures aunque el rig tuviera 26).
        self.sync_rig_layout()

        # ── ShowEngine (use_effects=False: render de clips lo hace la library) ─
        try:
            self.show_engine = ShowEngine(use_effects=False,
                                          rig=self.fixture_rig,
                                          analysis=self.analysis)
            self.send_artnet = True
        except Exception as e:
            print(f"[session] ShowEngine no disponible: {e}")
            self.show_engine = None
            self.send_artnet = False

        # ── Audio (reloj maestro) ────────────────────────────────────────────
        from server.audio_headless import HeadlessAudioPlayer
        self.audio = HeadlessAudioPlayer()
        if audio_file.is_file():
            self.audio.load(audio_file, duration=dur_s)
        else:
            print(f"[session] Audio no encontrado: {audio_file}")
            self.audio.duration = dur_s

        # ── Shims para que los handlers del bridge vean la interfaz `app` ────
        # (mismos nombres que TimelineEditorWindow: tl_view, props, _pm, _project)
        self.tl_view = _NullView()
        self.props = _NullProps()
        self._pm = self.pm
        self._project = self.project
        self._dual_window = None  # _qt_call_dual lo lee → None = no-op

        # ── Estado de transporte / render ────────────────────────────────────
        self.loop = False
        self.rec = False
        self.muted_tracks: set[int] = set()
        self.solo_tracks: set[int] = set()
        self._clip_bucket_index: Dict[int, list] = {}
        self._clip_bucket_index_n = -1
        self._cached_actx = {
            'rms': 0.5, 'energy': 0.5, 'flux': 0.3, 'centroid': 4000, 'zcr': 0.2,
            'mfcc': np.zeros(13, dtype=np.float32),
            'chroma': np.full(12, 0.5, dtype=np.float32),
            'tonnetz': np.zeros(6, dtype=np.float32),
            'contrast': np.full(7, 30, dtype=np.float32),
            'mel_bands': np.full(8, -25, dtype=np.float32),
        }

    # ── Sync del layout del visor 3D desde el FixtureRig ─────────────────────
    def sync_rig_layout(self):
        """Genera `rig_layout.json` del visor 3D desde el FixtureRig actual.

        Port headless de `dual_app._sync_rig_to_viewer3d()`. Escribe a las DOS
        rutas: la copia servida (`web/dist/v3d/`) y la fuente (`src/viewer3d/`),
        para que el visor en el navegador refleje el rig real al recargar.
        """
        rig = self.fixture_rig
        if rig is None:
            return
        try:
            import json
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
                "_comment": "Auto-generated from FixtureRig (server.session).",
                "stage": {"width": 12.0, "depth": 6.0,
                          "floor_color": "#1a1a22",
                          "background_color": "#06080c"},
                "fixtures": fixtures_json,
            }
            targets = [
                PROJECT_DIR / "web" / "dist" / "v3d" / "rig_layout.json",
                VIEWER3D_DIR / "rig_layout.json",
            ]
            for target in targets:
                if target.parent.is_dir():
                    with open(target, "w", encoding="utf-8") as f:
                        json.dump(layout, f, indent=2)
            print(f"[session] rig_layout.json regenerado: {len(fixtures_json)} fixtures")
        except Exception as e:
            print(f"[session] sync_rig_layout error: {e}")

    # ── Notificación de cambios (hacia el stream → el navegador re-fetchea) ──
    def notify_changed(self, kind: str = 'model'):
        self._rev += 1
        if self.on_change:
            try:
                self.on_change(kind)
            except Exception:
                pass

    # ── Transporte ───────────────────────────────────────────────────────────
    @property
    def time(self) -> float:
        return self.audio.get_current_time()

    @property
    def playing(self) -> bool:
        return self.audio.playing

    @property
    def duration(self) -> float:
        return self.audio.duration

    def play(self, at: Optional[float] = None):
        self.audio.play(at=at)

    def pause(self):
        self.audio.pause()

    def stop(self):
        self.audio.stop()

    def seek(self, seconds: float):
        self.audio.seek(seconds)

    # ── Métodos que los handlers esperan en `app` (cues / blackout) ──────────
    def _refresh_cue_buttons(self, *a, **k):
        self.notify_changed('cues')

    def _trigger_cue(self, slot: int):
        cue = next((c for c in self.timeline.cue_points if c.slot == slot), None)
        if cue is not None and getattr(cue, 'time_ms', -1) >= 0:
            self.seek(cue.time_ms / 1000.0)
            self.play(at=cue.time_ms / 1000.0)

    def _send_blackout(self, *a, **k):
        """Apaga las luces enviando un frame negro por el motor (si hay)."""
        try:
            if self.show_engine is not None:
                black = np.zeros((NUM_BARS, LEDS, 3), dtype=np.uint8)
                self.show_engine.send_frame(black)
        except Exception:
            pass

    # ── Secciones / compás (para el estado de transporte) ────────────────────
    def section_name_at(self, t: float) -> str:
        try:
            sec = self.analysis.section_at(t)
            if sec is not None:
                return getattr(sec, 'name', None) or getattr(sec, 'label', '') or '—'
        except Exception:
            pass
        return '—'

    def bar_beat(self, t: float):
        beat = int(t / (60.0 / self.bpm)) if self.bpm else 0
        return beat // 4 + 1, beat % 4 + 1

    # ── Mute/Solo (equivalente headless del estado de la vista) ──────────────
    def _track_is_audible(self, track: int) -> bool:
        if self.solo_tracks:
            return track in self.solo_tracks
        return track not in self.muted_tracks

    def _resolve_scope_bars(self, scope: str) -> List[int]:
        """Barras destino de un clip con scope de grupo. Port de timeline_editor."""
        if not isinstance(scope, str):
            return []
        if scope.startswith('group:') or scope.startswith('group_set:'):
            target = scope.split(':', 1)[1]
            groups = getattr(self.timeline, 'groups', []) or []
            for g in groups:
                if g.name == target:
                    return g.resolve_bars(groups)
        return []

    def _build_clip_bucket_index(self):
        buckets: Dict[int, list] = {}
        for c in self.timeline.clips:
            b_lo = max(0, c.start_ms // _BUCKET_MS)
            b_hi = max(b_lo, c.end_ms // _BUCKET_MS)
            for b in range(b_lo, b_hi + 1):
                buckets.setdefault(b, []).append(c)
        for b in buckets:
            buckets[b].sort(key=lambda c: c.layer)
        self._clip_bucket_index = buckets
        self._clip_bucket_index_n = len(self.timeline.clips)

    def invalidate_clip_index(self):
        """Forzar reconstrucción del índice (tras editar clips)."""
        self._clip_bucket_index_n = -1

    def invalidate_caches(self):
        """Invalidar cachés tras edición de clips. Puro, sin Qt."""
        self._clip_bucket_index_n = -1
        self.notify_changed('model')

    def find_clip_by_id(self, clip_id: int | str):
        """Busca un clip por su id (identidad en memoria Python)."""
        clip_id = int(clip_id)
        for c in self.timeline.clips:
            if id(c) == clip_id:
                return c
        return None

    # ── Undo / Redo (snapshots de los clips del timeline) ────────────────────
    def snapshot(self):
        if not hasattr(self, "_undo"):
            self._undo, self._redo = [], []
        self._undo.append([c.to_dict() for c in self.timeline.clips])
        if len(self._undo) > 60:
            self._undo.pop(0)
        self._redo.clear()

    def _set_clips(self, dicts):
        from src.core.timeline_model import Clip
        self.timeline.clips = [Clip.from_dict(d) for d in dicts]
        self.invalidate_clip_index()
        self.notify_changed("undo")

    def undo(self) -> bool:
        if not getattr(self, "_undo", None):
            return False
        self._redo.append([c.to_dict() for c in self.timeline.clips])
        self._set_clips(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not getattr(self, "_redo", None):
            return False
        self._undo.append([c.to_dict() for c in self.timeline.clips])
        self._set_clips(self._redo.pop())
        return True

    def _resolve_clip_effect(self, clip):
        """Devuelve (effect_id, params) del clip, resolviendo el preset si lo tiene.
        Enlace vivo: si el clip apunta a un preset, manda el preset."""
        pid = getattr(clip, "preset_id", None)
        if pid:
            p = self.presets.get(pid)
            if p is not None:
                return p.base_effect_id, p.params
        return clip.effect_id, clip.params

    # ── compute_frame: port Qt-free de TimelineEditorWindow._compute_frame ───
    def compute_frame(self, t_s: float) -> np.ndarray:
        """Renderiza los clips activos en t a un array (NUM_BARS, LEDS, 3) uint8."""
        frame = np.zeros((NUM_BARS, LEDS, 3), dtype=np.uint8)
        t_ms = int(t_s * 1000)
        actx = self._cached_actx

        # Robusto frente a la invalidación del bridge (_dirty_timeline hace
        # `del app._clip_bucket_index` / `_clip_bucket_index_n`).
        if (getattr(self, '_clip_bucket_index_n', -1) != len(self.timeline.clips)
                or not hasattr(self, '_clip_bucket_index')):
            self._build_clip_bucket_index()

        bucket = t_ms // _BUCKET_MS
        for clip in self._clip_bucket_index.get(bucket, ()):
            if clip.start_ms > t_ms or clip.end_ms <= t_ms:
                continue
            if getattr(clip, 'muted', False):
                continue
            if not self._track_is_audible(clip.track):
                continue
            effect_id, params = self._resolve_clip_effect(clip)
            eff = self.library.get_effect(effect_id)
            if not eff:
                continue
            try:
                r = eff.render(elapsed_time=t_ms - clip.start_ms, bars_state=frame,
                               audio_context=actx, **params)
                group_bars = self._resolve_scope_bars(clip.scope)
                if group_bars:
                    if r.shape == (1, LEDS, 3):
                        for b in group_bars:
                            if 0 <= b < NUM_BARS:
                                frame[b] = np.maximum(frame[b], r[0])
                    elif r.shape == (NUM_BARS, LEDS, 3):
                        for b in group_bars:
                            if 0 <= b < NUM_BARS:
                                frame[b] = np.maximum(frame[b], r[b])
                    continue
                if r.shape == (1, LEDS, 3) and 0 <= clip.track < NUM_BARS:
                    frame[clip.track] = (np.maximum(frame[clip.track], r[0])
                                         if clip.layer > 0 else r[0])
                elif r.shape == (NUM_BARS, LEDS, 3):
                    if clip.scope == 'global':
                        frame = np.maximum(frame, r)
                    else:
                        frame[clip.track] = np.maximum(frame[clip.track], r[clip.track])
            except Exception:
                pass
        return frame
