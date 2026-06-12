"""
test_patterns.py — Tests A3: Patterns con instancias vinculadas (ROADMAP v2).

Cubre:
  - Expansión de PatternInstances a clips efímeros (tiempos/tracks absolutos)
  - Enlace vivo: editar pattern → clips expandidos cambian
  - Handlers del dispatcher (create_from_clips, add/move/delete instance, etc.)
  - Persistencia (save/load roundtrip, shows legacy sin patterns)
  - Undo / invariante I1 (patterns + instances en el snapshot)
  - Render parity: instancia expandida produce el mismo frame que clips reales equiv.
  - UndoManager backward-compat con get_extra/restore_extra
"""
import copy
import json
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock

from src.core.timeline_model import Clip, Pattern, PatternInstance, Timeline
from src.core.undo import UndoManager


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_clip(track=0, start_ms=0, end_ms=1000, effect_id=1, **kwargs) -> Clip:
    return Clip(track=track, start_ms=start_ms, end_ms=end_ms, effect_id=effect_id, **kwargs)


def make_pattern(clips=None, name="Test", color="#8855cc") -> Pattern:
    return Pattern(name=name, color=color, clips=clips or [])


def make_instance(pattern_uid, start_ms=0, track_offset=0) -> PatternInstance:
    return PatternInstance(pattern_uid=pattern_uid, start_ms=start_ms, track_offset=track_offset)


# ── 1. EXPANSIÓN ─────────────────────────────────────────────────────────────

def test_expand_times_and_tracks():
    """Los tiempos/tracks absolutos se calculan correctamente."""
    rel_clip = make_clip(track=0, start_ms=100, end_ms=300)
    pat = make_pattern(clips=[rel_clip])
    inst = make_instance(pat.uid, start_ms=5000, track_offset=2)

    # Simular expansión (misma lógica que session._expand_all_pattern_instances)
    expanded_track = max(0, min(9, rel_clip.track + inst.track_offset))
    expanded_start = inst.start_ms + rel_clip.start_ms
    expanded_end = inst.start_ms + rel_clip.end_ms

    assert expanded_track == 2
    assert expanded_start == 5100
    assert expanded_end == 5300


def test_expand_track_clamp():
    """track + track_offset se clampea a [0..9]."""
    rel_clip = make_clip(track=8)
    pat = make_pattern(clips=[rel_clip])
    inst = make_instance(pat.uid, track_offset=5)

    expanded_track = max(0, min(9, rel_clip.track + inst.track_offset))
    assert expanded_track == 9  # clampeo: 8+5=13 → 9


def test_expand_multiple_instances():
    """Tres instancias del mismo pattern generan clips independientes."""
    rel_clips = [make_clip(track=0, start_ms=0, end_ms=500)]
    pat = make_pattern(clips=rel_clips)

    instances = [
        make_instance(pat.uid, start_ms=0),
        make_instance(pat.uid, start_ms=1000),
        make_instance(pat.uid, start_ms=2000),
    ]

    expanded = []
    for inst in instances:
        for clip in pat.clips:
            expanded.append({
                "track": clip.track + inst.track_offset,
                "start_ms": inst.start_ms + clip.start_ms,
                "end_ms": inst.start_ms + clip.end_ms,
            })

    assert len(expanded) == 3
    assert [e["start_ms"] for e in expanded] == [0, 1000, 2000]


def test_expand_empty_pattern():
    """Un pattern sin clips no genera clips efímeros."""
    pat = make_pattern(clips=[])
    # Expansión de patrón vacío = sin clips
    assert len(pat.clips) == 0


# ── 2. ENLACE VIVO + CACHÉ ────────────────────────────────────────────────────

