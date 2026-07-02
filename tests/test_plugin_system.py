"""
tests/test_plugin_system.py — Tests del sistema de plugins de efectos (v1.8 F4)
"""
import sys
import tempfile
import textwrap
import types
from pathlib import Path

import numpy as np
import pytest

# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_bars():
    from src.core.effects_engine import LEDS_PER_BAR, NUM_BARS
    return np.zeros((NUM_BARS, LEDS_PER_BAR, 3), dtype=np.float32)


# ── 1. Carga básica de la librería con plugins reales ────────────────────────

def test_library_loads_with_plugins():
    """EffectLibrary carga sin errores y tiene >51 efectos (con plugins)."""
    from src.core.effects_engine import PLUGIN_BASE_ID, EffectLibrary
    lib = EffectLibrary()
    assert len(lib.effects) > 51, "Deben haber efectos base + al menos un plugin"
    # Los efectos base no deben haberse corrompido
    assert lib.get_effect(0) is not None
    assert lib.get_effect(50) is not None


def test_plugin_effects_have_correct_ids():
    """Los efectos de plugins tienen IDs >= 1000."""
    from src.core.effects_engine import PLUGIN_BASE_ID, EffectLibrary
    lib = EffectLibrary()
    plugin_effects = {k: v for k, v in lib.effects.items() if k >= PLUGIN_BASE_ID}
    assert len(plugin_effects) >= 2, "example_plugin debe cargar al menos 2 efectos"


def test_example_plugin_effects_registered():
    """Los efectos del plugin de ejemplo están registrados."""
    from src.core.effects_engine import EffectLibrary
    lib = EffectLibrary()
    names = {e.name for e in lib.effects.values()}
    assert 'meteor_shower' in names
    assert 'heartbeat' in names


def test_plugin_effect_families():
    """Los efectos del plugin tienen la familia correcta."""
    from src.core.effects_engine import EffectLibrary
    lib = EffectLibrary()
    for eff in lib.effects.values():
        if eff.name in ('meteor_shower', 'heartbeat'):
            assert eff.family == 'plugin_demo'


# ── 2. Renderizado de efectos plugin ─────────────────────────────────────────

def test_meteor_shower_render():
    """MeteorShowerEffect.render devuelve array de forma correcta."""
    from src.core.effects_engine import EffectLibrary
    lib = EffectLibrary()
    # Buscar por nombre
    meteor = next((e for e in lib.effects.values() if e.name == 'meteor_shower'), None)
    assert meteor is not None
    bars = _make_bars()
    ctx = {'energy': 0.7, 'rms': 0.5}
    result = meteor.render(500.0, bars, ctx)
    assert result.shape == bars.shape
    assert result.max() > 0, "Debe haber LEDs encendidos"


def test_heartbeat_render():
    """HeartbeatEffect.render devuelve array correcto."""
    from src.core.effects_engine import EffectLibrary
    lib = EffectLibrary()
    heartbeat = next((e for e in lib.effects.values() if e.name == 'heartbeat'), None)
    assert heartbeat is not None
    bars = _make_bars()
    ctx = {'energy': 0.8}
    result = heartbeat.render(100.0, bars, ctx, bpm=120.0)
    assert result.shape == bars.shape


def test_plugin_render_no_audio_context():
    """Plugins no crashean con audio_context=None y respetan el contrato de shape."""
    from src.core.effects_engine import EffectLibrary
    lib = EffectLibrary()
    bars = _make_bars()
    for eff_id, eff in lib.effects.items():
        if eff_id >= 1000:
            try:
                result = eff.render(0.0, bars, None)
            except Exception as e:
                pytest.fail(f"Plugin {eff.name} crashea con context=None: {e}")
            # El shape válido lo fija el contrato derivado del scope (hallazgo 1):
            # PER_BAR → (1, LEDS, 3); ALL_BARS/GLOBAL → (NUM_BARS, LEDS, 3).
            assert result.shape == eff.expected_output_shape, (
                f"Plugin {eff.name} (scope={eff.scope.value}) devolvió "
                f"{result.shape}, se esperaba {eff.expected_output_shape}")


# ── 3. Sistema de autodescubrimiento con módulos sintéticos ──────────────────

