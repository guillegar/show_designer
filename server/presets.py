"""
presets.py — Banco de efectos (presets) con enlace vivo.

Un **preset** es una versión configurada de un efecto base:
    { preset_id, name, base_effect_id, family, params, color, scope }

Los clips del show apuntan a un preset por `preset_id`. Al renderizar, el clip
RESUELVE su efecto+params del preset → editar el preset cambia TODOS sus clips
(enlace vivo). De un tipo base (p.ej. `color_flash`) se crean varios presets
("Flash Rojo" hue=0, "Flash Verde" hue=120).

Ámbitos (el usuario eligió AMBOS):
    - global  → presets.json en la raíz del repo (reutilizable entre shows)
    - project → projects/<slug>/presets.json (paleta del show)

`PresetBank.list()` devuelve la unión (cada preset lleva su `scope`). Si un id se
repite, el del proyecto pisa al global.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).parent.parent
GLOBAL_FILE = _ROOT / "presets.json"


@dataclass
class EffectPreset:
    preset_id: str
    name: str
    kind: str = "pixel"                       # 'pixel' | 'channel'
    base_effect_id: int = 0                    # efecto pixel (kind='pixel')
    channel_effect_id: Optional[str] = None    # efecto de canal (kind='channel')
    category: str = ""                         # categoría del efecto de canal
    family: str = ""                           # familia (pixel) o = category (channel) para agrupar
    params: Dict[str, Any] = field(default_factory=dict)
    param_links: List[Dict[str, Any]] = field(default_factory=list)  # A1 links preconfigured
    color: str = "#3a7acc"
    scope: str = "project"          # 'global' | 'project' (ámbito de almacenamiento)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EffectPreset":
        return cls(
            preset_id=d.get("preset_id") or uuid.uuid4().hex[:12],
            name=d.get("name", "Preset"),
            kind=d.get("kind", "pixel"),
            base_effect_id=int(d.get("base_effect_id", 0)),
            channel_effect_id=d.get("channel_effect_id"),
            category=d.get("category", ""),
            family=d.get("family", ""),
            params=dict(d.get("params", {})),
            param_links=list(d.get("param_links", [])),
            color=d.get("color", "#3a7acc"),
            scope=d.get("scope", "project"),
        )


# Presets de fábrica (ámbito global) — el banco no nace vacío.
# (hue 0=rojo, 120=verde, 240=azul, 300=magenta, 60=ámbar)
def _seed_global(library) -> List[EffectPreset]:
    def eid(name: str, default: int) -> int:
        for i, eff in library.effects.items():
            if getattr(eff, "name", "") == name:
                return i
        return default
    fam = {}
    for i, eff in library.effects.items():
        fam[i] = getattr(eff, "family", "")
    seeds = [
        ("Flash Blanco", "white_flash", 0, {}, "#f3f4f6"),
        ("Flash Rojo", "color_flash", 1, {"hue": 0}, "#f0654b"),
        ("Flash Verde", "color_flash", 1, {"hue": 120}, "#1fe39a"),
        ("Flash Azul", "color_flash", 1, {"hue": 220}, "#5aa9f0"),
        ("Strobe", "strobe", 3, {}, "#ffffff"),
        ("Wave Azul", "horizontal_wave", 10, {"hue": 210}, "#5aa9f0"),
        ("Wave Arcoíris", "rainbow_wave", 13, {}, "#d569e0"),
        ("Gradiente Magenta", "linear_gradient", 20, {"hue": 300}, "#d569e0"),
        ("Chase Verde", "chase", 35, {"hue": 140}, "#3fe08a"),
        ("Sparkle", "sparkle", 34, {}, "#e0c05a"),
        ("Breathing Ámbar", "breathing", 32, {"hue": 45}, "#e0c05a"),
        ("Hue Cycle", "hue_cycle", 40, {}, "#a779f0"),
    ]
    out = []
    for name, eff_name, default_id, params, color in seeds:
        i = eid(eff_name, default_id)
        out.append(EffectPreset(
            preset_id=uuid.uuid4().hex[:12], name=name, kind="pixel", base_effect_id=i,
            family=fam.get(i, ""), params=params, color=color, scope="global",
        ))
    # Presets de canal (movers / fixtures no-LED). channel_effect_id estables.
    ch_seeds = [
        ("Mover Círculo", "pos_circle", "position", {"speed": 0.3, "radius": 0.25}, "#a779f0"),
        ("Mover Ocho", "pos_figure8", "position", {"speed": 0.3, "radius": 0.25}, "#a779f0"),
        ("Mover Barrido", "pos_pan_sweep", "position", {"speed": 0.2}, "#5aa9f0"),
        ("Color Arcoíris", "col_rainbow", "color", {"speed": 0.2}, "#d569e0"),
        ("Color Cálido-Frío", "col_warm_cold", "color", {"speed": 0.2}, "#e0c05a"),
        ("Dim Pulso", "dim_pulse", "intensity", {"speed": 0.5}, "#1fe39a"),
        ("Dim Respiración", "dim_breath", "intensity", {"speed": 0.3}, "#1fe39a"),
        ("Strobe", "str_flash", "strobe", {"freq_hz": 12}, "#ffffff"),
        ("Gobo Spin", "opt_gobo_spin", "optical", {"speed": 0.4}, "#f0654b"),
    ]
    for name, ch_id, cat, params, color in ch_seeds:
        out.append(EffectPreset(
            preset_id=uuid.uuid4().hex[:12], name=name, kind="channel",
            channel_effect_id=ch_id, category=cat, family=cat,
            params=params, color=color, scope="global",
        ))
    return out


def _seed_f3_effects(library) -> List[EffectPreset]:
    """30 presets curados para los 10 efectos F1 (IDs 1010-1019). 3 por efecto."""
    fam = {i: getattr(eff, "family", "") for i, eff in library.effects.items()}

    def p(name, eid, params, color, param_links=None):
        return EffectPreset(
            preset_id=uuid.uuid4().hex[:12], name=name, kind="pixel",
            base_effect_id=eid, family=fam.get(eid, ""),
            params=params, param_links=param_links or [], color=color, scope="global",
        )

    return [
        # ── gradient_sweep (1010) ───────────────────────────────────────────
        p("Aurora Boreal",    1010, {"color1_r": 0,   "color1_g": 50,  "color1_b": 255,
                                     "color2_r": 128,  "color2_g": 0,   "color2_b": 255,
                                     "speed": 0.5, "offset": 0.0}, "#3244e8"),
        p("Amanecer",         1010, {"color1_r": 255, "color1_g": 30,  "color1_b": 0,
                                     "color2_r": 255,  "color2_g": 180, "color2_b": 0,
                                     "speed": 0.3, "offset": 0.0}, "#e87020"),
        p("Crepúsculo",       1010, {"color1_r": 255, "color1_g": 100, "color1_b": 0,
                                     "color2_r": 220,  "color2_g": 0,   "color2_b": 180,
                                     "speed": 0.7, "offset": 0.5}, "#e05080"),

        # ── pixel_chase (1011) ──────────────────────────────────────────────
        p("Hormiga Roja",     1011, {"r": 255, "g": 0,   "b": 0,
                                     "speed": 60.0, "width": 4.0, "mode": "bounce", "tail_decay": 0.9}, "#e03030"),
        p("Luz de Policía",   1011, {"r": 0,   "g": 100, "b": 255,
                                     "speed": 80.0, "width": 3.0, "mode": "bounce", "tail_decay": 0.7}, "#2266e8"),
        p("Lluvia de Neón",   1011, {"r": 0,   "g": 255, "b": 100,
                                     "speed": 120.0, "width": 2.0, "mode": "cycle", "tail_decay": 0.85}, "#00e860"),

        # ── theater_chase (1012) ────────────────────────────────────────────
        p("Marquesina Dorada", 1012, {"r": 255, "g": 200, "b": 0,
                                      "group_size": 3, "gap_size": 3, "speed": 3.0}, "#e8c000"),
        p("Teatro Azul",       1012, {"r": 0,   "g": 100, "b": 255,
                                      "group_size": 5, "gap_size": 3, "speed": 1.5}, "#0066e8"),
        p("Rock & Roll",       1012, {"r": 220, "g": 0,   "b": 0,
                                      "group_size": 2, "gap_size": 2, "speed": 6.0}, "#dd0000"),

        # ── twinkle (1013) ──────────────────────────────────────────────────
        p("Cielo Estrellado", 1013, {"r": 150, "g": 180, "b": 255,
                                     "density": 0.2, "speed": 2.0, "min_brightness": 0.0}, "#96b4ff"),
        p("Nieve",            1013, {"r": 255, "g": 255, "b": 255,
                                     "density": 0.15, "speed": 1.5, "min_brightness": 0.1}, "#f0f0ff"),
        p("Polvo de Hadas",   1013, {"r": 255, "g": 100, "b": 220,
                                     "density": 0.3, "speed": 5.0, "min_brightness": 0.0}, "#e064dc"),

        # ── fire (1014) ─────────────────────────────────────────────────────
        p("Hoguera",          1014, {"intensity": 0.6, "cooling": 0.5, "sparking": 0.5}, "#e87020"),
        p("Llama Intensa",    1014, {"intensity": 0.9, "cooling": 0.2, "sparking": 0.8}, "#ff4400"),
        p("Fuego Suave",      1014, {"intensity": 0.4, "cooling": 0.7, "sparking": 0.3}, "#c06030"),

        # ── strobe_color (1015) ─────────────────────────────────────────────
        p("Estrobo Blanco",   1015, {"r": 255, "g": 255, "b": 255,
                                     "rate_hz": 8.0,  "duty_cycle": 0.5}, "#ffffff"),
        p("Pulso Rojo",       1015, {"r": 255, "g": 0,   "b": 0,
                                     "rate_hz": 4.0,  "duty_cycle": 0.7}, "#cc0000"),
        p("Flash Azul",       1015, {"r": 0,   "g": 80,  "b": 255,
                                     "rate_hz": 15.0, "duty_cycle": 0.3}, "#0050ff"),

        # ── vu_meter (1016) ─────────────────────────────────────────────────
        p("VU Verde-Rojo",    1016, {"r_low": 0, "g_low": 255, "b_low": 0,
                                     "r_high": 255, "g_high": 0, "b_high": 0,
                                     "smoothing": 0.7, "peak_hold_ms": 500.0}, "#40dd40"),
        p("VU Azul-Blanco",   1016, {"r_low": 0, "g_low": 80, "b_low": 255,
                                     "r_high": 255, "g_high": 255, "b_high": 255,
                                     "smoothing": 0.6, "peak_hold_ms": 300.0}, "#0050ff"),
        p("VU Cian-Magenta",  1016, {"r_low": 0, "g_low": 220, "b_low": 220,
                                     "r_high": 220, "g_high": 0, "b_high": 220,
                                     "smoothing": 0.8, "peak_hold_ms": 800.0}, "#00dcdc"),

        # ── rainbow_wave (1017) ─────────────────────────────────────────────
        p("Arcoíris Rápido",  1017, {"speed": 3.0, "saturation": 1.0, "value": 1.0, "reverse": False}, "#d569e0"),
        p("Arcoíris Suave",   1017, {"speed": 0.5, "saturation": 0.9, "value": 0.8, "reverse": False}, "#a080e0"),
        p("Arcoíris Inverso", 1017, {"speed": 1.5, "saturation": 1.0, "value": 1.0, "reverse": True},  "#e0a030"),

        # ── scanner (1018) ──────────────────────────────────────────────────
        p("Radar Blanco",     1018, {"r": 255, "g": 255, "b": 255,
                                     "speed": 0.8, "width": 10.0, "mode": "sin",    "brightness_env": False}, "#f0f0f0"),
        p("Scanner Rojo",     1018, {"r": 255, "g": 0,   "b": 0,
                                     "speed": 1.5, "width": 6.0,  "mode": "bounce", "brightness_env": False}, "#dd2020"),
        p("Disco Azul",       1018, {"r": 0,   "g": 150, "b": 255,
                                     "speed": 2.5, "width": 15.0, "mode": "sin",    "brightness_env": True},  "#0096ff"),

        # ── breathing (1019) ────────────────────────────────────────────────
        p("Respiro Blanco",   1019, {"r": 255, "g": 255, "b": 255,
                                     "rate_hz": 0.3, "min_brightness": 0.0,
                                     "audio_reactive": False, "audio_source": "rms"}, "#f0f0f0"),
        p("Pulso Ámbar",      1019, {"r": 255, "g": 150, "b": 0,
                                     "rate_hz": 1.0, "min_brightness": 0.1,
                                     "audio_reactive": True, "audio_source": "rms"}, "#e09600",
          param_links=[{"param": "rate_hz", "source": "rms", "gain": 2.0, "offset": 0.5,
                        "curve": "linear", "min_v": 0.1, "max_v": 3.0}]),
        p("Respiro Verde",    1019, {"r": 0,   "g": 200, "b": 80,
                                     "rate_hz": 0.5, "min_brightness": 0.05,
                                     "audio_reactive": False, "audio_source": "rms"}, "#00c850"),
    ]


class PresetBank:
    def __init__(self, library, channel_lib=None, project_file: Optional[Path] = None):
        self.library = library
        self.channel_lib = channel_lib
        self.project_file = project_file
        self._global: List[EffectPreset] = []
        self._project: List[EffectPreset] = []
        self._load()

    # ── carga / persistencia ─────────────────────────────────────────────────
    def _load(self):
        if GLOBAL_FILE.is_file():
            self._global = [EffectPreset.from_dict(d) for d in _read(GLOBAL_FILE)]
        else:
            self._global = _seed_global(self.library)
            _write(GLOBAL_FILE, [p.to_dict() for p in self._global])
        for p in self._global:
            p.scope = "global"
        # Migración F3: añadir presets de efectos 1010-1019 si aún no existen
        covered = {p.base_effect_id for p in self._global if p.kind == "pixel"}
        f3_ids = set(range(1010, 1020))
        missing = f3_ids - covered
        if missing:
            new_presets = [p for p in _seed_f3_effects(self.library) if p.base_effect_id in missing]
            self._global.extend(new_presets)
            _write(GLOBAL_FILE, [p.to_dict() for p in self._global])
        if self.project_file and self.project_file.is_file():
            self._project = [EffectPreset.from_dict(d) for d in _read(self.project_file)]
        for p in self._project:
            p.scope = "project"

    def _save_global(self):
        _write(GLOBAL_FILE, [p.to_dict() for p in self._global])

    def _save_project(self):
        if self.project_file:
            self.project_file.parent.mkdir(parents=True, exist_ok=True)
            _write(self.project_file, [p.to_dict() for p in self._project])

    # ── consulta ─────────────────────────────────────────────────────────────
    def list(self) -> List[EffectPreset]:
        # proyecto pisa global si coincide id
        by_id = {p.preset_id: p for p in self._global}
        for p in self._project:
            by_id[p.preset_id] = p
        return list(by_id.values())

    def get(self, preset_id: str) -> Optional[EffectPreset]:
        for p in self._project:
            if p.preset_id == preset_id:
                return p
        for p in self._global:
            if p.preset_id == preset_id:
                return p
        return None

    # ── CRUD ─────────────────────────────────────────────────────────────────
    def _channel_category(self, ch_id: str) -> str:
        if self.channel_lib and ch_id:
            eff = self.channel_lib.get(ch_id)
            if eff:
                return getattr(eff, "category", "")
        return ""

    def create(self, name: str, params: dict, color: str = "#3a7acc",
               scope: str = "project", kind: str = "pixel",
               base_effect_id: int = 0, channel_effect_id: Optional[str] = None) -> EffectPreset:
        if kind == "channel":
            cat = self._channel_category(channel_effect_id or "")
            p = EffectPreset(preset_id=uuid.uuid4().hex[:12], name=name, kind="channel",
                             channel_effect_id=channel_effect_id, category=cat, family=cat,
                             params=dict(params or {}), color=color, scope=scope)
        else:
            fam = ""
            eff = self.library.get_effect(int(base_effect_id))
            if eff:
                fam = getattr(eff, "family", "")
            p = EffectPreset(preset_id=uuid.uuid4().hex[:12], name=name, kind="pixel",
                             base_effect_id=int(base_effect_id), family=fam,
                             params=dict(params or {}), color=color, scope=scope)
        if scope == "global":
            self._global.append(p); self._save_global()
        else:
            self._project.append(p); self._save_project()
        return p

    def update(self, preset_id: str, **fields) -> Optional[EffectPreset]:
        p = self.get(preset_id)
        if p is None:
            return None
        if "name" in fields and fields["name"] is not None:
            p.name = fields["name"]
        if "params" in fields and fields["params"] is not None:
            p.params = dict(fields["params"])
        if "color" in fields and fields["color"] is not None:
            p.color = fields["color"]
        if "base_effect_id" in fields and fields["base_effect_id"] is not None:
            p.base_effect_id = int(fields["base_effect_id"])
            eff = self.library.get_effect(p.base_effect_id)
            p.family = getattr(eff, "family", "") if eff else ""
        if "channel_effect_id" in fields and fields["channel_effect_id"] is not None:
            p.channel_effect_id = fields["channel_effect_id"]
            p.category = self._channel_category(p.channel_effect_id)
            p.family = p.category
        if p.scope == "global":
            self._save_global()
        else:
            self._save_project()
        return p

    def delete(self, preset_id: str) -> bool:
        for lst, save in ((self._project, self._save_project), (self._global, self._save_global)):
            for i, p in enumerate(lst):
                if p.preset_id == preset_id:
                    lst.pop(i); save(); return True
        return False


def _read(path: Path) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _write(path: Path, data: list):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
