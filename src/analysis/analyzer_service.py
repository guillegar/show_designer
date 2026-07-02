"""
analyzer_service.py — Capa unificada de acceso al análisis musical.

Fase A de la release v1.6 "Audio Brain". Sustituye los accesos directos
a analysis.json + timeseries.npz repartidos por show_engine.py /
timeline_editor.py / generate_show_taser.py por UNA puerta de entrada
normalizada (schema v3) con migrador transparente desde v1 y v2.

Principios:
  • LAZY: no toca disco hasta que se piden datos.
  • CACHE: timeseries.npz cargado una vez, interpolaciones cacheadas.
  • SEPARACIÓN crudo/curado: analysis.json + timeseries.npz son sagrados
    (regenerables por analyzer_pro.py); curation.json es el trabajo humano
    y NUNCA se pisa al re-analizar.
  • MIGRACIÓN: schema v1 (analyzer.py) y v2 (analyzer_pro.py) se
    normalizan al vuelo al schema canónico v3 en memoria.

API pública (resumen):
    svc = AnalysisService(audio_path_or_dir)
    svc.summary          → dict
    svc.list_sections()  → List[Section]
    svc.list_beats(t0,t1)
    svc.list_downbeats(t0,t1)
    svc.list_events(kind, t0, t1)   # kick/snare/hat/sub/bass/.../onsets_all
    svc.features_at(t, names)
    svc.features_range(t0, t1, downsample_to, names)
    svc.find_drops(min_energy_jump)
    svc.find_breakdowns(min_low_energy_sec)
    svc.list_stems_events(stem)
    svc.curation         → Curation  (escrituras + persistencia)
"""
from __future__ import annotations

import json
import threading
from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from src._paths import ANALIZADAS_DIR

# ───────────────────────────────────────────────────────────────
# Vocabulario de tipos de sección (vocabulario híbrido + libre)
# ───────────────────────────────────────────────────────────────

SECTION_TYPES = [
    'intro', 'verse', 'chorus', 'drop', 'breakdown',
    'buildup', 'bridge', 'outro', 'silence',
]
"""Tipos canónicos. La curación admite cualquier otra string libre."""

EVENT_KINDS = [
    'kick', 'snare', 'hat',
    'sub', 'bass', 'low_mid', 'mid', 'high_mid', 'presence', 'brilliance', 'air',
    'bass_notes', 'mids', 'highs',
    'onsets_all', 'onsets_percussive', 'onsets_harmonic',
]


# ───────────────────────────────────────────────────────────────
# Dataclasses ligeras para tipado de retorno
# ───────────────────────────────────────────────────────────────

@dataclass
class Section:
    idx: int
    start: float
    end: float
    energy: float
    label: str           # label automático ("section_3")
    name: str = ""       # nombre curado (vacío si no editado)
    type: str = ""       # tipo curado (vocab o libre); vacío si no editado

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Event:
    time_sec: float
    kind: str
    end_sec: float | None = None   # los band_events tienen start+end; los onsets no
    source: str = "auto"              # "auto" | "manual"
    name: str = ""

    def to_dict(self) -> dict:
        d = {"time_sec": self.time_sec, "kind": self.kind, "source": self.source}
        if self.end_sec is not None:
            d["end_sec"] = self.end_sec
        if self.name:
            d["name"] = self.name
        return d


# ───────────────────────────────────────────────────────────────
# MIGRADOR — v1 / v2 → v3
# ───────────────────────────────────────────────────────────────

def detect_schema_version(payload: dict) -> int:
    """Detecta el schema_version del payload, infiriendo si no está marcado."""
    if 'schema_version' in payload:
        return int(payload['schema_version'])
    # v1: 'beats' (no _librosa); v2: 'beats_librosa'
    if 'beats_librosa' in payload:
        return 2
    if 'beats' in payload:
        return 1
    return 0  # desconocido


