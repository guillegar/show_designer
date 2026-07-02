"""
exporter.py — Exportadores multi-formato para Show Designer Pro (v1.8 F5)

Formatos soportados:
  CSV Clips    : lista de todos los clips con metadatos
  CSV DMX      : valores DMX frame-a-frame (universo seleccionable)
  QLC+ XML     : workspace con fixtures + cues como Chaser
"""
from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fixtures import FixtureRig
    from timeline_model import Clip, Timeline


# ─────────────────────────────────────────────────────────────────────────────
# 1. CSV — Lista de clips
# ─────────────────────────────────────────────────────────────────────────────

def export_clips_csv(timeline: Timeline, path) -> int:
    """
    Exporta todos los clips del timeline como CSV.

    Columnas:
      clip_id, track, start_ms, end_ms, duration_ms, layer,
      effect_id, category, channel_effect_id, scope, label, color,
      locked, muted, params_json

    Devuelve el numero de filas escritas.
    """
    path = Path(path)
    clips = sorted(timeline.clips, key=lambda c: (c.start_ms, c.track, c.layer))

    headers = [
        'clip_id', 'track', 'start_ms', 'end_ms', 'duration_ms', 'layer',
        'effect_id', 'category', 'channel_effect_id', 'scope',
        'label', 'color', 'locked', 'muted', 'params_json',
    ]

    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for i, clip in enumerate(clips):
            writer.writerow({
                'clip_id':           i,
                'track':             clip.track,
                'start_ms':          clip.start_ms,
                'end_ms':            clip.end_ms,
                'duration_ms':       clip.end_ms - clip.start_ms,
                'layer':             clip.layer,
                'effect_id':         clip.effect_id,
                'category':          getattr(clip, 'category', 'pixel'),
                'channel_effect_id': getattr(clip, 'channel_effect_id', '') or '',
                'scope':             clip.scope,
                'label':             clip.label or '',
                'color':             clip.color,
                'locked':            int(clip.locked),
                'muted':             int(clip.muted),
                'params_json':       json.dumps(clip.params, ensure_ascii=False),
            })

    return len(clips)


# ─────────────────────────────────────────────────────────────────────────────
# 2. CSV — DMX frame-a-frame
# ─────────────────────────────────────────────────────────────────────────────

def export_dmx_csv(show_engine, timeline: Timeline, path,
                   universe: int = 1,
                   interval_ms: int = 100,
                   duration_ms: int | None = None) -> int:
    """
    Renderiza el show y exporta valores DMX como CSV.

    Columnas: time_ms, ch_1 .. ch_512
    (solo las primeras `max_channels` para mantener el archivo manejable)

    Args:
        show_engine : ShowEngine activo con rig y analysis cargados
        timeline    : Timeline a renderizar
        path        : Ruta de destino (.csv)
        universe    : Universo DMX a exportar (1..N)
        interval_ms : Intervalo entre frames (default 100ms = 10fps)
        duration_ms : Duracion total (None -> usa timeline.duration_ms)

    Devuelve el numero de frames escritos.
    """
    path = Path(path)
    dur = duration_ms or timeline.duration_ms
    max_channels = 512

    # Determinar cuántos canales usa realmente el universo (para no exportar 512 ceros)
    actual_channels = 512
    if show_engine and hasattr(show_engine, 'fixture_rig') and show_engine.fixture_rig:
        fxs_in_uni = [
            fx for fx in show_engine.fixture_rig.fixtures
            if fx.universe == universe
        ]
        if fxs_in_uni:
            last_ch = max(
                fx.dmx_start - 1 + (
                    show_engine.fixture_rig.get_profile(fx.profile_id).num_channels
                    if show_engine.fixture_rig.get_profile(fx.profile_id) else 3
                )
                for fx in fxs_in_uni
            )
            actual_channels = min(max_channels, last_ch)
        else:
            actual_channels = 16   # por defecto exportar 16 canales

    headers = ['time_ms'] + [f'ch_{i+1}' for i in range(actual_channels)]

    frames_written = 0
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        t_ms = 0
        while t_ms <= dur:
            t_sec = t_ms / 1000.0
            row = [t_ms]

            try:
                # Intentar usar el Universe Assembler si está disponible
                if (show_engine and
                        hasattr(show_engine, 'assemble_universe') and
                        show_engine.fixture_rig is not None):
                    uni_bytes = show_engine.assemble_universe(universe, t_sec)
                    row.extend(uni_bytes[:actual_channels])
                else:
                    row.extend([0] * actual_channels)
            except Exception:
                row.extend([0] * actual_channels)

            writer.writerow(row)
            frames_written += 1
            t_ms += interval_ms

    return frames_written


# ─────────────────────────────────────────────────────────────────────────────
# 3. QLC+ XML Workspace
# ─────────────────────────────────────────────────────────────────────────────