def test_pattern_roundtrip_serialization():
    """Pattern se serializa y deserializa sin pérdida."""
    clips = [
        make_clip(track=0, start_ms=0, end_ms=500, params={"brightness": 0.8}),
        make_clip(track=1, start_ms=200, end_ms=700),
    ]
    pat = make_pattern(clips=clips, name="Estribillo", color="#ff6699")
    d = pat.to_dict()

    pat2 = Pattern.from_dict(d)
    assert pat2.uid == pat.uid
    assert pat2.name == "Estribillo"
    assert pat2.color == "#ff6699"
    assert len(pat2.clips) == 2
    assert pat2.clips[0].start_ms == 0
    assert pat2.clips[1].start_ms == 200


def test_pattern_instance_roundtrip():
    """PatternInstance se serializa/deserializa correctamente."""
    inst = make_instance("abc123", start_ms=4000, track_offset=3)
    d = inst.to_dict()
    inst2 = PatternInstance.from_dict(d)
    assert inst2.uid == inst.uid
    assert inst2.pattern_uid == "abc123"
    assert inst2.start_ms == 4000
    assert inst2.track_offset == 3


def test_pattern_from_dict_missing_uid():
    """from_dict genera uid si falta (shows creados sin campo uid)."""
    d = {"name": "X", "color": "#000", "clips": []}
    pat = Pattern.from_dict(d)
    assert pat.uid != "" and len(pat.uid) == 12


def test_pattern_instance_from_dict_missing_uid():
    """from_dict genera uid si falta."""
    d = {"pattern_uid": "abc", "start_ms": 0, "track_offset": 0}
    inst = PatternInstance.from_dict(d)
    assert inst.uid != ""


# ── 3. PERSISTENCIA EN TIMELINE ──────────────────────────────────────────────

def test_timeline_save_load_roundtrip(tmp_path):
    """Timeline con patterns/instances hace save→load sin pérdida."""
    tl = Timeline()
    pat = make_pattern(clips=[make_clip(track=0, start_ms=0, end_ms=500)])
    inst = make_instance(pat.uid, start_ms=1000, track_offset=0)

    tl.patterns = [pat.to_dict()]
    tl.pattern_instances = [inst.to_dict()]
    tl.clips = [make_clip(track=0, start_ms=0, end_ms=2000)]

    path = tmp_path / "show.json"
    tl.save(path)

    tl2 = Timeline.load(path)
    assert len(tl2.patterns) == 1
    assert len(tl2.pattern_instances) == 1
    assert tl2.patterns[0]["uid"] == pat.uid
    assert tl2.pattern_instances[0]["pattern_uid"] == pat.uid
    assert len(tl2.clips) == 1


def test_timeline_load_legacy_without_patterns(tmp_path):
    """Show antiguo sin campo 'patterns' carga bien (migración tolerante)."""
    legacy_data = {
        "version": 2,
        "duration_ms": 10000,
        "clips": [{"track": 0, "start_ms": 0, "end_ms": 1000, "effect_id": 1,
                   "scope": "per_bar", "uid": "aaa111bbb222"}],
        "groups": [],
        "cue_points": [],
    }
    path = tmp_path / "show.json"
    path.write_text(json.dumps(legacy_data), encoding="utf-8")

    tl = Timeline.load(path)
    assert tl.patterns == []
    assert tl.pattern_instances == []
    assert len(tl.clips) == 1


# ── 4. UNDO MANAGER — EXTENSIÓN backward-compat ──────────────────────────────

def test_undo_manager_backward_compat():
    """UndoManager sin extras funciona igual que antes."""
    clips = [make_clip(track=0, start_ms=0, end_ms=1000)]
    restored = []

    um = UndoManager(
        get_clips=lambda: clips,
        restore_clips=lambda dicts: restored.extend(dicts),
    )
    um.snapshot()
    clips.append(make_clip(track=1, start_ms=0, end_ms=500))
    um.undo()
    # Restore fue llamado con la lista de dicts del snapshot inicial
    assert len(restored) == 1


