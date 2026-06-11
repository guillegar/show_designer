"""
Timeline model - clips, tracks, persistencia.

Un Clip = una instancia de un Effect aplicada en un track durante un rango
temporal con parámetros propios. Persiste a JSON.

Esto es el modelo subyacente del editor estilo Adobe.
"""
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Any, List, Optional
from uuid import uuid4

from src._paths import PROJECT_DIR
TIMELINE_FILE = PROJECT_DIR / 'show_timeline.json'

NUM_TRACKS = 10   # Una pista por barra (0-9). Track 10+ podría usarse para "global all bars" en futuras versiones.


@dataclass
class BarGroup:
    """
    Grupo de barras para asignación colectiva de efectos.

    Soporta dos tipos:
      - Grupo simple: lista de barras (campo `bars`).
      - Grupo-de-grupos: lista de otros grupos por nombre (campo `subgroups`),
        cuyas barras se resuelven recursivamente al renderizar.
    Un mismo BarGroup puede tener AMBAS cosas (ej: subgroups=['IZQ','DER'] +
    bars=[]) — es lo que indica que es un "set" de otros grupos.
    """
    name: str
    bars: List[int] = field(default_factory=list)
    color: str = "#888888"
    subgroups: List[str] = field(default_factory=list)  # nombres de otros grupos

    @property
    def is_set(self) -> bool:
        """True si este grupo está compuesto por otros (grupos-de-grupos)."""
        return bool(self.subgroups)

    def resolve_bars(self, all_groups: List['BarGroup'],
                     _visited: Optional[set] = None) -> List[int]:
        """
        Resuelve TODAS las barras finales, expandiendo subgrupos recursivamente.
        Evita ciclos infinitos con un set de nombres visitados.
        """
        if _visited is None:
            _visited = set()
        if self.name in _visited:
            return []
        _visited.add(self.name)
        result = set(self.bars)
        for sub_name in self.subgroups:
            for g in all_groups:
                if g.name == sub_name:
                    result.update(g.resolve_bars(all_groups, _visited))
                    break
        return sorted(result)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'bars': list(self.bars),
            'color': self.color,
            'subgroups': list(self.subgroups),
        }

    @classmethod
    def from_dict(cls, d) -> 'BarGroup':
        return cls(
            name=d['name'],
            bars=list(d.get('bars', [])),
            color=d.get('color', '#888888'),
            subgroups=list(d.get('subgroups', [])),
        )


@dataclass(eq=False)  # eq=False ⇒ usa identity hash; mantiene a Clip hashable
class Clip:
    """Una instancia de Effect en el timeline."""
    track: int               # 0..9 = barra fisica
    start_ms: int
    end_ms: int
    effect_id: int           # 0..50
    scope: str = "per_bar"   # "per_bar" | "global" (afecta la renderizacion)
    params: Dict[str, Any] = field(default_factory=dict)   # {'hue': 200, 'saturation': 0.9, ...}
    label: str = ""          # nombre opcional que muestra el clip
    color: str = "#3a7acc"   # color del rectangulo en el track (hex)
    layer: int = 0           # 0=base, 1=layer1, ... (sub-fila dentro del track)
    locked: bool = False     # si True no se puede mover/redimensionar/borrar
    muted: bool = False      # si True el clip no se renderiza (silenciado individual)
    # v1.7 Fase 5 — clips de canal (no-pixel)
    category: str = 'pixel'               # 'pixel' | 'position' | 'color' | 'intensity' | 'optical' | 'strobe'
    channel_effect_id: Optional[str] = None  # ID del ChannelEffect (solo si category != 'pixel')
    # v1.10 — banco de presets: si está set, el clip RESUELVE su efecto+params
    # del preset (enlace vivo: editar el preset cambia todos sus clips).
    preset_id: Optional[str] = None
    # v1.10 — ANALYSIS hallazgo 2: id ESTABLE y persistido. Reemplaza id(self),
    # que no era estable entre sesiones y CPython puede reusar tras GC.
    uid: str = field(default_factory=lambda: uuid4().hex[:12])

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def contains(self, time_ms: int) -> bool:
        return self.start_ms <= time_ms < self.end_ms

    def to_dict(self):
        """Serializa el clip a dict compatible con JSON-RPC.

        `id` = `uid` (estable y persistido) → es la clave que usan los clientes
        (Claude/web) para referenciar el clip en move_clip/delete_clip/etc.
        Se incluye también `uid` explícito para claridad/persistencia.
        """
        return {
            "id": self.uid,
            "uid": self.uid,
            "track": self.track,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "effect_id": self.effect_id,
            "scope": self.scope,
            "label": self.label,
            "color": self.color,
            "layer": self.layer,
            "locked": self.locked,
            "muted": self.muted,
            "params": dict(self.params) if self.params else {},
            "category": self.category,
            "channel_effect_id": self.channel_effect_id,
            "preset_id": self.preset_id,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            track=int(d['track']),
            start_ms=int(d['start_ms']),
            end_ms=int(d['end_ms']),
            effect_id=int(d.get('effect_id', 0)),
            scope=d.get('scope', 'per_bar'),
            params=dict(d.get('params', {})),
            label=d.get('label', ''),
            color=d.get('color', '#3a7acc'),
            layer=int(d.get('layer', 0)),
            locked=bool(d.get('locked', False)),
            muted=bool(d.get('muted', False)),
            category=d.get('category', 'pixel'),
            channel_effect_id=d.get('channel_effect_id'),
            preset_id=d.get('preset_id'),
            # Migración: usa el uid persistido; si no hay (shows viejos cuyo "id"
            # era el int de id(self)), genera uno nuevo estable.
            uid=d.get('uid') or (d['id'] if isinstance(d.get('id'), str)
                                 else uuid4().hex[:12]),
        )