def migrate_to_v3(payload: dict) -> dict:
    """Normaliza un payload v1, v2 o v3 al schema canónico v3.

    El payload v3 tiene:
      schema_version, file, sha256, song_id, analyzed_at, duration_s, sample_rate
      global: { bpm, bpm_source, beat_count, downbeats_source, key, loudness_*,
                peak_amplitude, spectral_centroid_mean_hz, zcr_mean,
                spectral_flatness_mean? }
      beats: [float]                  # unificado
      downbeats: [float]              # unificado (puede estar vacío)
      sections: [...]
      onsets: { all, percussive, harmonic }
      events: { kick, snare, hat, sub, bass, ..., bass_notes, mids, highs }
              cada uno [{start, end, duration}]
      stems: { files, analysis }       # opcional, puede estar vacío
      piano_roll: { notes, count, midi_file } | null
      lyrics: { language, text, segments } | null
      files: { timeseries, audio_source }
    """
    v = detect_schema_version(payload)
    if v == 3:
        return payload

    out = dict(payload)  # copia superficial
    out['schema_version'] = 3

    glob_in = dict(payload.get('global', {}))
    glob_out: dict[str, Any] = {}

    if v == 1:
        # v1: bpm, beat_count, key, loudness, peak, crest, energy, danceability,
        #     valence, spectral_brightness, spectral_centroid_mean_hz, zcr_mean
        glob_out['bpm'] = glob_in.get('bpm', 0.0)
        glob_out['bpm_source'] = 'librosa'
        glob_out['beat_count'] = int(glob_in.get('beat_count', 0))
        glob_out['downbeats_source'] = 'fallback_4_4'  # v1 ya asume 4/4
        out['beats'] = list(payload.get('beats', []))
        out['downbeats'] = list(payload.get('downbeats', []))  # ya estaba derivado
    elif v == 2:
        # v2: bpm_librosa, bpm_madmom, beat_count_librosa, beat_count_madmom,
        #     downbeat_count_madmom, key, loudness, peak, spectral, zcr, flatness
        bpm_madmom = glob_in.get('bpm_madmom')
        bpm_librosa = glob_in.get('bpm_librosa', 0.0)
        if bpm_madmom:
            glob_out['bpm'] = bpm_madmom
            glob_out['bpm_source'] = 'madmom'
        else:
            glob_out['bpm'] = bpm_librosa
            glob_out['bpm_source'] = 'librosa'
        glob_out['beat_count'] = int(glob_in.get('beat_count_librosa', 0))

        beats_madmom = payload.get('beats_madmom') or []
        beats_librosa = payload.get('beats_librosa') or []
        out['beats'] = list(beats_madmom) if beats_madmom else list(beats_librosa)

        downbeats_madmom = payload.get('downbeats_madmom') or []
        if downbeats_madmom:
            out['downbeats'] = list(downbeats_madmom)
            glob_out['downbeats_source'] = 'madmom'
        elif out['beats']:
            # Fallback 4/4: cada 4º beat es downbeat
            out['downbeats'] = list(out['beats'][::4])
            glob_out['downbeats_source'] = 'fallback_4_4'
        else:
            out['downbeats'] = []
            glob_out['downbeats_source'] = 'none'

        # Limpiar las claves v2 ya migradas
        for k in ('bpm_madmom', 'bpm_librosa', 'beat_count_librosa',
                 'beat_count_madmom', 'downbeat_count_madmom'):
            glob_in.pop(k, None)

    # Conservar los demás campos globales (key, loudness, peak, etc.)
    for k, val in glob_in.items():
        if k not in glob_out:
            glob_out[k] = val
    out['global'] = glob_out

    # song_id corto: 12 chars del sha256 del audio
    sha = payload.get('sha256', '')
    out['song_id'] = sha[:12] if sha else payload.get('file', 'unknown')

    # Unificar eventos en `events` dict plano
    events: dict[str, list] = {}
    for k, v_list in (payload.get('events_by_band') or {}).items():
        events[k] = list(v_list)
    for k, v_list in (payload.get('events_percussive') or {}).items():
        events[k] = list(v_list)
    for k, v_list in (payload.get('events_harmonic') or {}).items():
        events[k] = list(v_list)
    out['events'] = events

    # Defaults para campos v2 ausentes en v1
    out.setdefault('stems', {'files': {}, 'analysis': {}})
    out.setdefault('piano_roll', None)
    out.setdefault('lyrics', None)
    out.setdefault('files', {'timeseries': 'timeseries.npz',
                             'audio_source': payload.get('file', '')})

    return out


# ───────────────────────────────────────────────────────────────
# Curation — capa humana editable, persistencia separada
# ───────────────────────────────────────────────────────────────