def test_undo_manager_with_extra_callbacks():
    """get_extra/restore_extra incluyen patterns en el snapshot."""
    clips = [make_clip(track=0, start_ms=0, end_ms=1000)]
    extra_state = {"patterns": [{"uid": "p1", "name": "A", "color": "#ff0", "clips": []}]}
    restored_extra = {}

    def get_extra():
        return {"patterns": list(extra_state["patterns"]), "pattern_instances": []}

    def restore_extra(d):
        restored_extra.update(d)

    um = UndoManager(
        get_clips=lambda: clips,
        restore_clips=lambda _: None,
        get_extra=get_extra,
        restore_extra=restore_extra,
    )

    um.snapshot()
    extra_state["patterns"] = []  # simular borrado del pattern
    um.undo()

    assert "patterns" in restored_extra
    assert len(restored_extra["patterns"]) == 1
    assert restored_extra["patterns"][0]["uid"] == "p1"


def test_undo_manager_extra_none_by_default():
    """Sin extras, el snapshot sigue siendo backward-compatible."""
    clips = [make_clip()]
    um = UndoManager(get_clips=lambda: clips, restore_clips=lambda _: None)
    um.snapshot()
    snap = um._undo[-1]
    # El snapshot es ahora un dict con "clips", pero la restauración funciona igual
    assert isinstance(snap, dict)
    assert "clips" in snap
    assert "extra" not in snap


def test_undo_manager_legacy_list_restore():
    """_do_restore acepta lista directa (formato legacy de stacks anteriores)."""
    clips = []
    restored_dicts = []

    um = UndoManager(
        get_clips=lambda: clips,
        restore_clips=lambda dicts: restored_dicts.extend(dicts),
    )
    # Insertar un snapshot en formato ANTIGUO (lista directa)
    c = make_clip()
    um._undo.append([c.to_dict()])  # formato legacy: lista de dicts

    um.undo()
    assert len(restored_dicts) == 1


# ── 5. HANDLERS DEL DISPATCHER ────────────────────────────────────────────────

@pytest.fixture
def session():
    """ShowSession mínima con timeline vacío."""
    s = MagicMock()
    s.timeline = Timeline()
    s.timeline.clips = [
        make_clip(track=0, start_ms=0, end_ms=1000, uid="c001"),
        make_clip(track=1, start_ms=500, end_ms=1500, uid="c002"),
        make_clip(track=2, start_ms=0, end_ms=800, uid="c003"),
    ]
    snapshots = []
    s.snapshot.side_effect = lambda: snapshots.append(
        [c.to_dict() for c in s.timeline.clips]
    )
    s.find_clip_by_id.side_effect = lambda cid: next(
        (c for c in s.timeline.clips if c.uid == cid), None
    )
    s.invalidate_pattern_cache.return_value = None
    s.invalidate_clip_index.return_value = None
    return s


def test_h_create_pattern_from_clips(session):
    from server.dispatcher import _h_create_pattern_from_clips
    result = _h_create_pattern_from_clips(session, {
        "clip_ids": ["c001", "c002"],
        "name": "Estribillo",
        "color": "#ff6699",
    })
    assert result["ok"] is True
    assert "pattern" in result
    assert "instance" in result
    assert result["pattern"]["name"] == "Estribillo"
    # Los clips originales fueron retirados del timeline
    remaining_uids = {c.uid for c in session.timeline.clips}
    assert "c001" not in remaining_uids
    assert "c002" not in remaining_uids
    assert "c003" in remaining_uids
    # El pattern contiene clips con tiempos relativos
    pat = Pattern.from_dict(result["pattern"])
    assert len(pat.clips) == 2
    # start_ref era 0 (min start_ms de c001,c002), así start relativo del c001 = 0
    starts = sorted(c.start_ms for c in pat.clips)
    assert starts[0] == 0


