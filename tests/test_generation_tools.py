"""
Tests de los handlers MCP de generación (v1.8):
  - generate_section
  - mirror_clips_lr
  - apply_palette_to_range

Testea handlers directamente sin arrancar el WS server.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.mcp import mcp_bridge as mb
from src.core.timeline_model import Timeline, Clip


# ────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────

class MockApp:
    """App mínima con timeline vacío y sin analyzer."""
    def __init__(self, svc=None):
        self.timeline = Timeline()
        self.analysis = svc
        self._tl_view = None

    def _refresh_timeline(self): pass


@pytest.fixture
def app():
    return MockApp()


@pytest.fixture
def app_with_analyzer():
    """App con AnalysisService real si hay análisis disponible."""
    try:
        from src.analysis.analyzer_service import default_service, Curation
        svc = default_service()
        if not svc.has_analysis:
            return MockApp(svc=None)
        return MockApp(svc=svc)
    except Exception:
        return MockApp()


def _add_bar_clips(timeline, bars=(0, 1, 2), start_ms=0, end_ms=1000, effect_id=0):
    """Añade clips bar:N al timeline para tests de mirror."""
    for bar in bars:
        c = Clip(
            track=0,
            start_ms=start_ms,
            end_ms=end_ms,
            effect_id=effect_id,
            scope=f"bar:{bar}",
        )
        timeline.add(c)


# ────────────────────────────────────────────────────────────────
# generate_section — sin analyzer
# ────────────────────────────────────────────────────────────────

class TestGenerateSection:

    def test_basic_fill(self, app):
        r = mb._h_generate_section(app, {
            "effect_id": 0,
            "trigger": "fill",
            "start_sec": 0.0,
            "end_sec": 5.0,
        })
        assert r["ok"] is True
        assert r["count"] == 1
        c = r["clips"][0]
        assert c["start_ms"] == 0
        assert c["end_ms"] == 5000

    def test_every_500ms(self, app):
        r = mb._h_generate_section(app, {
            "effect_id": 1,
            "trigger": "every_500ms",
            "start_sec": 0.0,
            "end_sec": 3.0,
        })
        assert r["ok"] is True
        assert r["count"] == 6  # 0, 500, 1000, 1500, 2000, 2500

    def test_every_250ms(self, app):
        r = mb._h_generate_section(app, {
            "effect_id": 0,
            "trigger": "every_250ms",
            "start_sec": 0.0,
            "end_sec": 1.0,
        })
        assert r["ok"] is True
        assert r["count"] == 4  # 0, 250, 500, 750

    def test_dry_run_no_clips_added(self, app):
        r = mb._h_generate_section(app, {
            "effect_id": 0,
            "trigger": "fill",
            "start_sec": 0.0,
            "end_sec": 5.0,
            "dry_run": True,
        })
        assert r["ok"] is True
        assert r["dry_run"] is True
        assert len(app.timeline.clips) == 0  # nada añadido

    def test_clips_added_to_timeline(self, app):
        mb._h_generate_section(app, {
            "effect_id": 0,
            "trigger": "every_500ms",
            "start_sec": 0.0,
            "end_sec": 2.0,
        })
        assert len(app.timeline.clips) == 4

    def test_max_clips_limit(self, app):
        r = mb._h_generate_section(app, {
            "effect_id": 0,
            "trigger": "every_500ms",
            "start_sec": 0.0,
            "end_sec": 60.0,
            "max_clips": 5,
        })
        assert r["ok"] is True
        assert r["count"] <= 5

    def test_spacing_ms_reduces_count(self, app):
        """Con spacing_ms = 1000, no puede haber más de 1 clip por segundo."""
        r = mb._h_generate_section(app, {
            "effect_id": 0,
            "trigger": "every_250ms",
            "start_sec": 0.0,
            "end_sec": 4.0,
            "spacing_ms": 1000,
        })
        # Sin spacing serian 16 clips; con 1000ms de spacing → max 4
        assert r["count"] <= 4

    def test_clip_duration_ms_respected(self, app):
        r = mb._h_generate_section(app, {
            "effect_id": 0,
            "trigger": "fill",
            "start_sec": 0.0,
            "end_sec": 10.0,
            "clip_duration_ms": 99999,  # will be clamped to end_ms
        })
        c = r["clips"][0]
        assert c["end_ms"] <= 10000  # no se sale del rango

    def test_scope_and_track_forwarded(self, app):
        r = mb._h_generate_section(app, {
            "effect_id": 2,
            "trigger": "fill",
            "start_sec": 1.0,
            "end_sec": 3.0,
            "scope": "bar:3",
            "track": 5,
            "layer": 2,
            "color": "#ff0000",
        })
        assert r["ok"] is True
        c = r["clips"][0]
        assert c["scope"] == "bar:3"
        assert c["track"] == 5
        assert c["layer"] == 2
        assert c["color"] == "#ff0000"

    def test_invalid_trigger_format(self, app):
        r = mb._h_generate_section(app, {
            "effect_id": 0,
            "trigger": "every_badformat",
            "start_sec": 0.0,
            "end_sec": 5.0,
        })
        assert r["ok"] is False
        assert "formato" in r["error"]

    def test_missing_time_range(self, app):
        r = mb._h_generate_section(app, {
            "effect_id": 0,
            "trigger": "fill",
        })
        assert r["ok"] is False

    def test_clip_params_forwarded(self, app):
        r = mb._h_generate_section(app, {
            "effect_id": 0,
            "trigger": "fill",
            "start_sec": 0.0,
            "end_sec": 2.0,
            "clip_params": {"hue": 180, "speed": 2.0},
        })
        c = r["clips"][0]
        assert c["params"]["hue"] == 180


class TestGenerateSectionWithAnalyzer:

    def test_on_beat_uses_analyzer(self, app_with_analyzer):
        if app_with_analyzer.analysis is None:
            pytest.skip("Sin analyzer")
        r = mb._h_generate_section(app_with_analyzer, {
            "effect_id": 0,
            "trigger": "on_beat",
            "start_sec": 0.0,
            "end_sec": 10.0,
        })
        assert r["ok"] is True
        assert r["count"] > 0

    def test_section_name_resolves(self, app_with_analyzer):
        if app_with_analyzer.analysis is None:
            pytest.skip("Sin analyzer")
        # Buscar cualquier sección existente
        svc = app_with_analyzer.analysis
        sections = svc.list_sections(with_curated=True)
        if not sections:
            pytest.skip("No hay secciones")
        sec = sections[0]
        sec_d = sec.to_dict() if hasattr(sec, "to_dict") else sec
        sec_label = sec_d.get("label") or sec_d.get("type", "intro")
        r = mb._h_generate_section(app_with_analyzer, {
            "effect_id": 0,
            "trigger": "fill",
            "section_name": sec_label,
        })
        assert r["ok"] is True

    def test_invalid_section_name(self, app_with_analyzer):
        if app_with_analyzer.analysis is None:
            pytest.skip("Sin analyzer")
        r = mb._h_generate_section(app_with_analyzer, {
            "effect_id": 0,
            "trigger": "fill",
            "section_name": "__no_existe_esta_seccion__",
        })
        assert r["ok"] is False


# ────────────────────────────────────────────────────────────────
# mirror_clips_lr
# ────────────────────────────────────────────────────────────────

class TestMirrorClipsLR:

    def test_basic_mirror(self, app):
        _add_bar_clips(app.timeline, bars=[0, 1, 2])
        r = mb._h_mirror_clips_lr(app, {"start_ms": 0})
        assert r["ok"] is True
        assert r["count"] == 3  # bar 0→9, 1→8, 2→7

    def test_mirror_bar_values(self, app):
        _add_bar_clips(app.timeline, bars=[0])
        r = mb._h_mirror_clips_lr(app, {"start_ms": 0})
        assert r["ok"] is True
        assert r["clips"][0]["scope"] == "bar:9"

    def test_mirror_bar_9_goes_to_0(self, app):
        _add_bar_clips(app.timeline, bars=[9])
        r = mb._h_mirror_clips_lr(app, {"start_ms": 0})
        assert r["ok"] is True
        assert r["clips"][0]["scope"] == "bar:0"

    def test_no_duplicate_mirrors(self, app):
        """Si ya existe el espejo, no lo vuelve a crear."""
        _add_bar_clips(app.timeline, bars=[0, 9])  # 9 es el espejo de 0
        r = mb._h_mirror_clips_lr(app, {"start_ms": 0})
        assert r["ok"] is True
        # bar:0 → espejo bar:9 ya existe → skip
        # bar:9 → espejo bar:0 ya existe → skip
        assert r["count"] == 0

    def test_dry_run(self, app):
        _add_bar_clips(app.timeline, bars=[1, 2])
        r = mb._h_mirror_clips_lr(app, {"start_ms": 0, "dry_run": True})
        assert r["ok"] is True
        assert r["dry_run"] is True
        # Solo los 2 originales, nada añadido
        assert len(app.timeline.clips) == 2

    def test_mirror_only_in_range(self, app):
        """Los clips fuera del rango end_ms no se espejan."""
        _add_bar_clips(app.timeline, bars=[0], start_ms=5000, end_ms=6000)
        r = mb._h_mirror_clips_lr(app, {"start_ms": 0, "end_ms": 4000})
        assert r["ok"] is False  # no hay clips en el rango

    def test_layer_offset_applied(self, app):
        _add_bar_clips(app.timeline, bars=[3])
        r = mb._h_mirror_clips_lr(app, {"start_ms": 0, "layer_offset": 2})
        assert r["ok"] is True
        # layer original = 0, espejo = 0 + 2 = 2
        assert r["clips"][0]["layer"] == 2

    def test_color_override(self, app):
        _add_bar_clips(app.timeline, bars=[0])
        r = mb._h_mirror_clips_lr(app, {"start_ms": 0, "color": "#ff0000"})
        assert r["clips"][0]["color"] == "#ff0000"

    def test_no_mirror_for_all_bars_scope(self, app):
        """Clips con scope all_bars o per_bar no deben ser espejados."""
        c = Clip(track=0, start_ms=0, end_ms=1000, effect_id=0, scope="all_bars")
        app.timeline.add(c)
        r = mb._h_mirror_clips_lr(app, {"start_ms": 0})
        assert r["ok"] is False

    def test_track_filter(self, app):
        """Solo espeja clips en la pista indicada."""
        _add_bar_clips(app.timeline, bars=[0])  # track=0
        c = Clip(track=1, start_ms=0, end_ms=1000, effect_id=0, scope="bar:1")
        app.timeline.add(c)
        r = mb._h_mirror_clips_lr(app, {"start_ms": 0, "track": 1})
        assert r["ok"] is True
        assert r["count"] == 1  # solo el de track 1


# ────────────────────────────────────────────────────────────────
# apply_palette_to_range
# ────────────────────────────────────────────────────────────────

class TestApplyPaletteToRange:

    def _fill_timeline(self, timeline, n=6):
        for i in range(n):
            c = Clip(track=0, start_ms=i * 500, end_ms=(i + 1) * 500,
                     effect_id=0, scope="per_bar", params={})
            timeline.add(c)

    def test_cycle_mode(self, app):
        self._fill_timeline(app.timeline, 6)
        r = mb._h_apply_palette_to_range(app, {
            "palette": "warm",
            "start_ms": 0,
            "mode": "cycle",
        })
        assert r["ok"] is True
        assert r["count"] == 6
        hues = [u["hue"] for u in r["updates"]]
        warm = [0, 20, 40, 60]
        for h in hues:
            assert h in warm

    def test_gradient_mode(self, app):
        self._fill_timeline(app.timeline, 3)
        r = mb._h_apply_palette_to_range(app, {
            "palette": "cool",
            "start_ms": 0,
            "mode": "gradient",
        })
        assert r["ok"] is True
        hues = [u["hue"] for u in r["updates"]]
        # Primer hue = 180 (cool[0]), último = 240 (cool[-1])
        assert hues[0] == 180
        assert hues[-1] == 240

    def test_random_mode(self, app):
        self._fill_timeline(app.timeline, 10)
        r = mb._h_apply_palette_to_range(app, {
            "palette": "fire",
            "start_ms": 0,
            "mode": "random",
        })
        assert r["ok"] is True
        fire = [0, 10, 20, 30, 40]
        for u in r["updates"]:
            assert u["hue"] in fire

    def test_custom_palette_list(self, app):
        self._fill_timeline(app.timeline, 3)
        r = mb._h_apply_palette_to_range(app, {
            "palette": [90, 180, 270],
            "start_ms": 0,
            "mode": "cycle",
        })
        assert r["ok"] is True
        hues = [u["hue"] for u in r["updates"]]
        for h in hues:
            assert h in [90, 180, 270]

    def test_unknown_palette_error(self, app):
        self._fill_timeline(app.timeline, 2)
        r = mb._h_apply_palette_to_range(app, {
            "palette": "nonexistent_palette",
            "start_ms": 0,
        })
        assert r["ok"] is False
        assert "nonexistent_palette" in r["error"]

    def test_hue_written_to_clip_params(self, app):
        self._fill_timeline(app.timeline, 1)
        mb._h_apply_palette_to_range(app, {
            "palette": "mono",
            "start_ms": 0,
        })
        c = app.timeline.clips[0]
        assert "hue" in c.params
        assert c.params["hue"] == 60  # mono paleta = [60]

    def test_locked_clips_skipped(self, app):
        self._fill_timeline(app.timeline, 2)
        app.timeline.clips[0].locked = True
        r = mb._h_apply_palette_to_range(app, {
            "palette": "warm",
            "start_ms": 0,
        })
        # Solo debería actualizar el no bloqueado
        assert r["count"] == 1

    def test_range_filter(self, app):
        self._fill_timeline(app.timeline, 4)  # 0, 500, 1000, 1500 ms
        r = mb._h_apply_palette_to_range(app, {
            "palette": "warm",
            "start_ms": 500,
            "end_ms": 1500,
        })
        # Solo los que empiezan en 500 y 1000 (2 clips)
        assert r["count"] == 2

    def test_track_filter(self, app):
        self._fill_timeline(app.timeline, 3)  # track=0
        c = Clip(track=1, start_ms=0, end_ms=500, effect_id=0, scope="per_bar", params={})
        app.timeline.add(c)
        r = mb._h_apply_palette_to_range(app, {
            "palette": "cool",
            "start_ms": 0,
            "track": 1,
        })
        assert r["count"] == 1

    def test_no_clips_in_range(self, app):
        r = mb._h_apply_palette_to_range(app, {
            "palette": "warm",
            "start_ms": 99999,
        })
        assert r["ok"] is False

    def test_all_named_palettes_valid(self, app):
        self._fill_timeline(app.timeline, 3)
        for name in ["warm", "cool", "fire", "ocean", "rainbow", "purple", "neon", "mono"]:
            r = mb._h_apply_palette_to_range(app, {
                "palette": name,
                "start_ms": 0,
            })
            assert r["ok"] is True, f"paleta '{name}' falló"
