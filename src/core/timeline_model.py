"""
Timeline model - clips, tracks, persistencia.

Un Clip = una instancia de un Effect aplicada en un track durante un rango
temporal con parámetros propios. Persiste a JSON.

Esto es el modelo subyacente del editor estilo Adobe.
"""
import json
import os
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
    # A1 — Modulación: vínculos param ← señal del análisis
    param_links: List[Dict[str, Any]] = field(default_factory=list)
    # A4 — Micro-eventos: overrides puntuales en instantes relativos al clip
    events: List[Dict[str, Any]] = field(default_factory=list)
    # G3 — Channel effects (lista de configs: [{"id": str, "params": dict}])
    # Complementa a channel_effect_id/params (que sigue siendo el efecto principal legacy).
    channel_effects: List[Dict[str, Any]] = field(default_factory=list)

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
            "param_links": list(self.param_links) if self.param_links else [],
            "events": list(self.events) if self.events else [],
            "channel_effects": list(self.channel_effects) if self.channel_effects else [],
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
            param_links=list(d.get('param_links', [])),
            events=list(d.get('events', [])),
            channel_effects=list(d.get('channel_effects', [])),
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


_VALID_MARKER_CATEGORIES = frozenset(
    {"intro", "verso", "estribillo", "bridge", "outro", "custom"}
)