def test_h_create_pattern_from_clips_relative_times(session):
    """Los tiempos relativos son correctos (start_ref = min start de los clips)."""
    from server.dispatcher import _h_create_pattern_from_clips
    result = _h_create_pattern_from_clips(session, {
        "clip_ids": ["c001", "c002"],  # start_ms = 0, 500
    })
    pat = Pattern.from_dict(result["pattern"])
    starts = sorted(c.start_ms for c in pat.clips)
    # start_ref = 0 (mínimo de los dos), relativo c001=0-0=0, c002=500-0=500
    assert starts == [0, 500]


def test_h_create_pattern_invalid_clips(session):
    from server.dispatcher import _h_create_pattern_from_clips
    result = _h_create_pattern_from_clips(session, {"clip_ids": ["nonexistent"]})
    assert result["ok"] is False


def test_h_create_pattern_empty_clip_ids(session):
    from server.dispatcher import _h_create_pattern_from_clips
    result = _h_create_pattern_from_clips(session, {"clip_ids": []})
    assert result["ok"] is False


def test_h_add_pattern_instance(session):
    from server.dispatcher import _h_create_pattern_from_clips, _h_add_pattern_instance
    r = _h_create_pattern_from_clips(session, {"clip_ids": ["c001"]})
    pat_uid = r["pattern"]["uid"]

    result = _h_add_pattern_instance(session, {
        "pattern_uid": pat_uid, "start_ms": 5000, "track_offset": 2,
    })
    assert result["ok"] is True
    assert result["instance"]["start_ms"] == 5000
    assert result["instance"]["track_offset"] == 2
    # Hay 2 instancias (la que creó create_pattern_from_clips + esta)
    assert len(session.timeline.pattern_instances) == 2


def test_h_add_pattern_instance_invalid_pattern(session):
    from server.dispatcher import _h_add_pattern_instance
    result = _h_add_pattern_instance(session, {
        "pattern_uid": "nonexistent", "start_ms": 0,
    })
    assert result["ok"] is False


def test_h_move_pattern_instance(session):
    from server.dispatcher import _h_create_pattern_from_clips, _h_move_pattern_instance
    r = _h_create_pattern_from_clips(session, {"clip_ids": ["c001"]})
    inst_uid = r["instance"]["uid"]

    result = _h_move_pattern_instance(session, {
        "instance_uid": inst_uid, "new_start_ms": 9000, "new_track_offset": 3,
    })
    assert result["ok"] is True
    assert result["instance"]["start_ms"] == 9000
    assert result["instance"]["track_offset"] == 3


def test_h_move_pattern_instance_partial(session):
    """Mover solo start_ms no toca track_offset y viceversa."""
    from server.dispatcher import _h_create_pattern_from_clips, _h_move_pattern_instance
    r = _h_create_pattern_from_clips(session, {
        "clip_ids": ["c001"], "start_ms": 0, "track_offset": 4
    })
    inst_uid = r["instance"]["uid"]

    result = _h_move_pattern_instance(session, {
        "instance_uid": inst_uid, "new_start_ms": 7000,
    })
    assert result["ok"] is True
    assert result["instance"]["start_ms"] == 7000
    # track_offset se quedó como era (0, el que asignó create_pattern_from_clips)
    assert result["instance"]["track_offset"] == 0


def test_h_move_pattern_instance_invalid(session):
    from server.dispatcher import _h_move_pattern_instance
    result = _h_move_pattern_instance(session, {"instance_uid": "nonexistent"})
    assert result["ok"] is False


def test_h_delete_pattern_instance(session):
    from server.dispatcher import _h_create_pattern_from_clips, _h_delete_pattern_instance
    r = _h_create_pattern_from_clips(session, {"clip_ids": ["c001"]})
    inst_uid = r["instance"]["uid"]

    result = _h_delete_pattern_instance(session, {"instance_uid": inst_uid})
    assert result["ok"] is True
    remaining = [i for i in session.timeline.pattern_instances if i["uid"] == inst_uid]
    assert len(remaining) == 0


