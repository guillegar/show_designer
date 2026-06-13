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
        self.param_stages: list = [
            ModulationStage(),
            AutomationStage(get_automation_lanes=self._get_automation_lanes),
            MicroEventStage(),
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
        """Restaura patterns, pattern_instances y mixer desde un snapshot de undo (I1)."""
        self.timeline.patterns = list(extra.get("patterns", []))
        self.timeline.pattern_instances = list(extra.get("pattern_instances", []))
        if "mixer" in extra:
            self.timeline.mixer = dict(extra["mixer"])
        self._pattern_rev += 1
        self._clip_bucket_index_n = -1

    def snapshot(self):
        self.undo_manager.snapshot()

    def undo(self) -> bool:
        return self.undo_manager.undo()

    def redo(self) -> bool:
        return self.undo_manager.redo()

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

        Delegado en AnalysisService.get_audio_context: tras la Fase 5 de la
        auditoría cuesta UN searchsorted + lerp vectorizado por frame — barato.
        Fallback al contexto estático SOLO si el proyecto no tiene timeseries
        (sin esto, la modulación de A1 vería señales congeladas y las luces
        no reaccionarían a la música — ver ANALYSIS/ROADMAP F0.0).
        """
        svc = self.analysis
        try:
            if svc is not None and getattr(svc, 'has_timeseries', False):
                return svc.get_audio_context(t_s)
        except Exception as e:
            import logging
            from src.log import get_logger, log_throttled
            log_throttled(get_logger(__name__), logging.WARNING,
                          'session.actx', f"get_audio_context({t_s:.2f}) error: {e}")
        return self._cached_actx

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
            # Postfx/master (B2) sobre el frame bakeado
            mixer = self.timeline.mixer
            if mixer:
                from src.core.postfx import apply_track_chain, apply_master
                track_chains = mixer.get("tracks", {})
                if track_chains:
                    for track_key, chain in track_chains.items():
                        try:
                            track_idx = int(track_key)
                            if 0 <= track_idx < NUM_BARS and chain:
                                frame[track_idx] = apply_track_chain(frame[track_idx], chain)
                        except (ValueError, TypeError):
                            pass
                master_chain = mixer.get("master", {})
                if master_chain:
                    frame = apply_master(frame, master_chain)
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

        # B2: cadena postfx del mixer — pista por pista, luego master global.
        # Orden fijo del pipeline: timeline_render → [capa live C1] → postfx/master.
        mixer = self.timeline.mixer
        if mixer:
            from src.core.postfx import apply_track_chain, apply_master
            track_chains = mixer.get("tracks", {})
            if track_chains:
                for track_key, chain in track_chains.items():
                    try:
                        track_idx = int(track_key)
                        if 0 <= track_idx < NUM_BARS and chain:
                            frame[track_idx] = apply_track_chain(frame[track_idx], chain)
                    except (ValueError, TypeError):
                        pass
            master_chain = mixer.get("master", {})
            if master_chain:
                frame = apply_master(frame, master_chain)

        return frame

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


_AUTOSAVE_MAX = 20
# (F0 + B2 + B4 aplicadas — ROADMAP v2)