def test_plugin_with_explicit_dict(tmp_path):
    """Un plugin con PLUGIN_EFFECTS={id: instance} carga con esos IDs."""
    plugin_code = textwrap.dedent("""
        import numpy as np
        from src.core.effects_engine import (Effect, EffectScope, EffectGeometry,
                                    EffectSymmetry)

        class TestEffect(Effect):
            name        = "test_explicit"
            family      = "test"
            duration_ms = 1000
            scope       = EffectScope.ALL_BARS
            geometry    = EffectGeometry.GEOMETRY_3D
            symmetry    = EffectSymmetry.ASYMMETRIC
            description = "Test explicit ID"

            def render(self, elapsed_time, bars_state, audio_context, **params):
                return bars_state.copy()

        PLUGIN_EFFECTS = {1099: TestEffect()}
    """)
    pdir = tmp_path / "plugins" / "effects"
    pdir.mkdir(parents=True)
    (pdir / "__init__.py").write_text("")
    (pdir / "test_explicit_plugin.py").write_text(plugin_code)

    # Simular _load_plugins manualmente con el directorio temporal
    import importlib.util
    import sys

    from src.core.effects_engine import PLUGIN_BASE_ID, Effect

    effects_found = {}
    for plugin_file in sorted(pdir.glob('*.py')):
        if plugin_file.name.startswith('_'):
            continue
        mod_name = f"_test_explicit.{plugin_file.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, plugin_file)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        if hasattr(mod, 'PLUGIN_EFFECTS') and isinstance(mod.PLUGIN_EFFECTS, dict):
            for eid, einst in mod.PLUGIN_EFFECTS.items():
                if isinstance(einst, Effect):
                    effects_found[eid] = einst

    assert 1099 in effects_found
    assert effects_found[1099].name == 'test_explicit'


def test_plugin_autodiscovery(tmp_path):
    """Un plugin sin PLUGIN_EFFECTS autodescubre subclases de Effect."""
    plugin_code = textwrap.dedent("""
        import numpy as np
        from src.core.effects_engine import (Effect, EffectScope, EffectGeometry,
                                    EffectSymmetry)

        class AutoEffect(Effect):
            name        = "auto_discovered"
            family      = "test_auto"
            duration_ms = 500
            scope       = EffectScope.ALL_BARS
            geometry    = EffectGeometry.GEOMETRY_3D
            symmetry    = EffectSymmetry.ASYMMETRIC
            description = "Autodescubierto"

            def render(self, elapsed_time, bars_state, audio_context, **params):
                return bars_state.copy()
    """)
    pdir = tmp_path / "plugins" / "effects"
    pdir.mkdir(parents=True)
    (pdir / "__init__.py").write_text("")
    (pdir / "test_auto_plugin.py").write_text(plugin_code)

    import importlib.util

    from src.core.effects_engine import PLUGIN_BASE_ID, Effect

    effects_found = {}
    next_id = PLUGIN_BASE_ID

    for plugin_file in sorted(pdir.glob('*.py')):
        if plugin_file.name.startswith('_'):
            continue
        spec = importlib.util.spec_from_file_location(
            f"test_auto.{plugin_file.stem}", plugin_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, 'PLUGIN_EFFECTS'):
            continue
        for attr in dir(mod):
            cls = getattr(mod, attr)
            if (isinstance(cls, type) and
                    issubclass(cls, Effect) and
                    cls is not Effect and
                    not getattr(cls, '__abstractmethods__', None)):
                effects_found[next_id] = cls()
                next_id += 1

    assert len(effects_found) == 1
    assert list(effects_found.values())[0].name == 'auto_discovered'


# ── 4. list_effects incluye plugins ──────────────────────────────────────────

def test_list_effects_includes_plugins():
    """list_effects() incluye los efectos de los plugins."""
    from src.core.effects_engine import EffectLibrary
    lib = EffectLibrary()
    listing = lib.list_effects()
    # Debe haber efectos con ID >= 1000
    plugin_ids = [k for k in listing if k >= 1000]
    assert len(plugin_ids) >= 2
    for pid in plugin_ids:
        assert 'name' in listing[pid]
        assert 'family' in listing[pid]


def test_get_effect_plugin():
    """get_effect() funciona para IDs de plugin."""
    from src.core.effects_engine import EffectLibrary
    lib = EffectLibrary()
    eff = lib.get_effect(1000)
    assert eff is not None
    assert eff.name == 'meteor_shower'


# ── 5. Proteccion: plugins no solapan IDs base ───────────────────────────────

def test_base_effects_not_overwritten():
    """Cargar plugins no sobreescribe los efectos base (0-50)."""
    from src.core.effects_engine import EffectLibrary
    lib = EffectLibrary()
    # Efecto 0 debe seguir siendo WhiteFlashEffect
    assert lib.get_effect(0).name == 'white_flash'
    # Efecto 50 debe seguir siendo RingExpandEffect
    assert lib.get_effect(50) is not None