@dataclass
class CuePoint:
    """Punto de disparo en vivo (Performance Mode estilo FL Studio)."""
    slot: int            # 1..9 (mapeado a tecla numérica)
    time_ms: int = -1    # -1 = vacío / sin asignar
    name: str = ""
    color: str = "#4a90e2"

    def is_set(self) -> bool:
        return self.time_ms >= 0

    def to_dict(self):
        return {'slot': self.slot, 'time_ms': self.time_ms,
                'name': self.name, 'color': self.color}

    @classmethod
    def from_dict(cls, d):
        return cls(slot=int(d['slot']), time_ms=int(d.get('time_ms', -1)),
                   name=d.get('name', ''), color=d.get('color', '#4a90e2'))


class Timeline:
    """Conjunto de clips + persistencia."""

    def __init__(self, clips: Optional[List[Clip]] = None,
                 duration_ms: int = 165_000,
                 groups: Optional[List[BarGroup]] = None,
                 cue_points: Optional[List[CuePoint]] = None):
        self.clips: List[Clip] = clips or []
        self.duration_ms = duration_ms
        self.groups: List[BarGroup] = groups or []
        # 9 cue points por defecto (todos vacíos)
        self.cue_points: List[CuePoint] = cue_points or [
            CuePoint(slot=i) for i in range(1, 10)
        ]

    def add(self, clip: Clip):
        self.clips.append(clip)

    def remove(self, clip: Clip):
        if clip in self.clips:
            self.clips.remove(clip)

    def clips_on_track(self, track: int) -> List[Clip]:
        return [c for c in self.clips if c.track == track]

    def active_clips_at(self, time_ms: int) -> List[Clip]:
        """Clips que cubren ese instante (puede haber varios por track si se solapan)."""
        return [c for c in self.clips if c.contains(time_ms)]

    def save(self, path=TIMELINE_FILE):
        data = {
            'version': 2,  # v2: incluye cue_points
            'duration_ms': self.duration_ms,
            'clips': [c.to_dict() for c in self.clips],
            'groups': [g.to_dict() for g in self.groups],
            'cue_points': [c.to_dict() for c in self.cue_points],
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path=TIMELINE_FILE) -> 'Timeline':
        p = Path(path)
        if not p.is_file():
            return cls()
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        clips  = [Clip.from_dict(d)  for d in data.get('clips',  [])]
        groups = [BarGroup.from_dict(d) for d in data.get('groups', [])]
        cues_raw = data.get('cue_points', [])
        cues = [CuePoint.from_dict(d) for d in cues_raw] if cues_raw else None
        return cls(clips, int(data.get('duration_ms', 165_000)), groups, cues)


def make_default_groups() -> List[BarGroup]:
    """
    Grupos por defecto para layout 5+gap+5 (10 barras).
    Incluye grupos simples y grupos-de-grupos.
    """
    return [
        # Grupos simples (subdivisiones físicas / artísticas del setup)
        BarGroup(name='IZQ',        bars=[0, 1, 2, 3, 4],       color='#ff6666'),
        BarGroup(name='DER',        bars=[5, 6, 7, 8, 9],       color='#6699ff'),
        BarGroup(name='EXTREMOS',   bars=[0, 9],                color='#ffdd55'),
        BarGroup(name='CENTRO',     bars=[4, 5],                color='#55ffaa'),
        BarGroup(name='PARES',      bars=[0, 2, 4, 6, 8],       color='#cc88ff'),
        BarGroup(name='IMPARES',    bars=[1, 3, 5, 7, 9],       color='#ff88cc'),
        # Grupos-de-grupos (sets)
        BarGroup(name='TODO',       subgroups=['IZQ', 'DER'],    color='#ffffff'),
        BarGroup(name='BORDES+CENTRO', subgroups=['EXTREMOS', 'CENTRO'], color='#ffaa33'),
    ]


def make_demo_timeline(duration_ms: int = 273_300) -> Timeline:
    """Genera un timeline de prueba para arrancar — un clip por track durante toda la canción."""
    tl = Timeline(duration_ms=duration_ms)
    # 10 clips, uno por track, todos con effect_id distinto
    for i in range(NUM_TRACKS):
        clip = Clip(
            track=i,
            start_ms=0,
            end_ms=duration_ms,
            effect_id=(i * 5) % 51,   # repartir efectos por barra
            scope='per_bar',
            label=f'demo bar {i}',
            color=['#cc3a3a', '#cc7a3a', '#ccbb3a', '#7acc3a', '#3acc7a',
                   '#3aaacc', '#3a7acc', '#7a3acc', '#cc3aaa', '#cc3a7a'][i],
        )
        tl.add(clip)
    return tl


if __name__ == '__main__':
    # Demo: crear timeline de prueba y guardarlo
    tl = make_demo_timeline()
    print(f"Timeline con {len(tl.clips)} clips. Duración: {tl.duration_ms/1000:.1f}s")
    for c in tl.clips:
        print(f"  Track {c.track}: effect_id={c.effect_id}, {c.start_ms}–{c.end_ms} ms")
    tl.save()
    print(f"Guardado en {TIMELINE_FILE.name}")