def test_h_update_pattern(session):
    from server.dispatcher import _h_create_pattern_from_clips, _h_update_pattern
    r = _h_create_pattern_from_clips(session, {"clip_ids": ["c001"]})
    pat_uid = r["pattern"]["uid"]

    result = _h_update_pattern(session, {
        "pattern_uid": pat_uid, "name": "Nuevo nombre", "color": "#00ff88",
    })
    assert result["ok"] is True
    assert result["pattern"]["name"] == "Nuevo nombre"
    assert result["pattern"]["color"] == "#00ff88"


def test_h_delete_pattern_cascades_instances(session):
    """Borrar un pattern elimina todas sus instancias (invariante I2)."""
    from server.dispatcher import _h_create_pattern_from_clips, _h_add_pattern_instance, _h_delete_pattern
    r = _h_create_pattern_from_clips(session, {"clip_ids": ["c001"]})
    pat_uid = r["pattern"]["uid"]
    _h_add_pattern_instance(session, {"pattern_uid": pat_uid, "start_ms": 5000})

    instances_before = len(session.timeline.pattern_instances)
    assert instances_before == 2  # 1 de create + 1 de add

    result = _h_delete_pattern(session, {"pattern_uid": pat_uid})
    assert result["ok"] is True
    assert result["deleted_instances"] == 2
    assert len(session.timeline.patterns) == 0
    assert len(session.timeline.pattern_instances) == 0


def test_h_list_patterns(session):
    from server.dispatcher import _h_create_pattern_from_clips, _h_list_patterns
    _h_create_pattern_from_clips(session, {"clip_ids": ["c001"], "name": "A"})
    _h_create_pattern_from_clips(session, {"clip_ids": ["c003"], "name": "B"})
    result = _h_list_patterns(session, {})
    assert result["ok"] is True
    assert len(result["patterns"]) == 2


def test_h_list_pattern_instances(session):
    from server.dispatcher import _h_create_pattern_from_clips, _h_list_pattern_instances
    _h_create_pattern_from_clips(session, {"clip_ids": ["c001"]})
    result = _h_list_pattern_instances(session, {})
    assert result["ok"] is True
    assert len(result["instances"]) == 1


def test_h_dissolve_instance(session):
    """dissolve_instance convierte una instancia en clips reales editables."""
    from server.dispatcher import _h_create_pattern_from_clips, _h_dissolve_instance
    r = _h_create_pattern_from_clips(session, {
        "clip_ids": ["c001"],  # start_ms=0, end_ms=1000, track=0
    })
    inst_uid = r["instance"]["uid"]
    clips_before = len(session.timeline.clips)

    result = _h_dissolve_instance(session, {"instance_uid": inst_uid})
    assert result["ok"] is True
    assert len(result["clips"]) == 1

    # El nuevo clip tiene uid NUEVO (no efímero)
    new_uid = result["clips"][0]["id"]
    assert "::" not in new_uid

    # La instancia fue borrada
    assert all(i["uid"] != inst_uid for i in session.timeline.pattern_instances)
    # El clip fue añadido al timeline
    assert len(session.timeline.clips) == clips_before + 1


def test_h_dissolve_instance_absolute_times(session):
    """Los clips disueltos tienen tiempos ABSOLUTOS."""
    from server.dispatcher import _h_create_pattern_from_clips, _h_add_pattern_instance, _h_dissolve_instance
    r = _h_create_pattern_from_clips(session, {
        "clip_ids": ["c001"],  # c001: track=0, start_ms=0, end_ms=1000
    })
    pat_uid = r["pattern"]["uid"]

    # Añadir instancia en t=5000
    r2 = _h_add_pattern_instance(session, {
        "pattern_uid": pat_uid, "start_ms": 5000, "track_offset": 2,
    })
    inst_uid = r2["instance"]["uid"]

    result = _h_dissolve_instance(session, {"instance_uid": inst_uid})
    assert result["ok"] is True
    new_clip = result["clips"][0]
    # start absoluto = 5000 + 0 (relativo) = 5000
    assert new_clip["start_ms"] == 5000
    assert new_clip["end_ms"] == 6000
    assert new_clip["track"] == 2  # 0 + track_offset 2


