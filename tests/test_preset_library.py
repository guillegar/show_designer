"""
test_preset_library.py — Tests de la biblioteca de presets curados (F3).

Cubre:
  - Los 10 efectos F1 (1010-1019) tienen exactamente 3 presets curados en el banco global.
  - Todos los presets tienen effect_id válido (efecto cargado en la librería).
  - set_clip_preset aplica params del preset al clip (roundtrip).
  - Preset con param_links (Pulso Ámbar) los propaga al clip.
  - list_presets con filtro effect_id devuelve solo los del efecto.
  - list_presets sin filtro devuelve todos.
"""
import pytest
import sys, os, tempfile
from pathlib import Path

# Asegurar que el root del repo está en sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("LUCES_NO_MCP_COMPAT", "1")


@pytest.fixture()
def tmp_presets(tmp_path, monkeypatch):
    """Monta PresetBank en un directorio temporal para no tocar presets.json de producción."""
    monkeypatch.chdir(tmp_path)
    # Parchear GLOBAL_FILE para que apunte al tmp
    import server.presets as pm
    orig_global = pm.GLOBAL_FILE
    pm.GLOBAL_FILE = tmp_path / "presets.json"
    yield pm, tmp_path
    pm.GLOBAL_FILE = orig_global


@pytest.fixture()
def library():
    from src.core.effects_engine import EffectLibrary
    return EffectLibrary()


@pytest.fixture()
def bank(tmp_presets, library):
    pm, tmp_path = tmp_presets
    return pm.PresetBank(library, project_file=tmp_path / "proj_presets.json")


# ── Cobertura de efectos F1 ─────────────────────────────────────────────────

F1_IDS = list(range(1010, 1020))


def test_each_f1_effect_has_3_global_presets(bank):
    all_presets = bank.list()
    for eid in F1_IDS:
        matching = [p for p in all_presets if p.kind == "pixel" and p.base_effect_id == eid]
        assert len(matching) == 3, (
            f"Se esperaban 3 presets para effect_id={eid}, encontrados {len(matching)}: "
            + str([p.name for p in matching])
        )


def test_all_f3_presets_have_valid_effect_id(bank, library):
    all_presets = bank.list()
    f3 = [p for p in all_presets if p.kind == "pixel" and p.base_effect_id in set(F1_IDS)]
    assert len(f3) == 30, f"Se esperaban 30 presets F3, encontrados {len(f3)}"
    for p in f3:
        effect = library.get_effect(p.base_effect_id)
        assert effect is not None, f"Preset '{p.name}' referencia effect_id={p.base_effect_id} no encontrado"


def test_f3_presets_have_non_empty_params(bank):
    all_presets = bank.list()
    f3 = [p for p in all_presets if p.kind == "pixel" and p.base_effect_id in set(F1_IDS)]
    for p in f3:
        assert len(p.params) > 0, f"Preset '{p.name}' tiene params vacíos"


# ── Filtro list_presets por effect_id ───────────────────────────────────────

def test_list_presets_filter_by_effect_id(bank):
    """list() retorna todos; filtrado manualmente como hace el dispatcher."""
    all_presets = bank.list()
    for eid in F1_IDS:
        filtered = [p for p in all_presets if p.kind == "pixel" and p.base_effect_id == eid]
        assert len(filtered) == 3


def test_list_presets_no_filter_returns_all(bank):
    all_presets = bank.list()
    assert len(all_presets) >= 30  # 30 F3 + los seeds globales existentes


# ── Roundtrip set_clip_preset ────────────────────────────────────────────────

def test_set_clip_preset_applies_params(bank, library):
    """Simula lo que hace _h_set_clip_preset: los params del preset llegan al clip."""
    from src.core.timeline_model import Clip
    c = Clip(track=0, start_ms=0, end_ms=2000, effect_id=0)

    # Coger el preset "Hoguera" (fire, eid=1014)
    all_presets = bank.list()
    hoguera = next((p for p in all_presets if p.name == "Hoguera"), None)
    assert hoguera is not None, "Preset 'Hoguera' no encontrado"

    # Aplicar manualmente (igual que el handler)
    c.params = dict(hoguera.params)
    c.color = hoguera.color
    c.label = hoguera.name
    c.preset_id = hoguera.preset_id
    c.effect_id = hoguera.base_effect_id

    assert c.effect_id == 1014
    assert c.params.get("intensity") == pytest.approx(0.6)
    assert c.params.get("cooling") == pytest.approx(0.5)
    assert c.params.get("sparking") == pytest.approx(0.5)
    assert c.label == "Hoguera"