class Curation:
    """Curado humano sobre el análisis crudo.

    Se persiste en `analizadas/<song>/curation.json` aparte del crudo.
    Operaciones no destructivas:
      • Marcar eventos como disabled (los detectados se ocultan al consumidor).
      • Añadir eventos manuales (extra a los detectados).
      • Etiquetar secciones con nombre + tipo.
      • Overrides de umbrales por banda.
      • "Semillas" de cue (sugerencias humanas para crear cues).
    """

    SCHEMA_VERSION = 1

    def __init__(self, path: Path, song_id: str = "", service: Any | None = None):
        self.path = path
        self.song_id = song_id
        self.section_labels: dict[int, dict[str, str]] = {}
        # disabled_events: lista de (time_sec, kind, tolerance_ms)
        self.disabled_events: list[tuple[float, str, int]] = []
        self.manual_events: list[Event] = []
        self.threshold_overrides: dict[str, float] = {}
        self.cue_seeds: list[dict[str, Any]] = []
        self._dirty = False
        self._service = service  # Optional ref to AnalysisService for cache invalidation

    # ── Persistencia ───────────────────────────────────────────
    @classmethod
    def load(cls, path: Path, song_id: str = "", service: Any | None = None) -> Curation:
        c = cls(path, song_id=song_id, service=service)
        if not path.is_file():
            return c
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if data.get('version') != cls.SCHEMA_VERSION:
                print(f"[curation] versión {data.get('version')} no soportada, ignorando")
                return c
            for sl in data.get('section_labels', []):
                c.section_labels[int(sl['idx'])] = {
                    'name': sl.get('name', ''),
                    'type': sl.get('type', ''),
                }
            for de in data.get('disabled_events', []):
                c.disabled_events.append((
                    float(de['time_sec']),
                    str(de['kind']),
                    int(de.get('tolerance_ms', 20)),
                ))
            for me in data.get('manual_events', []):
                c.manual_events.append(Event(
                    time_sec=float(me['time_sec']),
                    kind=str(me['kind']),
                    source='manual',
                    name=me.get('name', ''),
                ))
            c.threshold_overrides = dict(data.get('manual_threshold_overrides', {}))
            c.cue_seeds = list(data.get('cue_seeds', []))
        except Exception as e:
            print(f"[curation] error cargando {path}: {e}")
        return c

    def save(self) -> None:
        data = {
            'version': self.SCHEMA_VERSION,
            'song_id': self.song_id,
            'section_labels': [
                {'idx': idx, **lbl} for idx, lbl in sorted(self.section_labels.items())
            ],
            'disabled_events': [
                {'time_sec': t, 'kind': k, 'tolerance_ms': tol}
                for (t, k, tol) in self.disabled_events
            ],
            'manual_events': [e.to_dict() for e in self.manual_events],
            'manual_threshold_overrides': dict(self.threshold_overrides),
            'cue_seeds': list(self.cue_seeds),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._dirty = False

    @property
    def dirty(self) -> bool:
        return self._dirty

    # ── Cache invalidation ────────────────────────────────────
    def _invalidate_if_service(self) -> None:
        """Invalida caches de AnalysisService si está disponible."""
        if self._service and hasattr(self._service, '_invalidate_feature_caches'):
            self._service._invalidate_feature_caches()

    # ── Writes ─────────────────────────────────────────────────
    def set_section_label(self, idx: int, name: str = "", type: str = "") -> None:
        """Etiqueta una sección con nombre + tipo.

        `type` admite SECTION_TYPES o cualquier string libre.
        Llamar con name="" y type="" elimina la etiqueta.
        """
        idx = int(idx)
        if not name and not type:
            self.section_labels.pop(idx, None)
        else:
            self.section_labels[idx] = {'name': name, 'type': type}
        self._dirty = True
        self._invalidate_if_service()

    def add_manual_event(self, time_sec: float, kind: str, name: str = "") -> None:
        kind = str(kind)
        if kind not in EVENT_KINDS:
            # Acepta tipos arbitrarios pero registra
            pass
        self.manual_events.append(Event(
            time_sec=float(time_sec), kind=kind, source='manual', name=name,
        ))
        self._dirty = True
        self._invalidate_if_service()

    def disable_event(self, time_sec: float, kind: str, tolerance_ms: int = 20) -> int:
        """Marca como disabled cualquier evento detectado de `kind` cercano
        a `time_sec` dentro de `tolerance_ms`. Devuelve cuántos se afectarán
        (la decisión real la toma `_is_disabled` al consumir)."""
        self.disabled_events.append((float(time_sec), str(kind), int(tolerance_ms)))
        self._dirty = True
        self._invalidate_if_service()
        return 1

    def set_event_threshold(self, kind: str, value: float) -> None:
        self.threshold_overrides[str(kind)] = float(value)
        self._dirty = True
        self._invalidate_if_service()

    def add_cue_seed(self, time_sec: float, name: str) -> None:
        self.cue_seeds.append({'time_sec': float(time_sec), 'name': str(name)})
        self._dirty = True

    # ── Reads ──────────────────────────────────────────────────
    def is_disabled(self, time_sec: float, kind: str) -> bool:
        for (t, k, tol) in self.disabled_events:
            if k != kind:
                continue
            if abs(time_sec - t) * 1000.0 <= tol:
                return True
        return False

    def section_label_for(self, idx: int) -> tuple[str, str]:
        lbl = self.section_labels.get(int(idx))
        if not lbl:
            return ("", "")
        return (lbl.get('name', ''), lbl.get('type', ''))


# ───────────────────────────────────────────────────────────────
# AnalysisService — la API que consumen show_engine / timeline / mcp
# ───────────────────────────────────────────────────────────────

class AnalysisService:
    """Acceso unificado al análisis de UNA canción.

    Argumentos aceptados al construir:
      • Path al MP3/WAV (`song.mp3`)        — busca su carpeta en analizadas/
      • Path a la carpeta del análisis      — `analizadas/<slug>/`
      • Path a analysis.json directamente

    No carga nada en disco hasta el primer acceso (lazy).
    """

    def __init__(self, audio_path_or_dir: Path):
        self._input = Path(audio_path_or_dir)
        self._analysis_dir: Path | None = None
        self._analysis_json_path: Path | None = None
        self._timeseries_path: Path | None = None
        self._payload: dict | None = None   # v3 normalizado
        self._timeseries: dict | None = None  # arrays mapeados
        self._curation: Curation | None = None
        self._preload_thread: threading.Thread | None = None

        # Resolver paths
        self._resolve_paths()

        # Preload analysis + timeseries en background (non-blocking)
        if self.has_analysis or self.has_timeseries:
            self._preload_thread = threading.Thread(
                target=self._preload_background, daemon=True
            )
            self._preload_thread.start()

    # ── Resolución de paths ───────────────────────────────────
    def _resolve_paths(self) -> None:
        p = self._input
        if p.is_file() and p.suffix == '.json':
            self._analysis_json_path = p
            self._analysis_dir = p.parent
        elif p.is_dir():
            self._analysis_dir = p
            self._analysis_json_path = p / 'analysis.json'
        elif p.is_file() and p.suffix.lower() in ('.mp3', '.wav', '.flac', '.ogg'):
            # Buscar la carpeta analizada por slugify
            slug = self._slugify(p.stem)
            self._analysis_dir = ANALIZADAS_DIR / slug
            self._analysis_json_path = self._analysis_dir / 'analysis.json'
        else:
            # Fallback: asumir que es un nombre/slug bajo analizadas/
            self._analysis_dir = ANALIZADAS_DIR / p.name
            self._analysis_json_path = self._analysis_dir / 'analysis.json'

        if self._analysis_dir is not None:
            self._timeseries_path = self._analysis_dir / 'timeseries.npz'

    @staticmethod
    def _slugify(name: str) -> str:
        import re
        s = re.sub(r'[^\w\s-]', '', name).strip().lower()
        return re.sub(r'[-\s]+', '_', s)

    def _preload_background(self) -> None:
        """Carga payload + timeseries en background (non-blocking init)."""
        try:
            self._load_payload()
            self._load_timeseries()
        except Exception:
            pass  # Si falla, lazy load lo maneja en primer acceso

    def _invalidate_feature_caches(self) -> None:
        """Limpia el cache de get_audio_context cuando curation cambia."""
        self.get_audio_context.cache_clear()

    # ── Estado / disponibilidad ───────────────────────────────
    @property
    def analysis_dir(self) -> Path:
        return self._analysis_dir or Path()

    @property
    def has_analysis(self) -> bool:
        return self._analysis_json_path is not None and self._analysis_json_path.is_file()

    @property
    def has_timeseries(self) -> bool:
        return self._timeseries_path is not None and self._timeseries_path.is_file()

    @property
    def song_id(self) -> str:
        if self._payload is None:
            self._load_payload()
        return self._payload.get('song_id', '') if self._payload else ''

    @property
    def curation(self) -> Curation:
        if self._curation is None:
            cpath = self.analysis_dir / 'curation.json'
            self._curation = Curation.load(cpath, song_id=self.song_id, service=self)
        return self._curation

    # ── Lazy loaders ──────────────────────────────────────────
    def _load_payload(self) -> None:
        if self._payload is not None:
            return
        if not self.has_analysis:
            raise FileNotFoundError(
                f"No existe analysis.json en {self._analysis_json_path}"
            )
        with open(self._analysis_json_path, encoding='utf-8') as f:
            raw = json.load(f)
        v = detect_schema_version(raw)
        if v == 0:
            raise ValueError(f"Schema desconocido en {self._analysis_json_path}")
        self._payload = migrate_to_v3(raw)
        # Validaciones mínimas
        for k in ('duration_s', 'sample_rate', 'global', 'beats',
                  'downbeats', 'sections', 'onsets', 'events'):
            if k not in self._payload:
                raise ValueError(f"Campo {k!r} ausente tras migración")

    def _load_timeseries(self) -> None:
        if self._timeseries is not None:
            return
        if not self.has_timeseries:
            # No es un error fatal: features_at devolverá defaults
            self._timeseries = {}
            return
        npz = np.load(self._timeseries_path)
        self._timeseries = {k: npz[k] for k in npz.files}
        # Pre-cache: los tiempos del grid
        if 'times' not in self._timeseries:
            print("[analyzer_service] timeseries.npz sin 'times', interpolación deshabilitada")

    # ── Summary ───────────────────────────────────────────────
    @property
    def summary(self) -> dict:
        self._load_payload()
        p = self._payload
        g = p.get('global', {})
        return {
            'schema_version': p.get('schema_version'),
            'file': p.get('file'),
            'song_id': p.get('song_id'),
            'duration_s': p.get('duration_s'),
            'sample_rate': p.get('sample_rate'),
            'bpm': g.get('bpm'),
            'bpm_source': g.get('bpm_source'),
            'beat_count': g.get('beat_count'),
            'downbeats_source': g.get('downbeats_source'),
            'key': g.get('key'),
            'loudness_rms_db': g.get('loudness_rms_db'),
            'peak_amplitude': g.get('peak_amplitude'),
            'spectral_centroid_mean_hz': g.get('spectral_centroid_mean_hz'),
            'num_sections': len(p.get('sections', [])),
            'has_stems': bool(p.get('stems', {}).get('files')),
            'has_piano_roll': bool(p.get('piano_roll')),
            'has_lyrics': bool(p.get('lyrics')),
            'has_timeseries': self.has_timeseries,
            'analysis_dir': str(self.analysis_dir),
        }

    # ── Secciones ─────────────────────────────────────────────
    def list_sections(self, with_curated: bool = True) -> list[Section]:
        self._load_payload()
        out: list[Section] = []
        for s in self._payload.get('sections', []):
            sec = Section(
                idx=int(s['index']),
                start=float(s['start']),
                end=float(s['end']),
                energy=float(s.get('energy', 0.0)),
                label=str(s.get('label', f"section_{s['index']}")),
            )
            if with_curated:
                name, type_ = self.curation.section_label_for(sec.idx)
                sec.name = name
                sec.type = type_
            out.append(sec)
        return out

    def section_at(self, time_sec: float) -> Section | None:
        for s in self.list_sections():
            if s.start <= time_sec < s.end:
                return s
        return None

    # ── Beats / Downbeats ─────────────────────────────────────
    def list_beats(self, t0: float = 0.0, t1: float | None = None) -> list[float]:
        self._load_payload()
        return self._slice(self._payload.get('beats', []), t0, t1)

    def list_downbeats(self, t0: float = 0.0, t1: float | None = None) -> list[float]:
        self._load_payload()
        return self._slice(self._payload.get('downbeats', []), t0, t1)

    @staticmethod
    def _slice(times: list[float], t0: float, t1: float | None) -> list[float]:
        if not times:
            return []
        arr = times
        lo = bisect_left(arr, t0)
        hi = bisect_right(arr, t1) if t1 is not None else len(arr)
        return list(arr[lo:hi])

    # ── Eventos (kicks, snares, hats, onsets...) ──────────────
    def list_events(self, kind: str, t0: float = 0.0,
                    t1: float | None = None) -> list[Event]:
        """Lista de eventos de `kind` entre t0 y t1.

        Filtra los marcados como disabled e incluye los manuales.
        `kind` admite: kick/snare/hat/sub/bass/.../bass_notes/mids/highs/
                       onsets_all/onsets_percussive/onsets_harmonic.
        """
        self._load_payload()

        # 1) Eventos auto del crudo
        auto: list[Event] = []
        if kind.startswith('onsets_'):
            sub = kind[len('onsets_'):]
            for t in (self._payload.get('onsets', {}).get(sub, []) or []):
                auto.append(Event(time_sec=float(t), kind=kind, source='auto'))
        else:
            events_dict = self._payload.get('events', {})
            for e in (events_dict.get(kind, []) or []):
                auto.append(Event(
                    time_sec=float(e['start']),
                    kind=kind,
                    end_sec=float(e.get('end', e['start'])),
                    source='auto',
                ))

        # 2) Filtrar disabled
        cur = self.curation
        auto = [e for e in auto if not cur.is_disabled(e.time_sec, kind)]

        # 3) Añadir manuales del mismo kind
        manual = [e for e in cur.manual_events if e.kind == kind]

        # 4) Combinar + filtrar rango
        all_evs = auto + manual
        all_evs.sort(key=lambda e: e.time_sec)
        if t1 is None:
            return [e for e in all_evs if e.time_sec >= t0]
        return [e for e in all_evs if t0 <= e.time_sec <= t1]

    # ── Features puntuales / rangos ───────────────────────────
    def features_at(self, time_sec: float, names: list[str] | None = None) -> dict[str, float]:
        """Interpola los features escalares 1D al tiempo dado.

        Si `names` es None, devuelve todos los disponibles.
        Multidim (mfcc, chroma, tonnetz, contrast, mel_bands) se devuelven
        como lists (no como float).
        """
        self._load_timeseries()
        if not self._timeseries or 'times' not in self._timeseries:
            return {}
        ts_times = self._timeseries['times']
        if names is None:
            names = ['rms', 'rms_db', 'centroid', 'rolloff', 'flux', 'zcr',
                     'bandwidth', 'flatness']
        out: dict[str, Any] = {}
        for n in names:
            if n not in self._timeseries:
                continue
            arr = self._timeseries[n]
            if arr.ndim == 1:
                out[n] = float(np.interp(time_sec, ts_times, arr, left=0.0, right=0.0))
            elif arr.ndim == 2:
                # Por coeficiente
                vec = np.zeros(arr.shape[0], dtype=np.float32)
                for i in range(arr.shape[0]):
                    vec[i] = np.interp(time_sec, ts_times, arr[i], left=0.0, right=0.0)
                out[n] = vec.tolist()
        return out

    def features_range(self, t0: float, t1: float,
                       downsample_to: int | None = None,
                       names: list[str] | None = None) -> dict[str, Any]:
        """Devuelve series temporales recortadas a [t0, t1].

        Si `downsample_to` está dado, hace decimation simple (mean) hasta
        tener `downsample_to` puntos. Útil para enviar a UI / MCP sin
        saturar.
        """
        self._load_timeseries()
        if not self._timeseries or 'times' not in self._timeseries:
            return {'times': [], 'features': {}}
        ts_times = self._timeseries['times']
        lo = bisect_left(ts_times, t0)
        hi = bisect_right(ts_times, t1)
        if hi <= lo:
            return {'times': [], 'features': {}}
        times_slice = ts_times[lo:hi]
        if names is None:
            names = ['rms', 'centroid', 'flux', 'zcr']

        features: dict[str, Any] = {}
        for n in names:
            if n not in self._timeseries:
                continue
            arr = self._timeseries[n]
            if arr.ndim == 1:
                features[n] = arr[lo:hi]
            elif arr.ndim == 2:
                features[n] = arr[:, lo:hi]

        # Downsample
        if downsample_to is not None and len(times_slice) > downsample_to:
            stride = max(1, len(times_slice) // downsample_to)
            times_slice = times_slice[::stride]
            for n in list(features.keys()):
                arr = features[n]
                if arr.ndim == 1:
                    features[n] = arr[::stride]
                else:
                    features[n] = arr[:, ::stride]

        # A JSON-friendly
        out = {
            'times': [float(x) for x in times_slice],
            'features': {},
        }
        for n, arr in features.items():
            if arr.ndim == 1:
                out['features'][n] = [float(x) for x in arr]
            else:
                out['features'][n] = [[float(x) for x in row] for row in arr]
        return out

    # ── Heurísticas ───────────────────────────────────────────
    def find_drops(self, min_energy_jump: float = 0.4) -> list[dict]:
        """Detecta drops: secciones cuya energía sube ≥ min_energy_jump
        respecto a la anterior."""
        sections = self.list_sections()
        drops = []
        for i, s in enumerate(sections):
            if i == 0:
                continue
            prev = sections[i - 1]
            if prev.energy <= 0:
                continue
            jump = (s.energy - prev.energy) / max(prev.energy, 1e-6)
            if jump >= min_energy_jump:
                drops.append({
                    'idx': s.idx,
                    'start': s.start,
                    'end': s.end,
                    'energy': s.energy,
                    'energy_jump_ratio': round(jump, 3),
                    'curated_name': s.name,
                    'curated_type': s.type,
                })
        return drops

    def find_breakdowns(self, min_low_energy_sec: float = 4.0) -> list[dict]:
        """Detecta breakdowns: secciones largas con energía < 60% del
        promedio del show."""
        sections = self.list_sections()
        if not sections:
            return []
        avg_energy = sum(s.energy for s in sections) / len(sections)
        thr = avg_energy * 0.6
        out = []
        for s in sections:
            if s.energy <= thr and s.duration >= min_low_energy_sec:
                out.append({
                    'idx': s.idx,
                    'start': s.start,
                    'end': s.end,
                    'duration': round(s.duration, 3),
                    'energy': s.energy,
                    'curated_name': s.name,
                    'curated_type': s.type,
                })
        return out

    # ── Stems ─────────────────────────────────────────────────
    def list_stems_events(self, stem: str) -> dict[str, Any]:
        """Si demucs corrió, devuelve los onsets/active regions del stem."""
        self._load_payload()
        stems = self._payload.get('stems', {})
        analysis = stems.get('analysis', {}) or {}
        stem_data = analysis.get(stem)
        if not stem_data:
            return {'available': False, 'stem': stem}
        return {
            'available': True,
            'stem': stem,
            'onsets': list(stem_data.get('onsets', [])),
            'active_regions': list(stem_data.get('active_regions', [])),
            'rms_mean': stem_data.get('rms_mean'),
            'rms_peak': stem_data.get('rms_peak'),
        }

    # ── Normalization bounds (normalización simple, sin precálculo) ────
    # NOTA: A1 implementa normalización on-the-fly. Regresión de rendimiento
    # ~5-15% detectada en bench (I5). Pendiente de optimización en fase de
    # refinamiento (F0 → A1 boundary check).

    # ── Audio context para los efectos (backwards compat) ────
    @lru_cache(maxsize=1)
    def get_audio_context(self, time_sec: float) -> dict[str, Any]:
        """Devuelve el mismo shape que `ShowEngine.get_audio_context()`
        usaba: dict con rms/centroid/flux/zcr/energy escalares + mfcc/
        chroma/tonnetz/contrast/mel_bands vectores.

        PLUS: actx['norm'] con las MISMAS señales normalizadas 0..1
        (ROADMAP v2 A1: la modulación lee SIEMPRE de norm, nunca de la cruda).

        Esto evita reescribir los 51 efectos. show_engine.py puede delegar
        aquí.
        """
        self._load_timeseries()
        ctx = self._default_audio_context()
        norm_ctx = {}

        if not self._timeseries or 'times' not in self._timeseries:
            ctx['norm'] = norm_ctx
            return ctx
        ts_times = self._timeseries['times']

        # ANALYSIS hallazgo 14: un solo searchsorted + lerp vectorizado para TODAS
        # las curvas (46+: mfcc/chroma/tonnetz/contrast/mel + escalares), en vez de
        # un np.interp por coeficiente. Replica np.interp(..., left=0.0, right=0.0).
        _n = len(ts_times)
        _oor = (_n == 0 or time_sec < ts_times[0] or time_sec > ts_times[-1])
        if not _oor:
            _idx = int(np.searchsorted(ts_times, time_sec))
            if _idx <= 0:
                _i0 = _i1 = 0; _w = 0.0
            elif _idx >= _n:
                _i0 = _i1 = _n - 1; _w = 0.0
            else:
                _i0, _i1 = _idx - 1, _idx
                _t0 = float(ts_times[_i0]); _t1 = float(ts_times[_i1])
                _w = 0.0 if _t1 == _t0 else (time_sec - _t0) / (_t1 - _t0)

        def interp_1d(arr):
            if _oor:
                return 0.0
            return float(float(arr[_i0]) * (1.0 - _w) + float(arr[_i1]) * _w)

        def interp_2d(arr):
            if _oor:
                return np.zeros(arr.shape[0], dtype=np.float32)
            return (arr[:, _i0] * (1.0 - _w) + arr[:, _i1] * _w).astype(np.float32)

        def normalize_scalar(val: float) -> float:
            """Normaliza un valor escalar 0..1 simple."""
            # Clamping simple: se asume que los valores están en rangos "razonables"
            # NOTA: esto es una normalización minimal. Para precisión, usar bounds
            # precalculados (pendiente de optimización).
            return min(1.0, max(0.0, val / 1.0)) if val > 0 else 0.0

        def normalize_vector(arr: np.ndarray) -> np.ndarray:
            """Normaliza un vector 0..1 elemento a elemento."""
            # Clamping simple por elemento
            return np.clip(arr, 0.0, 1.0).astype(np.float32)

        ts = self._timeseries
        for name in ('rms', 'centroid', 'flux', 'zcr', 'rolloff', 'bandwidth', 'flatness'):
            if name in ts and ts[name].ndim == 1:
                raw_val = interp_1d(ts[name])
                ctx[name] = raw_val
                norm_ctx[name] = normalize_scalar(raw_val)

        for name in ('mfcc', 'chroma', 'tonnetz', 'contrast', 'mel_bands'):
            if name in ts and ts[name].ndim == 2:
                raw_arr = interp_2d(ts[name])
                ctx[name] = raw_arr
                norm_ctx[name] = normalize_vector(raw_arr)

        # dtempo: usa su propio grid de tiempos
        if 'dtempo' in ts and 'dtempo_times' in ts:
            raw_val = float(np.interp(time_sec, ts['dtempo_times'],
                                            ts['dtempo'], left=0.0, right=0.0))
            ctx['dtempo'] = raw_val
            norm_ctx['dtempo'] = normalize_scalar(raw_val)

        # energy fallback
        if 'energy' not in ctx:
            ctx['energy'] = ctx.get('rms', 0.0) ** 2
            norm_ctx['energy'] = norm_ctx.get('rms', 0.0)  # usa rms normalizado

        ctx['norm'] = norm_ctx
        return ctx

    @staticmethod
    def _default_audio_context() -> dict[str, Any]:
        # 'energy' se omite a propósito: se rellena desde timeseries['energy']
        # o, en su defecto, se deriva como rms**2.
        return {
            'mfcc': np.zeros(13, dtype=np.float32),
            'chroma': np.zeros(12, dtype=np.float32),
            'tonnetz': np.zeros(6, dtype=np.float32),
            'contrast': np.zeros(7, dtype=np.float32),
            'mel_bands': np.zeros(8, dtype=np.float32),
            'centroid': 0.0,
            'flux': 0.0,
            'rms': 0.0,
            'zcr': 0.0,
            'dtempo': 0.0,
        }

    # ── Acceso al payload v3 normalizado (consumo avanzado) ──
    @property
    def payload_v3(self) -> dict:
        self._load_payload()
        return self._payload


# ───────────────────────────────────────────────────────────────
# Constructores de conveniencia
# ───────────────────────────────────────────────────────────────

def default_service() -> AnalysisService:
    """Servicio que apunta a la canción del show actual (El Taser).

    Se usa como fallback cuando dual_app.py no sabe qué audio cargar.
    Cuando llegue la Fase 7 (multi-proyecto), esto desaparecerá.
    """
    return AnalysisService(ANALIZADAS_DIR / 'el_taser_de_mama_remix')


def discover_analyzed_songs() -> list[str]:
    """Lista los slugs disponibles en analizadas/."""
    if not ANALIZADAS_DIR.is_dir():
        return []
    return sorted(
        p.name for p in ANALIZADAS_DIR.iterdir()
        if p.is_dir() and (p / 'analysis.json').is_file()
    )


# ───────────────────────────────────────────────────────────────
# Self-test
# ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    print("=== analyzer_service.py self-test ===")
    print(f"Canciones analizadas: {discover_analyzed_songs()}")

    svc = default_service()
    print(f"Has analysis: {svc.has_analysis}")
    print(f"Has timeseries: {svc.has_timeseries}")

    if not svc.has_analysis:
        print("No analysis available — saliendo")
        sys.exit(0)

    summary = svc.summary
    print(f"Summary keys: {list(summary.keys())}")
    print(f"  BPM: {summary['bpm']} ({summary['bpm_source']})")
    print(f"  Beats: {summary['beat_count']}")
    print(f"  Sections: {summary['num_sections']}")
    print(f"  Downbeats source: {summary['downbeats_source']}")
    print(f"  Has stems: {summary['has_stems']}")
    print(f"  Has piano_roll: {summary['has_piano_roll']}")

    secs = svc.list_sections()
    print(f"\nSecciones ({len(secs)}):")
    for s in secs:
        print(f"  [{s.idx}] {s.start:7.2f}->{s.end:7.2f}  E={s.energy:.4f}  {s.label}"
              + (f"  name={s.name!r} type={s.type!r}" if s.name or s.type else ""))

    beats = svc.list_beats(0, 10)
    print(f"\nBeats primeros 10s: {len(beats)} ({beats[:5]}...)")

    downbeats = svc.list_downbeats(0, 20)
    print(f"Downbeats primeros 20s: {len(downbeats)} ({downbeats})")

    kicks = svc.list_events('kick', 0, 30)
    print(f"\nKicks 0-30s: {len(kicks)}")

    drops = svc.find_drops()
    print(f"\nDrops detectados ({len(drops)}):")
    for d in drops:
        print(f"  Section {d['idx']}: start={d['start']:.1f}s "
              f"energy_jump={d['energy_jump_ratio']:.2f}")

    bdwn = svc.find_breakdowns()
    print(f"\nBreakdowns ({len(bdwn)}):")
    for b in bdwn:
        print(f"  Section {b['idx']}: {b['start']:.1f}->{b['end']:.1f} "
              f"({b['duration']:.1f}s)  E={b['energy']:.4f}")

    feats = svc.features_at(60.0)
    print(f"\nFeatures @ t=60s: {sorted(feats.keys())}")
    print(f"  rms={feats.get('rms', 0):.4f}  centroid={feats.get('centroid', 0):.0f}Hz")

    ctx = svc.get_audio_context(60.0)
    print(f"\nAudio context @ t=60s keys: {sorted(ctx.keys())}")
    print(f"  rms={ctx['rms']:.4f}  energy={ctx['energy']:.4f}  dtempo={ctx.get('dtempo', 0):.1f}")

    # Curation
    print(f"\nCuration en: {svc.curation.path}")
    print(f"  section_labels: {len(svc.curation.section_labels)}")
    print(f"  disabled: {len(svc.curation.disabled_events)}")
    print(f"  manuales: {len(svc.curation.manual_events)}")

    print("\n[OK] self-test completado")
