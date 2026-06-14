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
_FPS_BAKED = 30  # B3: FPS del render offline (debe coincidir con offline_render._FPS)


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

        # ── C1: motor de performance en vivo ─────────────────────────────────
        from server.live_engine import LiveEngine
        self.live_engine = LiveEngine()
        if getattr(self.timeline, 'live_slots', None):
            self.live_engine.slots_from_dicts(self.timeline.live_slots)

        # ── D1: motor AutoVJ (estado live, no se persiste en show.json) ────
        from src.core.autovj import AutoVJEngine
        self.autovj_engine = AutoVJEngine()
        _autovj_path = self.project.folder / "autovj.json"
        if _autovj_path.is_file():
            self.autovj_engine.load(_autovj_path)

        # ── D2: entrada de audio en vivo (None hasta que el usuario la active) ─
        self.live_input = None   # LiveInput | None
        self._live_mode = False  # True = usar live_input en vez de analysis

        # ── C2: macros en vivo (estado live, NO se persisten en show.json) ──
        self.macros: Dict[str, float] = {
            "brightness_mul": 1.0,
            "speed_mul": 1.0,
            "hue_shift": 0.0,
            "strobe_rate": 0.0,
        }

        # ── I1: grabación en vivo de macros ─────────────────────────────────
        self._recording: bool = False
        self._record_start_ms: float = 0.0
        self._recorded_lanes: Dict[str, list] = {}  # macro_name → [{t_ms, value}]
        self._record_last_ms: Dict[str, float] = {}  # throttle 50ms por macro

        # ── Estado de transporte / render ────────────────────────────────────
        self.loop = False
        self.rec = False
        self.muted_tracks: set[int] = set()
        self.solo_tracks: set[int] = set()
        # B3: estado del render offline + playback baked
        self.baked_frames: Optional[np.ndarray] = None  # None = modo live normal
        self.baked_hash: Optional[str] = None            # hash del show al bakear
        self.render_in_progress: bool = False
        self.render_pct: float = 0.0
        self.hub = None  # StreamHub; asignado por web.py tras construir la sesión
        self._clip_bucket_index: Dict[int, list] = {}
        self._clip_bucket_index_n = -1
        # A3: cache de clips efímeros expandidos de PatternInstances.
        # _pattern_rev se incrementa al mutar patterns/instances, forzando re-expansión.
        self._pattern_rev: int = 0
        self._pattern_expanded: list = []
        self._pattern_expanded_rev: int = -1
        # B4: autosave — rev en el último autosave (compara con _rev para detectar cambios)
        self._last_saved_rev: int = 0
        # Evita mostrar el banner de autosave más de una vez por arranque
        self._autosave_banner_shown: bool = False

        # E2: OSC bridge (asignado por web.py tras construir la sesión)
        self.osc_bridge = None

        # G2: sync de tempo vía Ableton Link o MIDI Clock
        from server.tempo_sync import TempoSyncService
        self.tempo_sync = TempoSyncService()

        # E4: estado runtime de herramientas de test de output (no persiste)
        self.blackout_override: bool = False   # blackout duro de pánico (instantáneo)
        self._identify: Dict[str, float] = {}  # fixture_id → t_expires (monotonic)
        self._test_universes: Dict[int, tuple] = {}  # universe → (r, g, b)

        # E1: estado runtime de cues (no se persiste en show.json)
        self._cue_fade_start_ms: Optional[float] = None    # timeline_ms donde empezó el fade
        self._cue_fade_duration_ms: float = 0.0
        self._cue_fade_from_master: float = 1.0             # brightness del master al iniciar
        self._cue_auto_follow_task = None                   # asyncio.Task activo
        self._cue_last_fade_pct: float = 1.0                # throttle >1% para cue_changed

        # Undo/redo extraído a UndoManager (SRP). A3: se añaden get_extra/restore_extra
        # para que patterns y pattern_instances entren en el snapshot (invariante I1).
        from server.undo_manager import UndoManager
        self.undo_manager = UndoManager(
            get_clips=lambda: self.timeline.clips,
            restore_clips=self._restore_clips,
            get_extra=lambda: {
                "patterns": list(self.timeline.patterns),
                "pattern_instances": list(self.timeline.pattern_instances),
                "mixer": dict(self.timeline.mixer),
                "live_slots": self.live_engine.slots_to_dicts(),
                "cue_list": self.timeline.cue_list.to_dict(),  # E1: I1
                "automation": list(self.timeline.automation),  # I1: undo covers recorded lanes
                "markers": [m.to_dict() for m in self.timeline.markers],  # I2
            },
            restore_extra=self._restore_pattern_state,
        )
        # Desacople (B1): política headless de `_qt_call` del bridge. Antes el
        # dispatcher parcheaba el módulo global; ahora la sesión la provee a nivel
        # de instancia (el bridge la detecta vía getattr). Sin Qt: ejecuta inline
        # y notifica el cambio al stream para que el navegador refresque.
        self._qt_call_impl = self._headless_qt_call
        self._qt_call_dual_impl = self._headless_qt_call_dual
        # F0.0: _cached_actx es SOLO el fallback para proyectos sin análisis.
        # El render usa el contexto REAL de AnalysisService (ver _get_audio_context).
        self._cached_actx = {
            'rms': 0.5, 'energy': 0.5, 'flux': 0.3, 'centroid': 4000, 'zcr': 0.2,
            'mfcc': np.zeros(13, dtype=np.float32),
            'chroma': np.full(12, 0.5, dtype=np.float32),
            'tonnetz': np.zeros(6, dtype=np.float32),
            'contrast': np.full(7, 30, dtype=np.float32),
            'mel_bands': np.full(8, -25, dtype=np.float32),
        }
        # F0.1: pipeline de parámetros — punto de extensión único (ROADMAP v2).
        # Orden canónico: modulación (A1) → automatización (A2) → micro-eventos
        # (A4) → macros (C2). Vacío = comportamiento idéntico al anterior.
        from src.core.modulation import ModulationStage
        from src.core.automation import AutomationStage
        from src.core.micro_events import MicroEventStage
        from src.core.param_pipeline import MacroStage
        self.param_stages: list = [
            ModulationStage(),
            AutomationStage(get_automation_lanes=self._get_automation_lanes),
            MicroEventStage(),
            MacroStage(self.macros),  # C2: referencia viva al dict — siempre ve el valor actual
        ]

    # ── Helpers para el pipeline de parámetros ───────────────────────────────
    def _get_automation_lanes(self):
        """Devuelve las lanes de automatización del timeline (para AutomationStage)."""
        from src.core.automation import AutomationLane
        return [AutomationLane.from_dict(d) for d in self.timeline.automation]

    # ── Sync del layout del visor 3D desde el FixtureRig ─────────────────────
    def sync_rig_layout(self):
        """Genera `rig_layout.json` del visor 3D desde el FixtureRig actual.

        Port headless de `dual_app._sync_rig_to_viewer3d()`. Escribe a las DOS
        rutas: la copia servida (`web/dist/v3d/`) y la fuente única
        (`web/public/v3d/` vía VIEWER3D_DIR), para que el visor en el navegador
        refleje el rig real al recargar.

        K1: si existe projects/<slug>/rig_layout.json, sus posiciones 3D explícitas
        sobreescriben las generadas automáticamente desde fx.position/rotation.
        """
        rig = self.fixture_rig
        if rig is None:
            return
        try:
            import json

            # K1 — cargar posiciones explícitas del usuario (si existen)
            k1_positions: dict = {}
            proj = getattr(self, "project", None)
            if proj is not None:
                layout_file = getattr(proj, "rig_layout_file", None)
                if layout_file is not None and layout_file.is_file():
                    try:
                        with open(layout_file, "r", encoding="utf-8") as f:
                            k1_data = json.load(f)
                        for e in k1_data.get("fixtures", []):
                            fid = e.get("id")
                            if fid:
                                k1_positions[fid] = e
                    except Exception:
                        pass

            fixtures_json = []
            for fx in rig.fixtures:
                prof = rig.get_profile(fx.profile_id)
                k1 = k1_positions.get(fx.fixture_id)
                if k1:
                    position = [k1["x"], k1["y"], k1["z"]]
                    rotation = [k1.get("rx", 0.0), k1.get("ry", 0.0), k1.get("rz", 0.0)]
                else:
                    position = list(fx.position)
                    rotation = list(fx.rotation)
                entry = {
                    "id": fx.fixture_id,
                    "type": prof.kind if prof else "led_strip",
                    "leds": prof.led_count if prof else 93,
                    "position": position,
                    "rotation": rotation,
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
        # A3: re-expandir instancias si cambió _pattern_rev
        if self._pattern_expanded_rev != self._pattern_rev:
            self._pattern_expanded = self._expand_all_pattern_instances()
            self._pattern_expanded_rev = self._pattern_rev

        buckets: Dict[int, list] = {}
        for c in self.timeline.clips + self._pattern_expanded:
            b_lo = max(0, c.start_ms // _BUCKET_MS)
            b_hi = max(b_lo, c.end_ms // _BUCKET_MS)
            for b in range(b_lo, b_hi + 1):
                buckets.setdefault(b, []).append(c)
        for b in buckets:
            buckets[b].sort(key=lambda c: c.layer)
        self._clip_bucket_index = buckets
        # Sólo cuenta clips reales para detectar cambios (efímeros no se editan)
        self._clip_bucket_index_n = len(self.timeline.clips)

    def _expand_all_pattern_instances(self) -> list:
        """Expande todas las PatternInstances a Clips efímeros con tiempos absolutos.

        Los clips efímeros tienen uid con '::' (marcador) para distinguirlos
        de los clips reales. NO aparecen en list_clips ni son editables.
        Sólo se usan para el render (bucket index).
        """
        from src.core.timeline_model import Pattern, PatternInstance, Clip
        result = []
        for inst_d in self.timeline.pattern_instances:
            inst = PatternInstance.from_dict(inst_d)
            pat_d = next(
                (p for p in self.timeline.patterns if p.get("uid") == inst.pattern_uid),
                None,
            )
            if pat_d is None:
                continue
            pat = Pattern.from_dict(pat_d)
            for clip in pat.clips:
                result.append(Clip(
                    track=max(0, min(9, clip.track + inst.track_offset)),
                    start_ms=inst.start_ms + clip.start_ms,
                    end_ms=inst.start_ms + clip.end_ms,
                    effect_id=clip.effect_id,
                    scope=clip.scope,
                    params=dict(clip.params),
                    color=clip.color,
                    label=clip.label,
                    layer=clip.layer,
                    locked=False,
                    muted=clip.muted,
                    category=clip.category,
                    channel_effect_id=clip.channel_effect_id,
                    preset_id=clip.preset_id,
                    uid=f"{inst.uid}::{clip.uid}",  # marcador de clip efímero
                    param_links=list(clip.param_links),
                ))
        return result

    def invalidate_clip_index(self):
        """Forzar reconstrucción del índice (tras editar clips)."""
        self._clip_bucket_index_n = -1

    def invalidate_caches(self):
        """Invalidar cachés tras edición de clips. Puro, sin Qt.

        B3: toda mutación del timeline invalida el render bakeado (el hash del
        show ya no coincidirá con el npz en disco → compute_frame vuelve al
        modo live).
        """
        self._clip_bucket_index_n = -1
        # B3: cualquier mutación del timeline invalida el baked (I4 inverso:
        # si el usuario edita, el npz es obsoleto — no se sirve basura)
        self.baked_frames = None
        self.baked_hash = None
        self.notify_changed('model')

    def invalidate_pattern_cache(self) -> None:
        """Llamar tras mutar patterns o pattern_instances (A3).

        Incrementa _pattern_rev para que _build_clip_bucket_index re-expanda
        las instancias en el próximo frame. B3: también invalida el baked.
        """
        self._pattern_rev += 1
        self._clip_bucket_index_n = -1
        # B3: mutar patterns también invalida el render bakeado
        self.baked_frames = None
        self.baked_hash = None
        self.notify_changed('model')

    def find_clip_by_id(self, clip_id):
        """Busca un clip por su `uid` (estable y persistido, ANALYSIS hallazgo 2).

        Compat: durante la transición acepta también el `id(self)` entero legacy
        (clientes que guardaron una referencia antigua).
        """
        key = str(clip_id)
        for c in self.timeline.clips:
            if getattr(c, 'uid', None) == key:
                return c
        # Fallback legacy: clip_id numérico = id(objeto) en memoria
        try:
            legacy = int(clip_id)
        except (TypeError, ValueError):
            return None
        for c in self.timeline.clips:
            if id(c) == legacy:
                return c
        return None

    # ── Política headless de _qt_call del bridge (B1) ────────────────────────
    def _headless_qt_call(self, fn):
        """Reemplazo headless de QTimer.singleShot: ejecuta inline + notifica."""
        try:
            fn()
        except Exception as e:
            print(f"[session] qt_call inline error: {e}")
        try:
            self.notify_changed('model')
        except Exception:
            pass

    def _headless_qt_call_dual(self, method_name):
        """En headless no hay ventana Qt; solo notifica para refrescar la vista."""
        try:
            self.notify_changed(method_name)
        except Exception:
            pass

    # ── Undo / Redo — delegado en UndoManager (server/undo_manager.py) ───────
    def _restore_clips(self, dicts):
        from src.core.timeline_model import Clip
        self.timeline.clips = [Clip.from_dict(d) for d in dicts]
        self.invalidate_clip_index()
        self.notify_changed("undo")

    def _restore_pattern_state(self, extra: dict) -> None:
        """Restaura patterns, pattern_instances, mixer, live_slots, cue_list y automation (I1)."""
        self.timeline.patterns = list(extra.get("patterns", []))
        self.timeline.pattern_instances = list(extra.get("pattern_instances", []))
        if "mixer" in extra:
            self.timeline.mixer = dict(extra["mixer"])
        if "live_slots" in extra:
            self.live_engine.slots_from_dicts(extra["live_slots"])
            self.timeline.live_slots = self.live_engine.slots_to_dicts()
        # E1: restaurar cue_list del snapshot (I1)
        if "cue_list" in extra:
            from src.core.timeline_model import CueList
            self.timeline.cue_list = CueList.from_dict(extra["cue_list"])
        # I1: restaurar lanes de automatización grabadas (undo de stop_record)
        if "automation" in extra:
            self.timeline.automation = list(extra["automation"])
        # I2: restaurar marcadores de timeline
        if "markers" in extra:
            from src.core.timeline_model import Marker
            self.timeline.markers = [Marker.from_dict(d) for d in extra["markers"]]
        self._pattern_rev += 1
        self._clip_bucket_index_n = -1

    # ── I1: grabación en vivo de macros ─────────────────────────────────────

    _REC_DEFAULTS: Dict[str, float] = {
        "brightness_mul": 1.0,
        "speed_mul": 1.0,
        "hue_shift": 0.0,
        "strobe_rate": 0.0,
    }

    def _normalize_macro(self, name: str, value: float) -> float:
        if name == "brightness_mul":
            return value / 2.0
        if name == "speed_mul":
            return value / 4.0
        if name == "hue_shift":
            return (value + 180.0) / 360.0
        if name == "strobe_rate":
            return value / 30.0
        return value

    def _maybe_record_macros(self, t_ms: int) -> None:
        """Captura valores de macros no-default durante grabación (throttle 50ms, I4)."""
        if not self._recording:
            return
        for name in ("brightness_mul", "speed_mul", "hue_shift", "strobe_rate"):
            val = self.macros.get(name, self._REC_DEFAULTS[name])
            if val == self._REC_DEFAULTS[name]:
                continue
            last = self._record_last_ms.get(name, -9999.0)
            if t_ms - last < 50:
                continue
            normalized = self._normalize_macro(name, val)
            self._recorded_lanes.setdefault(name, []).append(
                {"t_ms": t_ms, "value": normalized}
            )
            self._record_last_ms[name] = float(t_ms)

    def snapshot(self):
        self.undo_manager.snapshot()

    def undo(self) -> bool:
        return self.undo_manager.undo()

    def redo(self) -> bool:
        return self.undo_manager.redo()

    # ── E1: Sistema de Cues profesional ─────────────────────────────────────

    @property
    def _current_t_ms(self) -> int:
        """Posición actual del playhead en milisegundos (O(1))."""
        return int(self.time * 1000)

    def _find_cue_by_uid(self, uid: str):
        """Busca una CueEntry por uid (O(n), n << 100)."""
        return next(
            (e for e in self.timeline.cue_list.entries if e.uid == uid), None
        )

    def go_cue(self, uid: str):
        """Salta al cue con el uid dado: seek, fade y auto-follow.

        Devuelve la CueEntry o None si no se encontró.
        El fade (0→1) se aplica como multiplicador en compute_frame (I4).
        El auto-follow usa asyncio.create_task (I4 — sin time.sleep).
        """
        cue = self._find_cue_by_uid(uid)
        if cue is None:
            return None
        self.timeline.cue_list.active_uid = uid
        self.audio.seek(cue.t_ms / 1000.0)
        if cue.fade_in_ms > 0:
            self._cue_fade_start_ms = float(cue.t_ms)
            self._cue_fade_duration_ms = float(cue.fade_in_ms)
        else:
            self._cue_fade_start_ms = None
        # Cancelar tarea de auto-follow anterior
        if self._cue_auto_follow_task is not None:
            try:
                self._cue_auto_follow_task.cancel()
            except Exception:
                pass
            self._cue_auto_follow_task = None
        if cue.auto_follow and cue.hold_ms >= 0:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                self._cue_auto_follow_task = loop.create_task(
                    self._auto_follow_task(cue.hold_ms)
                )
            except RuntimeError:
                pass  # sin event loop (contexto de tests)
        self.notify_changed('cues')
        return cue

    async def _auto_follow_task(self, hold_ms: int):
        """Tarea asyncio: tras hold_ms avanza al siguiente cue (I4)."""
        import asyncio
        await asyncio.sleep(hold_ms / 1000.0)
        self.go_next_cue()

    def go_next_cue(self):
        """Avanza al siguiente CueEntry por número. No-op si ya es el último."""
        entries = self.timeline.cue_list.entries
        if not entries:
            return None
        active = self.timeline.cue_list.active_uid
        if active is None:
            return self.go_cue(entries[0].uid)
        for i, e in enumerate(entries):
            if e.uid == active and i + 1 < len(entries):
                return self.go_cue(entries[i + 1].uid)
        return None

    def go_prev_cue(self):
        """Retrocede al CueEntry anterior por número. No-op si ya es el primero."""
        entries = self.timeline.cue_list.entries
        if not entries:
            return None
        active = self.timeline.cue_list.active_uid
        if active is None:
            return None
        for i, e in enumerate(entries):
            if e.uid == active and i > 0:
                return self.go_cue(entries[i - 1].uid)
        return None

    def get_cue_state(self) -> dict:
        """Estado actual de la CueList (O(1)): active_uid, fade_pct, next_uid."""
        active_uid = self.timeline.cue_list.active_uid
        entries = self.timeline.cue_list.entries
        # Calcular fade_pct a partir del tiempo del timeline
        fade_pct = 1.0
        if self._cue_fade_start_ms is not None and self._cue_fade_duration_ms > 0:
            elapsed = self._current_t_ms - self._cue_fade_start_ms
            fade_pct = min(1.0, max(0.0, elapsed / self._cue_fade_duration_ms))
        # Siguiente cue (para la flecha ▶ en UI)
        next_uid = None
        for i, e in enumerate(entries):
            if e.uid == active_uid and i + 1 < len(entries):
                next_uid = entries[i + 1].uid
                break
        return {
            "active_uid": active_uid,
            "fade_pct": round(fade_pct, 4),
            "next_uid": next_uid,
        }

    def _resolve_clip_effect(self, clip):
        """Devuelve (effect_id, params) del clip, resolviendo el preset si lo tiene.
        Enlace vivo: si el clip apunta a un preset, manda el preset."""
        pid = getattr(clip, "preset_id", None)
        if pid:
            p = self.presets.get(pid)
            if p is not None:
                return p.base_effect_id, p.params
        return clip.effect_id, clip.params

    def _get_audio_context(self, t_s: float) -> dict:
        """Audio context REAL en t (F0.0, ROADMAP v2).

        D2: si live_mode activo usa LiveInput (features del ring buffer en vivo).
        Offline: delega en AnalysisService (un searchsorted + lerp vectorizado).
        Fallback al contexto estático si no hay timeseries disponible.
        """
        # D2: modo live — features del stream de audio de entrada
        if self._live_mode and self.live_input is not None:
            try:
                return self.live_input.get_audio_context(t_s)
            except Exception as e:
                import logging
                from src.log import get_logger, log_throttled
                log_throttled(get_logger(__name__), logging.WARNING,
                              'session.actx_live',
                              f"live_input.get_audio_context error: {e}")

        svc = self.analysis
        try:
            if svc is not None and getattr(svc, 'has_timeseries', False):
                actx = svc.get_audio_context(t_s)
            else:
                actx = self._cached_actx
        except Exception as e:
            import logging as _logging
            from src.log import get_logger as _get_logger, log_throttled as _log_throttled
            _log_throttled(_get_logger(__name__), _logging.WARNING,
                           'session.actx', f"get_audio_context({t_s:.2f}) error: {e}")
            actx = self._cached_actx

        # G2: si hay sync de tempo activo, sobreescribir el BPM del contexto
        ts = getattr(self, 'tempo_sync', None)
        if ts is not None and ts.bpm > 0.0:
            actx = dict(actx)  # copia shallow para no mutar el cache
            actx["bpm"] = ts.bpm
        return actx

    # ── B3: baked frames ─────────────────────────────────────────────────────

    def load_baked_frames(self) -> bool:
        """Lee render.npz si existe y el hash coincide con el timeline actual.

        Devuelve True si cargó correctamente (= baked mode activado).
        Si el hash no coincide (render obsoleto), no carga nada y devuelve False.
        """
        import json as _json
        from server.offline_render import compute_timeline_hash

        out_path = self.project.folder / "render.npz"
        meta_path = self.project.folder / "render_meta.json"
        if not out_path.is_file() or not meta_path.is_file():
            return False
        try:
            with open(meta_path, encoding='utf-8') as f:
                meta = _json.load(f)
            current_hash = compute_timeline_hash(self.timeline.to_dict())
            if meta.get("show_hash") != current_hash:
                return False  # render obsoleto → no cargar
            data = np.load(str(out_path))
            self.baked_frames = data['frames']
            self.baked_hash = meta.get("show_hash")
            return True
        except Exception as e:
            print(f"[session] load_baked_frames error: {e}")
            return False

    # ── compute_frame: port Qt-free de TimelineEditorWindow._compute_frame ───
    def compute_frame(self, t_s: float) -> np.ndarray:
        """Renderiza los clips activos en t a un array (NUM_BARS, LEDS, 3) uint8.

        B3: si hay frames bakeados cargados (baked mode ON) y no hay render en
        curso, sirve el frame del npz en vez de computar. El postfx/master (B2)
        se aplica igualmente sobre el frame bakeado, así el modo baked sigue
        siendo "tocable" en directo.
        """
        # B3: ruta baked — sirve frame del npz + aplica postfx/master
        if self.baked_frames is not None and not self.render_in_progress:
            n_frames = len(self.baked_frames)
            frame_idx = max(0, min(n_frames - 1, round(t_s * _FPS_BAKED)))
            frame = self.baked_frames[frame_idx].copy()
            # Postfx/master (B2) + C2 hue_shift sobre el frame bakeado
            mixer = self.timeline.mixer
            from src.core.postfx import apply_track_chain, apply_master
            if mixer:
                track_chains = mixer.get("tracks", {})
                if track_chains:
                    for track_key, chain in track_chains.items():
                        try:
                            track_idx = int(track_key)
                            if 0 <= track_idx < NUM_BARS and chain:
                                frame[track_idx] = apply_track_chain(frame[track_idx], chain)
                        except (ValueError, TypeError):
                            pass
            master_chain = dict(mixer.get("master", {})) if mixer else {}
            macro_hue = self.macros.get("hue_shift", 0.0)
            if macro_hue:
                master_chain["hue_shift"] = master_chain.get("hue_shift", 0.0) + macro_hue
            if master_chain:
                frame = apply_master(frame, master_chain)
            # C2: strobe_rate al final (aplica también en modo baked)
            strobe_rate = self.macros.get("strobe_rate", 0.0)
            if strobe_rate > 0:
                t_ms_b = int(t_s * 1000)
                half_period_ms = 500.0 / strobe_rate
                if (t_ms_b % (2 * half_period_ms)) >= half_period_ms:
                    frame[:] = 0
            # E1: fade de entrada del cue (multiplicar sobre el frame final, I4)
            if self._cue_fade_start_ms is not None:
                elapsed_b = t_ms_b - self._cue_fade_start_ms
                if elapsed_b >= self._cue_fade_duration_ms:
                    self._cue_fade_start_ms = None
                else:
                    pct_b = max(0.0, elapsed_b / self._cue_fade_duration_ms)
                    frame = (frame.astype(np.float32) * pct_b).clip(0, 255).astype(np.uint8)
            # E4: blackout duro (prioridad máxima, ambas rutas)
            if self.blackout_override:
                frame[:] = 0
            # J2: canales DMX no-pixel (baked path)
            self._compute_fixture_channels(int(t_s * 1000))
            # I1: captura de macros en vivo (baked path)
            self._maybe_record_macros(int(t_s * 1000))
            return frame

        from src.core.param_pipeline import resolve_params
        frame = np.zeros((NUM_BARS, LEDS, 3), dtype=np.uint8)
        t_ms = int(t_s * 1000)
        actx = self._get_audio_context(t_s)

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
            # F0.1: params efectivos vía pipeline (fast path sin stages = mismo dict)
            params = resolve_params(clip, t_ms, actx, self.param_stages,
                                    base_params=params)
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

        # D1: AutoVJ — evalúa reglas ANTES de compute_live_frame.
        # D2: si live_mode activo, pasa live_input como fuente de análisis
        # (misma interfaz: list_beats/list_downbeats/section_at/get_audio_context).
        if (self.autovj_engine.ruleset is not None
                and self.autovj_engine.ruleset.enabled):
            _analysis_src = (
                self.live_input
                if self._live_mode and self.live_input is not None
                else self.analysis
            )
            self.autovj_engine.evaluate(t_ms, actx, _analysis_src,
                                        self.live_engine)

        # C1: capa live — patterns lanzados + D1 patterns efímeros del AutoVJ.
        # Se mezcla encima del timeline con np.maximum (más brillante gana).
        # Orden fijo del pipeline: timeline_render → live+autovj → postfx/master.
        _autovj_pats = list(self.autovj_engine._ephemeral_patterns.values())
        live_frame = self.live_engine.compute_live_frame(
            t_ms,
            list(self.timeline.patterns) + _autovj_pats,
            self.library, self.param_stages, actx,
        )
        if live_frame.any():
            frame = np.maximum(frame, live_frame)

        # B2 + C2: postfx/master — pista por pista, luego master con hue_shift macro.
        # Orden fijo del pipeline: timeline_render → capa live (C1) → macros (C2) → postfx/master.
        mixer = self.timeline.mixer
        from src.core.postfx import apply_track_chain, apply_master
        if mixer:
            track_chains = mixer.get("tracks", {})
            if track_chains:
                for track_key, chain in track_chains.items():
                    try:
                        track_idx = int(track_key)
                        if 0 <= track_idx < NUM_BARS and chain:
                            frame[track_idx] = apply_track_chain(frame[track_idx], chain)
                    except (ValueError, TypeError):
                        pass
        # C2: hue_shift macro se suma al master (sin mutar el dict del timeline)
        master_chain = dict(mixer.get("master", {})) if mixer else {}
        macro_hue = self.macros.get("hue_shift", 0.0)
        if macro_hue:
            master_chain["hue_shift"] = master_chain.get("hue_shift", 0.0) + macro_hue
        if master_chain:
            frame = apply_master(frame, master_chain)

        # C2: strobe_rate — si >0, fase oscura → frame negro
        strobe_rate = self.macros.get("strobe_rate", 0.0)
        if strobe_rate > 0:
            half_period_ms = 500.0 / strobe_rate
            if (t_ms % (2 * half_period_ms)) >= half_period_ms:
                frame[:] = 0

        # E1: fade de entrada del cue (multiplicar sobre el frame final, I4)
        if self._cue_fade_start_ms is not None:
            elapsed = t_ms - self._cue_fade_start_ms
            if elapsed >= self._cue_fade_duration_ms:
                self._cue_fade_start_ms = None
            else:
                pct = max(0.0, elapsed / self._cue_fade_duration_ms)
                frame = (frame.astype(np.float32) * pct).clip(0, 255).astype(np.uint8)

        # E4/J4: identify fixture — color sobre las barras del fixture (posterior a postfx)
        # _identify values can be float (legacy) or {t_expires, color} (J4)
        if self._identify:
            import time as _time
            now = _time.monotonic()
            def _t_expires(v):
                return v if isinstance(v, float) else v.get("t_expires", now)
            expired = [fid for fid, v in self._identify.items() if now >= _t_expires(v)]
            for fid in expired:
                del self._identify[fid]
            if self._identify and self.fixture_rig is not None:
                for fid, v in list(self._identify.items()):
                    if isinstance(v, dict):
                        color = v.get("color", (255, 255, 255))
                    else:
                        color = (255, 255, 255)
                    for fx in getattr(self.fixture_rig, 'fixtures', []):
                        if getattr(fx, 'fixture_id', None) == fid:
                            bar = getattr(fx, 'legacy_bar_idx', None)
                            if bar is not None and 0 <= bar < NUM_BARS:
                                frame[bar, :] = color

        # E4: blackout duro — prioridad máxima (sobre identify, sobre todo)
        if self.blackout_override:
            frame[:] = 0

        # J2: renderizar canales DMX de fixtures no-pixel → _fixture_dmx_channels
        self._compute_fixture_channels(t_ms)

        # I1: captura de macros en vivo
        self._maybe_record_macros(t_ms)

        return frame

    def _compute_fixture_channels(self, t_ms: int) -> None:
        """J2: renderiza canales DMX para fixtures no-pixel (dimmer/rgb/mover/strobe).

        Resultado en self._fixture_dmx_channels: {universe: bytearray(512)}.
        Mapeo clip→fixture: track = fixture.universe - 1 (universo 1 → track 0).
        Mezcla LAST_WINS. Se llama al final de compute_frame (ambas rutas).
        """
        rig = getattr(self, "fixture_rig", None)
        if rig is None:
            return
        try:
            from src.core.dmx_render import render_fixture_channels, _PIXEL_KINDS, _effective_kind
        except ImportError:
            return

        channels: dict = {}
        for fx in rig.fixtures:
            profile = rig.get_profile(fx.profile_id)
            kind = _effective_kind(fx, profile)
            if kind in _PIXEL_KINDS:
                continue
            # track = universe - 1 (misma convención que las barras WLED)
            fx_track = fx.universe - 1
            fx_clips = [
                c for c in self.timeline.clips
                if c.track == fx_track
                and c.start_ms <= t_ms < c.end_ms
                and not getattr(c, "muted", False)
            ]
            ch_vals = render_fixture_channels(fx, profile, fx_clips, t_ms)
            if ch_vals:
                uni = fx.universe
                if uni not in channels:
                    channels[uni] = bytearray(512)
                buf = channels[uni]
                for ch_1based, val in ch_vals.items():
                    idx = fx.dmx_start - 1 + ch_1based - 1
                    if 0 <= idx < 512:
                        buf[idx] = val
        self._fixture_dmx_channels = channels

    # ── B4: autosave + versiones de show ─────────────────────────────────────

    def _autosave_dir(self) -> Path:
        return self.project.folder / "autosave"

    def autosave_now(self) -> Path:
        """Guarda el timeline actual en el directorio de autosave (atómico).

        Usa Timeline.save() existente → formato show.json v3 normal, restaurable
        con Timeline.load(). No reemplaza show.json (ese lo controla el usuario).
        """
        from datetime import datetime
        d = self._autosave_dir()
        d.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%dT%H%M%S')
        path = d / f"show_{ts}.json"
        self.timeline.save(path)
        self._last_saved_rev = self._rev
        self._rotate_autosaves()
        return path

    def _rotate_autosaves(self):
        """Mantiene solo los 20 autosaves más recientes (borra los más viejos)."""
        d = self._autosave_dir()
        if not d.is_dir():
            return
        files = sorted(d.glob("show_*.json"), key=lambda p: p.name)
        while len(files) > _AUTOSAVE_MAX:
            try:
                files.pop(0).unlink()
            except OSError:
                pass

    async def start_autosave_task(self):
        """Tarea asyncio: guarda cada LUCES_AUTOSAVE_INTERVAL segundos si hay cambios.

        No corre en el tick de 30 FPS — es I/O pesado. Se lanza desde web.py
        en startup como asyncio.create_task(session.start_autosave_task()).
        """
        import asyncio as _asyncio
        import os as _os
        interval = int(_os.environ.get("LUCES_AUTOSAVE_INTERVAL", "60"))
        while True:
            await _asyncio.sleep(interval)
            if self._rev != self._last_saved_rev:
                try:
                    path = self.autosave_now()
                    print(f"[autosave] {path.name}")
                except Exception as e:
                    print(f"[autosave] error: {e}")

    def check_autosave_at_startup(self) -> Optional[dict]:
        """Si el autosave más reciente es más nuevo que show.json, devuelve el evento.

        El frontend muestra un banner con "Restaurar / Descartar". Solo se emite
        UNA vez por arranque (_autosave_banner_shown evita repetición).
        La comparación es por mtime — rápida y sin leer el contenido.
        """
        if self._autosave_banner_shown:
            return None
        d = self._autosave_dir()
        if not d.is_dir():
            return None
        files = sorted(d.glob("show_*.json"), key=lambda p: p.stat().st_mtime)
        if not files:
            return None
        latest = files[-1]
        show_file = self.project.show_file
        if not show_file.is_file():
            return None
        try:
            if latest.stat().st_mtime > show_file.stat().st_mtime:
                self._autosave_banner_shown = True
                ts = latest.stem[5:]  # "show_YYYYMMDDTHHMMSS" → "YYYYMMDDTHHMMSS"
                return {
                    "type": "autosave_available",
                    "path": f"{self.project.slug}/autosave/{latest.name}",
                    "ts": ts,
                    "filename": latest.name,
                }
        except OSError:
            pass
        return None

    # ── H3: multi-show quick-switch ───────────────────────────────────────────

    async def switch_project(self, new_slug: str) -> None:
        """Cambia el proyecto activo sin reiniciar el server.

        1. Para el playback (audio + live).
        2. Guarda el estado actual (autosave inmediato si hay cambios).
        3. Carga el nuevo proyecto (timeline, audio, analysis).
        4. Resetea el playback a t=0.
        5. Emite 'project_changed' al stream con el nuevo nombre.

        Lanza ValueError si new_slug no existe. Si algo falla a mitad del
        switch, la sesión puede quedar en estado parcial (el servidor sigue
        respondiendo pero el show puede ser inconsistente — recargar el server).
        """
        import asyncio

        # Verificar que el slug exista ANTES de empezar a desmontar el proyecto actual
        new_project = self.pm.open_project(new_slug)
        if new_project is None:
            raise ValueError(f"Proyecto no encontrado: {new_slug!r}")

        # 1. Parar playback y live engine
        try:
            self.audio.stop()
        except Exception:
            pass
        try:
            self.live_engine.stop_all()
        except Exception:
            pass

        # 2. Guardar estado del proyecto actual si hay cambios
        if self._rev != self._last_saved_rev:
            try:
                self.autosave_now()
            except Exception as e:
                print(f"[switch_project] autosave fallido: {e}")

        # 3. Cargar nuevo proyecto
        self.project = new_project
        self._project = new_project
        self.pm._current = new_project

        audio_file = Path(new_project.audio_path)
        show_file = new_project.show_file
        analysis_slug = new_project.analysis_slug

        # Timeline
        dur_ms = self.timeline.duration_ms  # fallback si analysis falla
        try:
            from src.analysis.analyzer_service import AnalysisService, default_service, ANALIZADAS_DIR
            if analysis_slug:
                self.analysis = AnalysisService(ANALIZADAS_DIR / analysis_slug)
            else:
                self.analysis = default_service()
            summary = self.analysis.summary
            self.bpm = float(summary.get('bpm') or 128.0)
            dur_ms = int(float(summary.get('duration_s') or 165.0) * 1000)
        except Exception as e:
            print(f"[switch_project] analysis fallido: {e}")

        loaded = Timeline.load(show_file) if show_file.is_file() else Timeline.load()
        loaded.duration_ms = dur_ms
        if not getattr(loaded, 'groups', None):
            loaded.groups = make_default_groups()
        self.timeline = loaded

        # Presets del nuevo proyecto
        try:
            from server.presets import PresetBank
            self.presets = PresetBank(self.library, self.channel_lib,
                                      project_file=new_project.folder / "presets.json")
        except Exception:
            pass

        # AutoVJ del nuevo proyecto
        try:
            _autovj_path = new_project.folder / "autovj.json"
            if _autovj_path.is_file():
                self.autovj_engine.load(_autovj_path)
        except Exception:
            pass

        # 4. Resetear estado de playback / render
        self.baked_frames = None
        self.baked_hash = None
        self.render_in_progress = False
        self.render_pct = 0.0
        self._clip_bucket_index = {}
        self._clip_bucket_index_n = -1
        self._pattern_rev = 0
        self._pattern_expanded = []
        self._pattern_expanded_rev = -1
        self._last_saved_rev = 0
        self._autosave_banner_shown = False
        self.blackout_override = False
        self._identify = {}
        self._test_universes = {}
        self._cue_fade_start_ms = None
        self._cue_fade_duration_ms = 0.0
        self._cue_fade_from_master = 1.0
        self._cue_last_fade_pct = 1.0
        self.live_engine.stop_all()
        self._rev += 1

        # Audio
        try:
            if audio_file.is_file():
                self.audio.load(audio_file, duration=dur_ms / 1000.0)
            else:
                self.audio.duration = dur_ms / 1000.0
        except Exception as e:
            print(f"[switch_project] audio fallido: {e}")

        # 5. Emitir evento al stream
        if self.hub is not None:
            try:
                await self.hub.broadcast({
                    "type": "project_changed",
                    "slug": new_slug,
                    "name": new_project.name,
                    "clips": len(self.timeline.clips),
                    "duration_ms": self.timeline.duration_ms,
                })
            except Exception as e:
                print(f"[switch_project] broadcast fallido: {e}")

        print(f"[switch_project] → {new_project.name!r} ({new_slug}), "
              f"{len(self.timeline.clips)} clips")


_AUTOSAVE_MAX = 20
# (F0 + B2 + B4 aplicadas — ROADMAP v2)