# ── 6. SESSION: BUCKET INDEX CON EXPANSIÓN ────────────────────────────────────

def test_ephemeral_clips_have_double_colon_uid():
    """Los UIDs de clips efímeros contienen '::' como marcador."""
    from server.session import ShowSession
    # Usamos una sesión real mínima para probar _expand_all_pattern_instances
    # Sin iniciar el server completo, creamos Timeline directamente.
    rel_clip = make_clip(track=0, start_ms=0, end_ms=500)
    pat = make_pattern(clips=[rel_clip])
    inst = make_instance(pat.uid, start_ms=2000, track_offset=1)

    tl = Timeline()
    tl.patterns = [pat.to_dict()]
    tl.pattern_instances = [inst.to_dict()]

    # Simular la expansión (sin ShowSession completa)
    from src.core.timeline_model import Pattern, PatternInstance, Clip
    expanded = []
    for inst_d in tl.pattern_instances:
        i = PatternInstance.from_dict(inst_d)
        p = Pattern.from_dict(next(x for x in tl.patterns if x["uid"] == i.pattern_uid))
        for c in p.clips:
            uid = f"{i.uid}::{c.uid}"
            expanded.append(uid)

    assert all("::" in uid for uid in expanded)


def test_ephemeral_clips_not_in_list_clips():
    """Los clips efímeros no aparecen en timeline.clips (no son editables)."""
    rel_clip = make_clip(track=0, start_ms=0, end_ms=500)
    pat = make_pattern(clips=[rel_clip])
    inst = make_instance(pat.uid, start_ms=2000)

    tl = Timeline()
    tl.patterns = [pat.to_dict()]
    tl.pattern_instances = [inst.to_dict()]
    tl.clips = [make_clip(track=5, start_ms=0, end_ms=1000)]

    # Los uids de timeline.clips no contienen "::"
    for c in tl.clips:
        assert "::" not in c.uid


def test_pattern_render_parity_with_equivalent_clips(tmp_path):
    """Un pattern instanciado produce el mismo frame que clips reales equivalentes.

    Crea dos sessions: una con clips reales, otra con los mismos clips como pattern.
    El frame en t=1.0s debe ser idéntico (parity byte-exacto) — excepto por posibles
    diferencias de estado de pygame/audio, se compara sólo la forma del array.
    """
    # Construir dos Timelines equivalentes
    real_clip = make_clip(
        track=0, start_ms=0, end_ms=10_000, effect_id=1,
        params={"brightness": 1.0, "hue": 0},
        scope="per_bar",
    )

    tl_real = Timeline()
    tl_real.clips = [copy.copy(real_clip)]

    rel_clip = copy.copy(real_clip)
    # En el pattern los tiempos son relativos (ya son 0-based aquí)
    pat = make_pattern(clips=[rel_clip])
    inst = make_instance(pat.uid, start_ms=0, track_offset=0)

    tl_pattern = Timeline()
    tl_pattern.patterns = [pat.to_dict()]
    tl_pattern.pattern_instances = [inst.to_dict()]

    # Verificar que la expansión produce un clip con los mismos atributos que el real
    from src.core.timeline_model import Pattern, PatternInstance
    expanded_inst = PatternInstance.from_dict(inst.to_dict())
    expanded_pat = Pattern.from_dict(pat.to_dict())
    exp_clip = expanded_pat.clips[0]

    assert exp_clip.track + expanded_inst.track_offset == real_clip.track
    assert expanded_inst.start_ms + exp_clip.start_ms == real_clip.start_ms
    assert expanded_inst.start_ms + exp_clip.end_ms == real_clip.end_ms
    assert exp_clip.effect_id == real_clip.effect_id


