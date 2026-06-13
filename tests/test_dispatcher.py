"""
test_dispatcher.py — Fase 2 de la migración web.

Verifica que el Dispatcher Qt-free (server/dispatcher.py) sirve el protocolo
JSON-RPC del bridge contra un ShowSession headless, sin Qt.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.session import ShowSession  # noqa: E402
from server.dispatcher import Dispatcher  # noqa: E402


@pytest.fixture(scope="module")
def disp():
    return Dispatcher(ShowSession())


def test_methods_available(disp):
    # Debe exponer la batería completa de endpoints (sin los debug_*)
    assert len(disp.methods) >= 45
    for m in ("get_state", "list_clips", "add_clip", "list_fixtures",
              "list_effects", "analyzer_summary"):
        assert m in disp.methods


def test_get_state(disp):
    st = disp.call("get_state")
    assert "time_sec" in st
    assert st["clip_count"] > 0
    assert st["duration_sec"] > 100


def test_list_clips(disp):
    r = disp.call("list_clips")
    assert r["count"] > 0
    assert "clips" in r


def test_list_fixtures(disp):
    r = disp.call("list_fixtures")
    assert r["rig_loaded"] is True
    assert r["count"] > 0


def test_list_effects(disp):
    r = disp.call("list_effects")
    assert r["count"] > 0


def test_analyzer_summary_and_sections(disp):
    s = disp.call("analyzer_summary")
    assert s["available"] is True
    assert s["summary"]["bpm"]
    sec = disp.call("analyzer_list_sections")
    assert "sections" in sec


def test_add_and_delete_clip_roundtrip(disp):
    before = disp.call("list_clips")["count"]
    add = disp.call("add_clip", {"track": 0, "start_ms": 1000, "end_ms": 3000,
                                 "effect_id": 0, "scope": "per_bar"})
    assert add["ok"] is True
    after = disp.call("list_clips")["count"]
    assert after == before + 1
    # El nuevo clip debe renderizar en compute_frame (cache invalidada)
    f = disp.session.compute_frame(2.0)  # t=2s, dentro del clip nuevo
    assert int(f.max()) >= 0  # no peta (la invalidación del bucket funciona)
    cid = add["clip"]["id"]
    dele = disp.call("delete_clip", {"clip_id": cid})
    assert dele["ok"] is True
    assert disp.call("list_clips")["count"] == before


def test_move_clip(disp):
    add = disp.call("add_clip", {"track": 1, "start_ms": 5000, "end_ms": 7000,
                                 "effect_id": 1, "scope": "per_bar"})
    cid = add["clip"]["id"]
    mv = disp.call("move_clip", {"clip_id": cid, "new_start_ms": 9000})
    assert mv["ok"] is True
    assert mv["clip"]["start_ms"] == 9000
    disp.call("delete_clip", {"clip_id": cid})


def test_set_cue(disp):
    r = disp.call("set_cue", {"slot": 1, "t_sec": 42.0, "name": "Test"})
    assert r["ok"] is True
    assert r["cue"]["time_ms"] == 42000


def test_set_clip_effect(disp):
    add = disp.call("add_clip", {"track": 2, "start_ms": 2000, "end_ms": 4000, "effect_id": 0})
    cid = add["clip"]["id"]
    r = disp.call("set_clip_effect", {"clip_id": cid, "effect_id": 5, "label": "X"})
    assert r["ok"] is True
    clip = next(c for c in disp.call("list_clips")["clips"] if c["id"] == cid)
    assert clip["effect_id"] == 5
    disp.call("delete_clip", {"clip_id": cid})


def test_duplicate_clip(disp):
    before = disp.call("list_clips")["count"]
    add = disp.call("add_clip", {"track": 3, "start_ms": 1000, "end_ms": 2000, "effect_id": 1})
    cid = add["clip"]["id"]
    dupe = disp.call("duplicate_clip", {"clip_id": cid})
    assert dupe["ok"] is True
    assert disp.call("list_clips")["count"] == before + 2
    disp.call("delete_clip", {"clip_id": cid})
    disp.call("delete_clip", {"clip_id": dupe["clip"]["id"]})


def test_split_clip(disp):
    add = disp.call("add_clip", {"track": 4, "start_ms": 0, "end_ms": 4000, "effect_id": 0})
    cid = add["clip"]["id"]
    before = disp.call("list_clips")["count"]
    r = disp.call("split_clip", {"clip_id": cid, "t_ms": 2000})
    assert r["ok"] is True
    assert disp.call("list_clips")["count"] == before + 1


def test_local_methods_listed(disp):
    for m in ("set_loop", "set_clip_effect", "duplicate_clip", "split_clip",
              "list_feedback", "analyzer_waveform_peaks"):
        assert m in disp.methods


def test_presets_seeded(disp):
    r = disp.call("list_presets")
    assert len(r["presets"]) > 0  # banco no nace vacío (seed global)
    assert any("Flash" in p["name"] for p in r["presets"])


def test_preset_create_clip_and_live_link(disp):
    # crear preset "Flash Rojo" (hue 0) sobre color_flash
    eff = next(e for e in disp.call("list_effects")["effects"] if e["name"] == "color_flash")
    cre = disp.call("create_preset", {"name": "Test Rojo", "base_effect_id": eff["id"],
                                      "params": {"hue": 0}, "color": "#ff0000", "scope": "project"})
    pid = cre["preset"]["preset_id"]
    # clip ligado al preset
    add = disp.call("add_preset_clip", {"preset_id": pid, "track": 0,
                                        "start_ms": 1000, "end_ms": 3000})
    assert add["clip"]["preset_id"] == pid
    cid = add["clip"]["id"]
    # render no peta y el clip resuelve el efecto del preset
    f = disp.session.compute_frame(2.0)
    assert f.shape == (10, 93, 3)
    # enlace vivo: editar el preset actualiza el snapshot del clip
    disp.call("update_preset", {"preset_id": pid, "params": {"hue": 120}, "color": "#00ff00"})
    clip = next(c for c in disp.call("list_clips")["clips"] if c["id"] == cid)
    assert clip["color"] == "#00ff00"
    assert clip["params"]["hue"] == 120
    # limpieza
    disp.call("delete_clip", {"clip_id": cid})
    assert disp.call("delete_preset", {"preset_id": pid})["ok"] is True


def test_channel_presets_seeded(disp):
    presets = disp.call("list_presets")["presets"]
    chan = [p for p in presets if p.get("kind") == "channel"]
    assert len(chan) > 0  # seed incluye presets de movers
    assert any(p["channel_effect_id"] == "pos_circle" for p in chan)


def test_channel_preset_clip_on_fixture(disp):
    # crear preset de canal "Test Círculo" sobre pos_circle
    cre = disp.call("create_preset", {"name": "Test Círculo", "kind": "channel",
                                      "channel_effect_id": "pos_circle",
                                      "params": {"speed": 0.4}, "color": "#a779f0", "scope": "project"})
    p = cre["preset"]
    assert p["kind"] == "channel" and p["category"] == "position"
    pid = p["preset_id"]
    # buscar un fixture no-LED (mover)
    fx = next(f for f in disp.call("list_fixtures")["fixtures"] if f.get("legacy_bar_idx") is None)
    add = disp.call("add_preset_clip", {"preset_id": pid, "fixture_id": fx["fixture_id"],
                                        "start_ms": 1000, "end_ms": 4000})
    assert add["ok"] is True
    clip = add["clip"]
    assert clip["preset_id"] == pid
    assert clip["scope"] == f"fixture:{fx['fixture_id']}"
    assert clip["channel_effect_id"] == "pos_circle"
    # enlace vivo: editar params del preset → snapshot del clip channel cambia
    disp.call("update_preset", {"preset_id": pid, "params": {"speed": 0.9}})
    got = next(c for c in disp.call("list_clips")["clips"] if c["id"] == clip["id"])
    assert got["params"]["speed"] == 0.9
    disp.call("delete_clip", {"clip_id": clip["id"]})
    disp.call("delete_preset", {"preset_id": pid})


def test_undo_redo(disp):
    before = disp.call("list_clips")["count"]
    disp.call("add_clip", {"track": 0, "start_ms": 100, "end_ms": 200, "effect_id": 0})
    assert disp.call("list_clips")["count"] == before + 1
    assert disp.call("undo")["ok"] is True
    assert disp.call("list_clips")["count"] == before
    assert disp.call("redo")["ok"] is True
    assert disp.call("list_clips")["count"] == before + 1
    disp.call("undo")  # dejar como estaba


def test_export_csv(disp):
    r = disp.call("export_csv")
    assert r["ok"] is True
    assert r["filename"].endswith(".csv")
    assert len(r["content"]) > 0


def test_export_qlc(disp):
    r = disp.call("export_qlc")
    assert r["ok"] is True
    assert r["filename"].endswith(".qxw")
    assert "<" in r["content"]


def test_unknown_method(disp):
    resp = disp.handle({"jsonrpc": "2.0", "id": 1, "method": "no_such", "params": {}})
    assert "error" in resp


def test_duplicate_range(disp):
    """A5: duplicate_range copia clips en [t0_ms, t1_ms) desplazados a dest_ms."""
    T = 350_000  # ms lejos del contenido real del show (350 s)

    # Añadir 2 clips dentro del rango y 1 fuera
    r1 = disp.call("add_clip", {"track": 0, "start_ms": T, "end_ms": T + 500, "effect_id": 0})
    r2 = disp.call("add_clip", {"track": 1, "start_ms": T + 1000, "end_ms": T + 1500, "effect_id": 0})
    r3 = disp.call("add_clip", {"track": 0, "start_ms": T + 2000, "end_ms": T + 2500, "effect_id": 0})
    src_ids = [r1["clip"]["id"], r2["clip"]["id"], r3["clip"]["id"]]

    dest = T + 10_000
    dup = disp.call("duplicate_range", {"t0_ms": T, "t1_ms": T + 2000, "dest_ms": dest})
    assert dup["ok"] is True
    assert len(dup["clips"]) == 2  # solo los 2 clips con start_ms en [T, T+2000)

    new_starts = sorted(c["start_ms"] for c in dup["clips"])
    assert new_starts == [dest, dest + 1000]  # offsets conservados

    # Los nuevos clips están en el timeline
    all_ids = {c["id"] for c in disp.call("list_clips")["clips"]}
    new_ids = {c["id"] for c in dup["clips"]}
    assert new_ids.issubset(all_ids)

    # Undo revierte la duplicación (los originales quedan intactos)
    assert disp.call("undo")["ok"] is True
    after_undo = {c["id"] for c in disp.call("list_clips")["clips"]}
    assert not new_ids.intersection(after_undo)
    assert {src_ids[0], src_ids[1], src_ids[2]}.issubset(after_undo)

    # t0 >= t1 devuelve ok=False (no excepción)
    err = disp.call("duplicate_range", {"t0_ms": T + 2000, "t1_ms": T, "dest_ms": 0})
    assert err["ok"] is False

    # Limpieza: borrar los 3 clips originales
    for cid in src_ids:
        try:
            disp.call("delete_clip", {"clip_id": cid})
        except Exception:
            pass
