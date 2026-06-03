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