@dataclass
class Marker:
    """Marcador de timeline con nombre, color y categoría (I2, ROADMAP v4)."""
    t_ms: int
    name: str = ""
    color: str = "#888888"
    category: str = "custom"  # intro|verso|estribillo|bridge|outro|custom

    def to_dict(self) -> dict:
        return {
            't_ms': self.t_ms,
            'time_ms': self.t_ms,   # alias para compatibilidad con el frontend
            'name': self.name,
            'color': self.color,
            'category': self.category,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'Marker':
        t_ms = int(d.get('t_ms', d.get('time_ms', 0)))
        cat = d.get('category', 'custom')
        if cat not in _VALID_MARKER_CATEGORIES:
            cat = 'custom'
        return cls(t_ms=t_ms, name=d.get('name', ''),
                   color=d.get('color', '#888888'), category=cat)


@dataclass
class Pattern:
    """Bloque reutilizable de clips (A3, ROADMAP v2).

    Los clips almacenan tiempos y tracks RELATIVOS:
      - start_ms / end_ms  → relativos al inicio del pattern (start_ms=0)
      - track              → offset relativo al track del primer clip del grupo original

    Las PatternInstances los expanden a tiempos/tracks absolutos en render time.
    """
    uid: str = field(default_factory=lambda: uuid4().hex[:12])
    name: str = ""
    color: str = "#8855cc"
    clips: List['Clip'] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "name": self.name,
            "color": self.color,
            "clips": [c.to_dict() for c in self.clips],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'Pattern':
        return cls(
            uid=d.get("uid") or uuid4().hex[:12],
            name=d.get("name", ""),
            color=d.get("color", "#8855cc"),
            clips=[Clip.from_dict(c) for c in d.get("clips", [])],
        )


@dataclass
class PatternInstance:
    """Referencia a un Pattern colocada en el timeline (A3, ROADMAP v2).

    start_ms y track_offset son ABSOLUTOS: la expansión aplica
    start_ms + clip.start_ms  y  track_offset + clip.track.
    """
    uid: str = field(default_factory=lambda: uuid4().hex[:12])
    pattern_uid: str = ""
    start_ms: int = 0
    track_offset: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "pattern_uid": self.pattern_uid,
            "start_ms": self.start_ms,
            "track_offset": self.track_offset,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'PatternInstance':
        return cls(
            uid=d.get("uid") or uuid4().hex[:12],
            pattern_uid=d.get("pattern_uid", ""),
            start_ms=int(d.get("start_ms", 0)),
            track_offset=int(d.get("track_offset", 0)),
        )


@dataclass
class CueEntry:
    """Entrada de la CueList — punto accionable de la lista de cues (E1, ROADMAP v3).

    Distinto de CuePoint (marcadores pasivos del timeline): CueEntry es la entidad
    de la lista operativa, con número decimal, crossfade de entrada y auto-follow.
    """
    uid: str              # uuid4 hex[:12]
    number: float         # 1, 1.5, 2… (decimal para insertar entre cues)
    name: str
    t_ms: int             # instante del timeline al que salta
    fade_in_ms: int = 0   # crossfade de entrada (0 = corte seco)
    hold_ms: int = -1     # -1 = esperar GO manual; >= 0 = auto-follow tras N ms
    auto_follow: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "number": self.number,
            "name": self.name,
            "t_ms": self.t_ms,
            "fade_in_ms": self.fade_in_ms,
            "hold_ms": self.hold_ms,
            "auto_follow": self.auto_follow,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'CueEntry':
        return cls(
            uid=d.get("uid") or uuid4().hex[:12],
            number=float(d.get("number", 1.0)),
            name=str(d.get("name", "")),
            t_ms=int(d.get("t_ms", 0)),
            fade_in_ms=int(d.get("fade_in_ms", 0)),
            hold_ms=int(d.get("hold_ms", -1)),
            auto_follow=bool(d.get("auto_follow", False)),
        )


@dataclass
class CueList:
    """Lista de cues operativa (E1, ROADMAP v3). Persistida en show.json como cue_list."""
    entries: List[CueEntry] = field(default_factory=list)  # ordenadas por number
    active_uid: Optional[str] = None                       # cue actualmente activo

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "active_uid": self.active_uid,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'CueList':
        entries = [CueEntry.from_dict(e) for e in d.get("entries", [])]
        return cls(entries=entries, active_uid=d.get("active_uid"))


class Timeline:
    """Conjunto de clips + persistencia.

    Schema v3 (ROADMAP v2, F0.2): añade contenedores para las fases del
    secuenciador. Nacen VACÍOS y cada fase los rellena:
      automation          → lanes de automatización (A2)
      patterns            → patterns reutilizables (A3)
      pattern_instances   → instancias de patterns en el timeline (A3)
      mixer               → estado de master + cadenas por pista (B2)

    Schema v4 (E1, ROADMAP v3): añade cue_list (CueList) para el sistema de
    cues profesional. Migración tolerante: si falta → CueList(entries=[]).

    Regla de versionado: añadir un CAMPO a una entidad existente con default
    tolerante en from_dict NO sube la versión; solo cambios ESTRUCTURALES
    (contenedores nuevos, renombres) la suben.
    """

    SCHEMA_VERSION = 4

    def __init__(self, clips: Optional[List[Clip]] = None,
                 duration_ms: int = 165_000,
                 groups: Optional[List[BarGroup]] = None,
                 cue_points: Optional[List[CuePoint]] = None,
                 automation: Optional[List[Dict]] = None,
                 patterns: Optional[List[Dict]] = None,
                 pattern_instances: Optional[List[Dict]] = None,
                 mixer: Optional[Dict] = None,
                 live_slots: Optional[List[Dict]] = None,
                 cue_list: Optional['CueList'] = None,
                 markers: Optional[List[Marker]] = None):
        self.clips: List[Clip] = clips or []
        self.duration_ms = duration_ms
        self.groups: List[BarGroup] = groups or []
        # 9 cue points por defecto (todos vacíos)
        self.cue_points: List[CuePoint] = cue_points or [
            CuePoint(slot=i) for i in range(1, 10)
        ]
        # v3: contenedores del secuenciador (dicts crudos hasta que su fase
        # los modele — A2/A3/B2/C1 los convertirán en dataclasses propias).
        self.automation: List[Dict] = automation or []
        self.patterns: List[Dict] = patterns or []
        self.pattern_instances: List[Dict] = pattern_instances or []
        self.mixer: Dict = mixer or {}
        # C1: configuración de los 16 slots del performance grid (uid, pattern_uid,
        # key, quantize, mode). El estado _active/_armed NO se persiste.
        self.live_slots: List[Dict] = live_slots or []
        # E1: lista de cues profesional (schema v4). Migración tolerante: si falta → vacía.
        self.cue_list: CueList = cue_list or CueList(entries=[])
        # I2: marcadores de timeline con nombre, color y categoría (ROADMAP v4).
        self.markers: List[Marker] = markers or []

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

    def to_dict(self) -> dict:
        """Serializa a dict (para copia congelada, hash, etc.). Mismo formato que save()."""
        return {
            'version': self.SCHEMA_VERSION,
            'duration_ms': self.duration_ms,
            'clips': [c.to_dict() for c in self.clips],
            'groups': [g.to_dict() for g in self.groups],
            'cue_points': [c.to_dict() for c in self.cue_points],
            'automation': list(self.automation),
            'patterns': list(self.patterns),
            'pattern_instances': list(self.pattern_instances),
            'mixer': dict(self.mixer),
            'live_slots': list(self.live_slots),
            'cue_list': self.cue_list.to_dict(),
            'markers': [m.to_dict() for m in self.markers],
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Timeline':
        """Construye un Timeline desde un dict (inverso de to_dict). Migración tolerante."""
        clips  = [Clip.from_dict(d)  for d in data.get('clips',  [])]
        groups = [BarGroup.from_dict(d) for d in data.get('groups', [])]
        cues_raw = data.get('cue_points', [])
        cues = [CuePoint.from_dict(d) for d in cues_raw] if cues_raw else None
        # E1: migración tolerante v3→v4: si falta cue_list → CueList vacía
        cue_list_raw = data.get('cue_list')
        cue_list = CueList.from_dict(cue_list_raw) if cue_list_raw else CueList(entries=[])
        # I2: migración tolerante — si falta markers → lista vacía
        markers_raw = data.get('markers', [])
        markers = [Marker.from_dict(d) for d in markers_raw]
        return cls(clips, int(data.get('duration_ms', 165_000)), groups, cues,
                   automation=list(data.get('automation', [])),
                   patterns=list(data.get('patterns', [])),
                   pattern_instances=list(data.get('pattern_instances', [])),
                   mixer=dict(data.get('mixer', {})),
                   live_slots=list(data.get('live_slots', [])),
                   cue_list=cue_list,
                   markers=markers)

    def save(self, path=TIMELINE_FILE):
        data = {
            'version': self.SCHEMA_VERSION,  # v4: + cue_list (E1); I2 añade markers
            'duration_ms': self.duration_ms,
            'clips': [c.to_dict() for c in self.clips],
            'groups': [g.to_dict() for g in self.groups],
            'cue_points': [c.to_dict() for c in self.cue_points],
            'automation': list(self.automation),
            'patterns': list(self.patterns),
            'pattern_instances': list(self.pattern_instances),
            'mixer': dict(self.mixer),
            'live_slots': list(self.live_slots),
            'cue_list': self.cue_list.to_dict(),
            'markers': [m.to_dict() for m in self.markers],
        }
        # Guardado atómico (ANALYSIS hallazgo 18): escribir a .tmp y os.replace,
        # para que un crash a mitad de json.dump no corrompa el archivo real.
        path = Path(path)
        tmp = path.with_suffix(path.suffix + '.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path=TIMELINE_FILE) -> 'Timeline':
        """Carga un show.json de CUALQUIER versión (v1/v2/v3/v4).

        Migración tolerante (F0.2, E1): los campos que falten reciben su default
        vacío — cargar un show viejo NUNCA falla ni pierde datos. Al guardar,
        sale como v4.
        """
        p = Path(path)
        if not p.is_file():
            return cls()
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        clips  = [Clip.from_dict(d)  for d in data.get('clips',  [])]
        groups = [BarGroup.from_dict(d) for d in data.get('groups', [])]
        cues_raw = data.get('cue_points', [])
        cues = [CuePoint.from_dict(d) for d in cues_raw] if cues_raw else None
        # E1: migración tolerante v3→v4: si falta cue_list → CueList vacía
        cue_list_raw = data.get('cue_list')
        cue_list = CueList.from_dict(cue_list_raw) if cue_list_raw else CueList(entries=[])
        # I2: migración tolerante — si falta markers → lista vacía
        markers_raw = data.get('markers', [])
        markers = [Marker.from_dict(d) for d in markers_raw]
        return cls(clips, int(data.get('duration_ms', 165_000)), groups, cues,
                   automation=list(data.get('automation', [])),
                   patterns=list(data.get('patterns', [])),
                   pattern_instances=list(data.get('pattern_instances', [])),
                   mixer=dict(data.get('mixer', {})),
                   live_slots=list(data.get('live_slots', [])),
                   cue_list=cue_list,
                   markers=markers)


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
