"""
fixtures.py — Modelo genérico de fixtures para Show Designer (Fase 3).

Reemplaza el modelo hard-codeado de 10 barras WLED en show_engine.py por uno
genérico que permite mezclar strips, movers, dimmers, lásers, etc.

Estructura:
  FixtureProfile  — define el TIPO de fixture (cuántos canales, qué hace cada
                    uno, cuántos LEDs si es strip, metadata como pan/tilt max).
  Fixture         — una INSTANCIA en el rig: dirección DMX (universe, dmx_start),
                    posición física en el escenario, label, referencia al profile.
  FixtureRig      — colección de fixtures + carga/save desde JSON.

Compatibilidad: las 10 barras WLED actuales se exponen como 10 Fixture
con profile_id='wled_strip_93', universe=1..10, dmx_start=1.

Lanzar standalone para test:
    python fixtures.py
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src._paths import PROFILES_DIR, PROJECT_DIR
from src.log import get_logger

_log = get_logger(__name__)

DEFAULT_RIG_FILE = PROJECT_DIR / 'fixtures.json'


# ───────────────────────────────────────────────────────────────
# FixtureProfile — definición de TIPO de fixture
# ───────────────────────────────────────────────────────────────

@dataclass
class FixtureProfile:
    profile_id: str
    name: str
    kind: str                       # 'led_strip' | 'moving_head' | 'dimmer' | 'laser' | 'rgb_par'
    num_channels: int               # canales DMX que ocupa el fixture
    channel_map: dict[str, int] = field(default_factory=dict)
                                    # 'pan':0, 'tilt':1, 'dim':2, ... (offsets DMX desde dmx_start)
    led_count: int = 0              # solo strips
    metadata: dict = field(default_factory=dict)
                                    # max_pan_deg, max_tilt_deg, has_rgb, etc.

    @classmethod
    def from_dict(cls, d: dict) -> FixtureProfile:
        return cls(
            profile_id=d['profile_id'],
            name=d.get('name', d['profile_id']),
            kind=d.get('kind', 'led_strip'),
            num_channels=int(d['num_channels']),
            channel_map=dict(d.get('channel_map', {})),
            led_count=int(d.get('led_count', 0)),
            metadata=dict(d.get('metadata', {})),
        )

    def to_dict(self):
        return asdict(self)

    # ── Categorías deducidas (v1.7) ────────────────────────────
    def supported_categories(self) -> set:
        """Devuelve el conjunto de categorías de efectos que este profile
        soporta, deducido AUTOMÁTICAMENTE del channel_map + led_count.

        Categorías:
          • 'pixel'     → si led_count > 0
          • 'position'  → pan + tilt
          • 'color'     → RGB completo, o color_wheel, o color_macro
          • 'intensity' → dim o intensity
          • 'optical'   → cualquiera de gobo_wheel/prism/focus/zoom/frost/iris
          • 'strobe'    → shutter, strobe_freq, strobe, o (intensity + speed)

        Resultado: el UI sólo ofrece efectos de las categorías presentes.
        Imposible aplicar MoverCircle a una barra LED o ColorRainbow a un
        strobe 2ch.
        """
        cm = self.channel_map
        cats: set = set()
        if self.led_count > 0:
            cats.add('pixel')
        if 'pan' in cm and 'tilt' in cm:
            cats.add('position')
        if ('r' in cm and 'g' in cm and 'b' in cm) \
                or 'color_wheel' in cm or 'color_macro' in cm:
            cats.add('color')
        if 'dim' in cm or 'intensity' in cm:
            cats.add('intensity')
        if any(c in cm for c in (
                'gobo_wheel', 'gobo_wheel2', 'prism', 'focus',
                'zoom', 'frost', 'iris', 'animation')):
            cats.add('optical')
        if 'shutter' in cm or 'strobe_freq' in cm or 'strobe' in cm \
                or ('intensity' in cm and 'speed' in cm):
            cats.add('strobe')
        return cats


# ── Constantes públicas de categorías ─────────────────────────────
CATEGORIES = ('pixel', 'position', 'color', 'intensity', 'optical', 'strobe')


def load_profile(profile_id: str) -> FixtureProfile | None:
    """Carga un profile desde profiles/<profile_id>.json o .gdtf.

    Prioriza el .json (más rápido y específico). Si no existe, intenta
    .gdtf con `loaders.gdtf_profile.load_gdtf_profile()`. Devuelve None
    si ninguno existe.

    Para selección de modo GDTF específico (cuando el fixture tiene varios),
    usar directamente `loaders.gdtf_profile.load_gdtf_profile()`.
    """
    p_json = PROFILES_DIR / f"{profile_id}.json"
    if p_json.is_file():
        with open(p_json, encoding='utf-8') as f:
            return FixtureProfile.from_dict(json.load(f))

    p_gdtf = PROFILES_DIR / f"{profile_id}.gdtf"
    if p_gdtf.is_file():
        try:
            # Import dinámico para soportar tanto importes relativos como desde tests
            try:
                from ..io.loaders.gdtf_profile import load_gdtf_profile
            except (ValueError, ImportError):
                from src.io.loaders.gdtf_profile import load_gdtf_profile
            return load_gdtf_profile(p_gdtf, profile_id=profile_id)
        except Exception as e:
            _log.warning(f"[fixtures] No se pudo cargar {p_gdtf.name}: {e}")
            return None

    return None


def list_available_profiles() -> list[str]:
    """Lista todos los profiles (JSON + GDTF) en profiles/.
    Los dos formatos se exponen sin sufijo (el stem del archivo).
    Si hay colisión (.json y .gdtf con el mismo nombre), el .json gana en
    `load_profile`.
    """
    if not PROFILES_DIR.is_dir():
        return []
    json_ids = {p.stem for p in PROFILES_DIR.glob('*.json')}
    gdtf_ids = {p.stem for p in PROFILES_DIR.glob('*.gdtf')}
    return sorted(json_ids | gdtf_ids)


def get_profile_source(profile_id: str) -> str | None:
    """Devuelve 'json', 'gdtf' o None según qué archivo existe."""
    if (PROFILES_DIR / f"{profile_id}.json").is_file():
        return "json"
    if (PROFILES_DIR / f"{profile_id}.gdtf").is_file():
        return "gdtf"
    return None


# ───────────────────────────────────────────────────────────────
# Fixture — INSTANCIA en el rig
# ───────────────────────────────────────────────────────────────

@dataclass
class Fixture:
    fixture_id: str                 # 'bar_0', 'mover_stage_l', 'dimmer_back_1'
    profile_id: str                 # referencia al FixtureProfile
    universe: int                   # universo DMX (1-based, igual que Art-Net)
    dmx_start: int                  # canal DMX inicial (1-512)
    # Posición física (metros, Y=up, X=lateral, Z=profundidad)
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    label: str = ""
    # Para compatibilidad con código viejo que indexa por entero:
    legacy_bar_idx: int | None = None
    # Para Art-Net WLED: cuando el fixture habla con un WLED, hay una IP.
    # Si es None, se asume que el universo se enruta a un nodo Art-Net
    # configurado externamente.
    target_ip: str | None = None
    # v1.7 Fase 4 — Overrides manuales de canales (0..1 normalizado).
    # Si una entrada existe, pisa el valor que generen los clips channel-level.
    # Útil para los sliders del Patch Panel (modo manual) y para
    # `set_fixture_channel` desde MCP. Vacío = sin overrides (modo auto).
    manual_channels: dict[str, float] = field(default_factory=dict)
    # J1 — Posición normalizada en el canvas de patch 2D (0.0..1.0).
    # None si el usuario no ha movido el fixture manualmente (usa auto-layout).
    patch_x: float | None = None
    patch_y: float | None = None
    # J2 — Override del kind del profile ('dimmer', 'rgb', 'moving_head', 'strobe',
    # 'led_strip'). None = usa profile.kind. Permite cambiar el modo de renderizado
    # DMX sin reemplazar el profile completo.
    kind_override: str | None = None
    # Editor de fixture (ROADMAP v4): notas libres, mapa de canales personalizado,
    # altura física en metros (persiste como `y` en rig_layout.json).
    notes: str | None = None
    channel_map: list[dict] | None = None   # [{ch: int, role: str}]
    height_m: float | None = None

    def to_dict(self):
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Fixture:
        # tuples vienen como listas en JSON
        px = d.get('patch_x')
        py = d.get('patch_y')
        hm = d.get('height_m')
        return cls(
            fixture_id=d['fixture_id'],
            profile_id=d['profile_id'],
            universe=int(d['universe']),
            dmx_start=int(d['dmx_start']),
            position=tuple(d.get('position', (0.0, 0.0, 0.0))),
            rotation=tuple(d.get('rotation', (0.0, 0.0, 0.0))),
            label=d.get('label', ''),
            legacy_bar_idx=d.get('legacy_bar_idx'),
            target_ip=d.get('target_ip'),
            manual_channels=dict(d.get('manual_channels', {})),
            patch_x=float(px) if px is not None else None,
            patch_y=float(py) if py is not None else None,
            kind_override=d.get('kind_override'),
            notes=d.get('notes'),
            channel_map=d.get('channel_map'),
            height_m=float(hm) if hm is not None else None,
        )


# ───────────────────────────────────────────────────────────────
# FixtureRig — colección de fixtures
# ───────────────────────────────────────────────────────────────

class FixtureRig:
    """Gestor del rig completo: fixtures + profiles cargados + persistencia."""

    def __init__(self, fixtures: list[Fixture] | None = None):
        self.fixtures: list[Fixture] = fixtures or []
        self._profile_cache: dict[str, FixtureProfile] = {}

    # ── Profile helpers ────────────────────────────────────────
    def get_profile(self, profile_id: str) -> FixtureProfile | None:
        if profile_id not in self._profile_cache:
            prof = load_profile(profile_id)
            if prof is None:
                return None
            self._profile_cache[profile_id] = prof
        return self._profile_cache[profile_id]

    # ── Lookup ─────────────────────────────────────────────────
    def by_id(self, fixture_id: str) -> Fixture | None:
        return next((f for f in self.fixtures if f.fixture_id == fixture_id), None)

    def by_legacy_bar(self, bar_idx: int) -> Fixture | None:
        return next((f for f in self.fixtures if f.legacy_bar_idx == bar_idx), None)

    def by_universe(self, universe: int) -> list[Fixture]:
        return [f for f in self.fixtures if f.universe == universe]

    def universes(self) -> list[int]:
        return sorted(set(f.universe for f in self.fixtures))

    # ── Persistencia ───────────────────────────────────────────
    def save(self, path=DEFAULT_RIG_FILE):
        data = {
            'version': 1,
            'fixtures': [f.to_dict() for f in self.fixtures],
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path=DEFAULT_RIG_FILE) -> FixtureRig:
        p = Path(path)
        if not p.is_file():
            return cls()
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        fixtures = [Fixture.from_dict(d) for d in data.get('fixtures', [])]
        return cls(fixtures)


# ───────────────────────────────────────────────────────────────
# Factory: construir el rig por defecto (10 barras WLED actuales)
# ───────────────────────────────────────────────────────────────

DEFAULT_WLED_IPS = [
    '192.168.1.201', '192.168.1.202', '192.168.1.203', '192.168.1.204',
    '192.168.1.205', '192.168.1.206', '192.168.1.207', '192.168.1.208',
    '192.168.1.209', '192.168.1.210',
]

# Layout físico: 5 IZQ + gap 4m + 5 DER (X=lateral, Y=altura, Z=profundidad)
DEFAULT_WLED_POSITIONS = [
    (-5.0, 1.0, 0.0), (-4.0, 1.0, 0.0), (-3.0, 1.0, 0.0),
    (-2.0, 1.0, 0.0), (-1.0, 1.0, 0.0),
    ( 1.0, 1.0, 0.0), ( 2.0, 1.0, 0.0), ( 3.0, 1.0, 0.0),
    ( 4.0, 1.0, 0.0), ( 5.0, 1.0, 0.0),
]


def build_default_wled_rig() -> FixtureRig:
    """Reproduce el rig actual de 10 barras WLED."""
    fixtures = []
    for i in range(10):
        fixtures.append(Fixture(
            fixture_id=f'bar_{i}',
            profile_id='wled_strip_93',
            universe=i + 1,             # universos 1..10
            dmx_start=1,
            position=DEFAULT_WLED_POSITIONS[i],
            rotation=(0.0, 0.0, 0.0),
            label=f'Bar {i:02d}',
            legacy_bar_idx=i,
            target_ip=DEFAULT_WLED_IPS[i],
        ))
    return FixtureRig(fixtures)


# ───────────────────────────────────────────────────────────────
# Self-test
# ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _log.info("=== fixtures.py self-test ===")
    _log.info(f"Profiles disponibles: {list_available_profiles()}")

    rig = build_default_wled_rig()
    _log.info(f"Rig por defecto: {len(rig.fixtures)} fixtures")
    _log.info(f"Universos: {rig.universes()}")
    _log.info(f"Primero: {rig.fixtures[0]}")
    _log.info(f"Por legacy_bar(5): {rig.by_legacy_bar(5)}")

    prof = rig.get_profile('wled_strip_93')
    _log.info(f"Profile wled_strip_93: {prof}")

    # Test save/load
    tmp = PROJECT_DIR / 'fixtures_test.json'
    rig.save(tmp)
    rig2 = FixtureRig.load(tmp)
    assert len(rig2.fixtures) == len(rig.fixtures)
    tmp.unlink()
    _log.info("[OK] save/load test pasado")