def test_set_clip_preset_aurora_boreal_gradient(bank):
    """Preset 'Aurora Boreal' (gradient_sweep) tiene params de color correctos."""
    all_presets = bank.list()
    aurora = next((p for p in all_presets if p.name == "Aurora Boreal"), None)
    assert aurora is not None
    assert aurora.base_effect_id == 1010
    assert aurora.params["color1_r"] == 0
    assert aurora.params["color1_b"] == 255
    assert aurora.params["color2_r"] == 128


# ── Presets con param_links ──────────────────────────────────────────────────

def test_pulso_ambar_has_param_links(bank):
    """El preset 'Pulso Ámbar' (breathing, audio_reactive) incluye param_links."""
    all_presets = bank.list()
    pulso = next((p for p in all_presets if p.name == "Pulso Ámbar"), None)
    assert pulso is not None, "Preset 'Pulso Ámbar' no encontrado"
    assert pulso.base_effect_id == 1019
    assert len(pulso.param_links) > 0, "Pulso Ámbar debe tener al menos un param_link"
    link = pulso.param_links[0]
    assert link["param"] == "rate_hz"
    assert link["source"] == "rms"


def test_clip_gets_param_links_from_preset(bank):
    """Cuando se aplica un preset con param_links al clip, el clip los recibe."""
    from src.core.timeline_model import Clip
    c = Clip(track=0, start_ms=0, end_ms=2000, effect_id=0)
    c.param_links = []

    all_presets = bank.list()
    pulso = next((p for p in all_presets if p.name == "Pulso Ámbar"), None)
    assert pulso is not None

    # Simular _h_set_clip_preset
    c.params = dict(pulso.params)
    if getattr(pulso, "param_links", None):
        c.param_links = list(pulso.param_links)
    c.effect_id = pulso.base_effect_id

    assert len(c.param_links) > 0
    assert c.param_links[0]["param"] == "rate_hz"


# ── Validación de schema ─────────────────────────────────────────────────────

def test_f3_preset_params_pass_schema_validation(bank, library):
    """Todos los params de presets F3 pasan la validación de schema."""
    from server.validators import validate_params_against_schema
    all_presets = bank.list()
    f3 = [p for p in all_presets if p.kind == "pixel" and p.base_effect_id in set(F1_IDS)]
    for p in f3:
        effect = library.get_effect(p.base_effect_id)
        schema = getattr(effect, "PARAM_SCHEMA", {})
        try:
            validate_params_against_schema(p.params, schema)
        except Exception as e:
            pytest.fail(f"Preset '{p.name}' falla validación: {e}")


# ── Persistencia: migración automática ──────────────────────────────────────

def test_f3_seeds_persist_to_json(tmp_presets, library):
    """El banco escribe los presets F3 en presets.json al crearse."""
    import json
    pm, tmp_path = tmp_presets
    bank = pm.PresetBank(library, project_file=tmp_path / "proj.json")

    data = json.loads((tmp_path / "presets.json").read_text(encoding="utf-8"))
    pixel_ids = {d["base_effect_id"] for d in data if d.get("kind") == "pixel"}
    f3_ids = set(range(1010, 1020))
    assert f3_ids.issubset(pixel_ids), f"Faltan IDs en presets.json: {f3_ids - pixel_ids}"


def test_f3_seeds_added_on_existing_json(tmp_presets, library):
    """Si presets.json ya existe sin F3, se añaden automáticamente al cargar."""
    import json
    pm, tmp_path = tmp_presets
    # Crear un presets.json mínimo sin efectos F1
    old_presets = [{"preset_id": "aaa", "name": "Old", "kind": "pixel",
                    "base_effect_id": 0, "family": "", "params": {}, "color": "#fff",
                    "scope": "global"}]
    (tmp_path / "presets.json").write_text(json.dumps(old_presets), encoding="utf-8")

    bank = pm.PresetBank(library, project_file=tmp_path / "proj.json")
    all_presets = bank.list()
    covered = {p.base_effect_id for p in all_presets if p.kind == "pixel"}
    assert set(range(1010, 1020)).issubset(covered)