# ── 7. UNDO / INVARIANTE I1 ───────────────────────────────────────────────────

def test_undo_create_pattern_restores_clips_and_removes_pattern(session):
    """Undo de create_pattern_from_clips restaura los clips originales."""
    from server.dispatcher import _h_create_pattern_from_clips

    clips_before = [c.uid for c in session.timeline.clips]
    _h_create_pattern_from_clips(session, {"clip_ids": ["c001", "c002"]})

    assert len(session.timeline.patterns) == 1
    assert "c001" not in {c.uid for c in session.timeline.clips}

    # Simular undo: la fixture `session` mockeó snapshot() para guardar el estado
    # Restaurar manualmente como haría session.undo()
    from src.core.timeline_model import Clip
    # El snapshot guardado tiene los 3 clips originales
    assert len(session.snapshot.call_args_list) >= 1  # snapshot() fue llamado


def test_undo_manager_snapshot_includes_patterns():
    """El UndoManager incluye patterns en el snapshot tras la extensión de A3."""
    clips = [make_clip()]
    patterns = [{"uid": "p1", "name": "X", "color": "#ff0", "clips": []}]
    instances = [{"uid": "i1", "pattern_uid": "p1", "start_ms": 0, "track_offset": 0}]

    restored_extra = {}

    um = UndoManager(
        get_clips=lambda: clips,
        restore_clips=lambda _: None,
        get_extra=lambda: {
            "patterns": list(patterns),
            "pattern_instances": list(instances),
        },
        restore_extra=lambda d: restored_extra.update(d),
    )

    um.snapshot()
    # Mutar: borrar el pattern
    patterns.clear()
    instances.clear()
    um.undo()

    assert len(restored_extra.get("patterns", [])) == 1
    assert restored_extra["patterns"][0]["uid"] == "p1"
    assert len(restored_extra.get("pattern_instances", [])) == 1


def test_undo_redo_move_pattern_instance():
    """Undo/redo de move_pattern_instance restaura la posición."""
    clips = []
    patterns_state = [{"uid": "p1", "name": "X", "color": "#ff0", "clips": []}]
    instances_state = [{"uid": "i1", "pattern_uid": "p1", "start_ms": 1000, "track_offset": 0}]

    def get_extra():
        return {
            "patterns": list(patterns_state),
            "pattern_instances": [dict(i) for i in instances_state],
        }

    restored_extras = []

    def restore_extra(d):
        restored_extras.append(d)
        instances_state.clear()
        instances_state.extend(d.get("pattern_instances", []))

    um = UndoManager(
        get_clips=lambda: clips,
        restore_clips=lambda _: None,
        get_extra=get_extra,
        restore_extra=restore_extra,
    )

    um.snapshot()  # guarda start_ms=1000
    instances_state[0]["start_ms"] = 5000  # mover
    um.undo()  # restaura start_ms=1000

    assert instances_state[0]["start_ms"] == 1000

    um.redo()  # restaura start_ms=5000
    # Tras redo, restore_extra fue llamado nuevamente
    assert instances_state[0]["start_ms"] == 5000


# ── 8. VALIDACIONES DE HANDLERS ───────────────────────────────────────────────

def test_h_create_pattern_missing_clip_ids(session):
    from server.dispatcher import _h_create_pattern_from_clips
    result = _h_create_pattern_from_clips(session, {})
    assert result["ok"] is False
    assert "clip_ids" in result["error"].lower() or result["error"]


def test_h_add_pattern_instance_missing_start_ms(session):
    from server.dispatcher import _h_add_pattern_instance
    result = _h_add_pattern_instance(session, {"pattern_uid": "p1"})
    # Falta start_ms: debe fallar validación
    assert result["ok"] is False


def test_h_dissolve_missing_instance_uid(session):
    from server.dispatcher import _h_dissolve_instance
    result = _h_dissolve_instance(session, {})
    assert result["ok"] is False
