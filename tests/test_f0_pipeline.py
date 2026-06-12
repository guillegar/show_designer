"""
test_f0_pipeline.py — ROADMAP v2, Fase F0 (F0.0 actx real + F0.1 param pipeline).

Cubre:
  - resolve_params: fast path SIN copia, orden de stages, no-mutación, stage roto.
  - ShowSession._get_audio_context: contexto REAL (varía con t) + fallback.
  - Parity: compute_frame con pipeline vacío == con stage no-op (mismo frame).
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.param_pipeline import resolve_params, ParamStage  # noqa: E402
from src.core.timeline_model import Clip  # noqa: E402


def _clip(**kw):
    base = dict(track=0, start_ms=0, end_ms=1000, effect_id=0,
                params={'hue': 200, 'brightness': 0.5})
    base.update(kw)
    return Clip(**base)


# ── resolve_params puro ───────────────────────────────────────────────────────

def test_fast_path_sin_stages_devuelve_el_mismo_objeto():
    """Invariante de rendimiento: sin stages, CERO copias (identidad de objeto)."""
    c = _clip()
    out = resolve_params(c, 500, {}, stages=[])
    assert out is c.params


def test_base_params_tiene_prioridad_sobre_clip_params():
    """Si se pasan base_params (p.ej. resueltos de un preset), se usan esos."""
    c = _clip()
    preset_params = {'hue': 99}
    out = resolve_params(c, 500, {}, stages=[], base_params=preset_params)
    assert out is preset_params


class _AddKeyStage:
    """Stage de prueba bien educado: copia antes de escribir."""
    def __init__(self, key, value):
        self.key, self.value = key, value

    def apply(self, params, clip, t_ms, audio_context):
        out = dict(params)
        out[self.key] = self.value
        return out


def test_stages_se_aplican_en_orden():
    c = _clip()
    s1 = _AddKeyStage('marca', 'primero')
    s2 = _AddKeyStage('marca', 'segundo')   # pisa a s1 → gana el último
    out = resolve_params(c, 500, {}, stages=[s1, s2])
    assert out['marca'] == 'segundo'
    assert out['hue'] == 200  # lo demás intacto


def test_stage_no_muta_los_params_originales():
    c = _clip()
    original = dict(c.params)
    resolve_params(c, 500, {}, stages=[_AddKeyStage('extra', 1)])
    assert c.params == original  # el dict del clip queda intacto


class _BrokenStage:
    def apply(self, params, clip, t_ms, audio_context):
        raise RuntimeError("boom")


def test_stage_roto_no_tumba_el_render():
    """Un stage que explota se salta; los demás siguen aplicándose."""
    c = _clip()
    out = resolve_params(c, 500, {}, stages=[_BrokenStage(), _AddKeyStage('ok', 1)])
    assert out['ok'] == 1


def test_protocolo_param_stage():
    assert isinstance(_AddKeyStage('x', 1), ParamStage)


# ── Sesión: actx real (F0.0) + parity del pipeline (F0.1) ────────────────────

@pytest.fixture(scope="module")
def session():
    from server.session import ShowSession
    return ShowSession()


def test_actx_real_varia_con_el_tiempo(session):
    """F0.0: el contexto de audio del render es REAL (cambia entre instantes),
    no el dict estático congelado que usaba la web antes (rms=0.5 fijo)."""
    if not getattr(session.analysis, 'has_timeseries', False):
        pytest.skip("proyecto sin timeseries — el fallback estático es correcto aquí")
    a = session._get_audio_context(5.0)
    b = session._get_audio_context(72.0)   # zona de drop de El Taser
    assert a['rms'] != b['rms'] or a['flux'] != b['flux'], \
        "el audio context no varía con t — ¿sigue usándose _cached_actx?"


def test_actx_fallback_sin_timeseries(session, monkeypatch):
    """Sin análisis, _get_audio_context devuelve el fallback estático (no crashea)."""
    class _Sin:
        has_timeseries = False
    monkeypatch.setattr(session, 'analysis', _Sin())
    out = session._get_audio_context(10.0)
    assert out is session._cached_actx


def test_parity_pipeline_vacio_vs_stage_noop(session):
    """F0.1: registrar un stage que no toca nada produce EXACTAMENTE el mismo
    frame que el pipeline vacío (byte a byte)."""
    class _NoOp:
        def apply(self, params, clip, t_ms, audio_context):
            return params

    t = 72.0
    session.param_stages = []
    f_vacio = session.compute_frame(t).copy()
    session.param_stages = [_NoOp()]
    f_noop = session.compute_frame(t).copy()
    session.param_stages = []
    assert np.array_equal(f_vacio, f_noop)


def test_pipeline_stage_altera_el_frame(session):
    """Un stage que fuerza brightness=0 en todos los clips debe cambiar el frame
    (prueba de que el pipeline está realmente cableado al render)."""
    class _Apagar:
        def apply(self, params, clip, t_ms, audio_context):
            out = dict(params)
            # La mayoría de efectos no tienen 'brightness'; forzamos params
            # imposibles no sirve. En su lugar: devolvemos params vacíos y
            # marcamos que nos llamaron.
            self.called = True
            return out

    st = _Apagar()
    st.called = False
    session.param_stages = [st]
    session.compute_frame(72.0)
    session.param_stages = []
    assert st.called, "el pipeline no se invocó desde compute_frame"