def export_qlc_workspace(timeline: Timeline, rig: FixtureRig | None,
                         path, song_name: str = "Show") -> dict:
    """
    Genera un workspace QLC+ (.qxw) con:
      - Fixtures mapeados desde el rig
      - Una Scene por cada cue point
      - Un Chaser "Show Timeline" que recorre todas las scenes

    Devuelve dict con estadisticas: {fixtures, scenes, chaser_steps}

    Limitaciones intencionales:
      - Los efectos pixel se exportan como states de color fijo (el primer color
        del efecto no se puede conocer sin renderizar). Los valores DMX quedan
        en 0 — el usuario los edita en QLC+.
      - Fixtures LED se exportan como RGB generico (3ch/fixture * num_leds no
        es practico; se exporta 1 dimmer por barra de 1 canal).
    """
    path = Path(path)

    # ── XML root ─────────────────────────────────────────────────────────────
    root = ET.Element('Workspace')
    root.set('xmlns', 'http://www.qlcplus.org/Workspace')
    root.set('CurrentWindow', 'ShowManager')

    creator = ET.SubElement(root, 'Creator')
    ET.SubElement(creator, 'Name').text = 'Show Designer Pro'
    ET.SubElement(creator, 'Version').text = '1.8.0'
    ET.SubElement(creator, 'Author').text = 'Show Designer Pro v1.8'

    engine = ET.SubElement(root, 'Engine')

    # ── InputOutputMap ────────────────────────────────────────────────────────
    iomap = ET.SubElement(engine, 'InputOutputMap')
    uni_elem = ET.SubElement(iomap, 'Universe')
    uni_elem.set('ID', '0')
    uni_elem.set('Name', 'Universe 1')
    out_elem = ET.SubElement(uni_elem, 'Output')
    out_elem.set('Plugin', 'ArtNet')
    out_elem.set('Line', '0')

    # ── Fixtures ──────────────────────────────────────────────────────────────
    fixtures_elem = ET.SubElement(engine, 'Fixtures')
    fixture_map: dict[str, int] = {}   # fixture_id -> QLC fixture ID
    qlc_fx_id = 0
    universe_offset = 0   # QLC universo 0 = primero

    if rig is not None:
        for fx in rig.fixtures:
            prof = rig.get_profile(fx.profile_id) if rig else None
            fx_elem = ET.SubElement(fixtures_elem, 'Fixture')

            # QLC+ identifica por fabricante/modelo para lookup de perfil
            if fx.profile_id == 'wled_strip_93':
                manufacturer = 'Generic'
                model        = 'Generic RGB'
                channels     = 3
            elif 'moving_head' in fx.profile_id or 'mover' in (fx.fixture_id or '').lower():
                manufacturer = 'Generic'
                model        = 'Generic Moving Head'
                channels     = prof.num_channels if prof else 16
            elif 'strobe' in fx.profile_id:
                manufacturer = 'Generic'
                model        = 'Generic Strobe'
                channels     = prof.num_channels if prof else 2
            else:
                manufacturer = 'Generic'
                model        = 'Generic Dimmer'
                channels     = prof.num_channels if prof else 4

            ET.SubElement(fx_elem, 'Manufacturer').text = manufacturer
            ET.SubElement(fx_elem, 'Model').text        = model
            ET.SubElement(fx_elem, 'Mode').text         = 'Default'
            ET.SubElement(fx_elem, 'Name').text         = fx.label or fx.fixture_id
            ET.SubElement(fx_elem, 'Universe').text      = str(fx.universe - 1)  # QLC 0-based
            ET.SubElement(fx_elem, 'Address').text       = str(fx.dmx_start - 1)  # QLC 0-based
            ET.SubElement(fx_elem, 'Channels').text      = str(channels)
            ET.SubElement(fx_elem, 'ID').text            = str(qlc_fx_id)
            ET.SubElement(fx_elem, 'ExcludeFadeChannels').text = ''

            fixture_map[fx.fixture_id] = qlc_fx_id
            qlc_fx_id += 1

    # ── Functions ─────────────────────────────────────────────────────────────
    functions_elem = ET.SubElement(engine, 'Functions')
    func_id = 0
    scene_ids: list[int] = []

    # Una Scene por cue point
    cues = sorted(timeline.cue_points or [], key=lambda c: c.time_ms)

    if not cues:
        # Sin cues: crear una scene genérica de inicio y otra de fin
        _cue_times = [(0, 'Inicio'), (timeline.duration_ms, 'Fin')]
    else:
        _cue_times = [(c.time_ms, c.name or f"Cue {i+1}") for i, c in enumerate(cues)]

    for (t_ms, cue_name) in _cue_times:
        scene_elem = ET.SubElement(functions_elem, 'Function')
        scene_elem.set('ID', str(func_id))
        scene_elem.set('Type', 'Scene')
        scene_elem.set('Name', cue_name or f"Cue @ {t_ms}ms")
        scene_elem.set('Path', '')

        speed_el = ET.SubElement(scene_elem, 'Speed')
        speed_el.set('FadeIn', '0')
        speed_el.set('FadeOut', '0')
        speed_el.set('Duration', '0')

        # FixtureVal: valores de canal en blanco (a editar en QLC+)
        # Para barras LED: encendemos canal 1 (dimmer/master) al 50%
        if rig is not None:
            for fx in rig.fixtures:
                if fx.fixture_id in fixture_map:
                    fv = ET.SubElement(scene_elem, 'FixtureVal')
                    fv.set('ID', str(fixture_map[fx.fixture_id]))
                    # Dimmer al 128 (50%) por defecto
                    fv.text = '0,128'

        scene_ids.append(func_id)
        func_id += 1

    # Chaser "Show Timeline" que enlaza todas las scenes
    chaser_elem = ET.SubElement(functions_elem, 'Function')
    chaser_elem.set('ID', str(func_id))
    chaser_elem.set('Type', 'Chaser')
    chaser_elem.set('Name', f'Show Timeline — {song_name}')
    chaser_elem.set('Path', '')

    speed_el = ET.SubElement(chaser_elem, 'Speed')
    speed_el.set('FadeIn', '0')
    speed_el.set('FadeOut', '0')
    speed_el.set('Duration', '0')
    ET.SubElement(chaser_elem, 'Direction').text = 'Forward'
    ET.SubElement(chaser_elem, 'RunOrder').text  = 'SingleShot'

    steps_el = ET.SubElement(chaser_elem, 'Steps')
    for i, (sid, (t_ms, _)) in enumerate(zip(scene_ids, _cue_times)):
        # Hold = duracion hasta el siguiente cue (o hasta el final)
        if i + 1 < len(_cue_times):
            hold = _cue_times[i + 1][0] - t_ms
        else:
            hold = timeline.duration_ms - t_ms
        hold = max(0, hold)

        step = ET.SubElement(steps_el, 'Step')
        step.set('Number', str(i))
        step.set('FadeIn',  '0')
        step.set('Hold',    str(hold))
        step.set('FadeOut', '0')
        step.text = str(sid)

    chaser_id = func_id
    func_id += 1

    # ── Guardar XML ───────────────────────────────────────────────────────────
    _indent_xml(root)
    tree = ET.ElementTree(root)
    tree.write(str(path), encoding='unicode', xml_declaration=True)

    # Parchear la cabecera (QLC+ espera DOCTYPE especifico)
    content = path.read_text(encoding='utf-8')
    if not content.startswith('<?xml'):
        content = '<?xml version="1.0" encoding="UTF-8"?>\n' + content
    else:
        # Reemplazar la declaracion generada por ET
        lines = content.split('\n', 1)
        content = '<?xml version="1.0" encoding="UTF-8"?>\n' + (lines[1] if len(lines) > 1 else '')
    path.write_text(content, encoding='utf-8')

    return {
        'fixtures':      len(fixture_map),
        'scenes':        len(scene_ids),
        'chaser_steps':  len(scene_ids),
        'chaser_id':     chaser_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _indent_xml(elem, level: int = 0):
    """Añade indentación legible al XML (in-place)."""
    indent = '\n' + '  ' * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + '  '
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            _indent_xml(child, level + 1)
        # Ultimo hijo
        if not child.tail or not child.tail.strip():
            child.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent


# ─────────────────────────────────────────────────────────────────────────────
# Test rapido: python exporter.py
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import tempfile

    from timeline_model import Clip, CuePoint, Timeline

    # Timeline mini de prueba
    tl = Timeline(duration_ms=120_000)
    tl.clips = [
        Clip(track=0, start_ms=0,    end_ms=5000,  effect_id=0, scope='per_bar', label='Flash'),
        Clip(track=1, start_ms=5000, end_ms=10000, effect_id=10, scope='per_bar', label='Wave'),
    ]
    tl.cue_points = [
        CuePoint(slot=0, time_ms=0,     name='Intro'),
        CuePoint(slot=1, time_ms=30000, name='Drop'),
        CuePoint(slot=2, time_ms=90000, name='Outro'),
    ]

    with tempfile.TemporaryDirectory() as td:
        p = Path(td)

        # CSV clips
        n = export_clips_csv(tl, p / 'clips.csv')
        print(f"[OK] CSV clips: {n} filas -> {p/'clips.csv'}")

        # QLC+ XML
        stats = export_qlc_workspace(tl, None, p / 'show.qxw', song_name='Test')
        print(f"[OK] QLC+ XML: {stats} -> {p/'show.qxw'}")
        print((p / 'show.qxw').read_text(encoding='utf-8')[:500])
