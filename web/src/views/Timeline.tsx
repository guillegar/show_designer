import { useEffect, useMemo, useRef, useState } from "react";
import { control } from "../api/control";
import { useStore, famColor, EffectInfo, Clip, Preset } from "../store";
import { fmtTime } from "../icons";
import { ContextMenu, MenuState } from "../components/ContextMenu";
import { Browser } from "../components/Browser";

const NUM_BARS = 10;
const LANE_H = 22;
const HEAD_W = 188;

type Lane =
  | { key: string; kind: "bar"; bar: number; label: string; ip: string }
  | { key: string; kind: "fixture"; fixtureId: string; label: string; ip: string };

export function TimelineView() {
  const t = useStore((s) => s.t);
  const clips = useStore((s) => s.clips);
  const effects = useStore((s) => s.effects);
  const sections = useStore((s) => s.sections);
  const markers = useStore((s) => s.markers);
  const refreshMarkers = useStore((s) => s.refreshMarkers);
  const groups = useStore((s) => s.groups);
  const fixtures = useStore((s) => s.fixtures);
  const duration = useStore((s) => s.duration) || 1;
  const bpm = useStore((s) => s.song.bpm) || 120;
  const selectedClipId = useStore((s) => s.selectedClipId);
  const selectClip = useStore((s) => s.selectClip);
  const refreshClips = useStore((s) => s.refreshClips);
  const clipboard = useStore((s) => s.clipboard);
  const setClipboard = useStore((s) => s.setClipboard);

  const [tool, setTool] = useState<"select" | "draw" | "cut">("select");
  const [zoom, setZoom] = useState(7);
  const [snap, setSnap] = useState(true);
  const [snapGrid, setSnapGrid] = useState<"off" | "bar" | "beat" | "half" | "quarter">("quarter");
  const [beats, setBeats] = useState<number[]>([]);
  const [downbeats, setDownbeats] = useState<number[]>([]);
  const [activeFx, setActiveFx] = useState<EffectInfo | null>(null);
  const [activePreset, setActivePreset] = useState<Preset | null>(null);
  const [muted, setMuted] = useState<Record<number, boolean>>({});
  const [solo, setSolo] = useState<Record<number, boolean>>({});
  const [menu, setMenu] = useState<MenuState>(null);
  const [inspector, setInspector] = useState(false);
  const [genOpen, setGenOpen] = useState(false);
  const [genSec, setGenSec] = useState(0);
  const [genTrig, setGenTrig] = useState("on_beat");
  const [genAll, setGenAll] = useState(true);
  const [dragPreview, setDragPreview] = useState<{ id: number; start: number; end: number } | null>(null);
  const lanesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    control.call("analyzer_list_beats").then((r) => setBeats(r.beats || [])).catch(() => {});
    control.call("analyzer_list_downbeats").then((r) => setDownbeats(r.downbeats || [])).catch(() => {});
  }, []);

  const beatSec = 60 / bpm;
  const barSec = beatSec * 4;
  const W = duration * zoom;

  // efectos agrupados por familia
  const families = useMemo(() => {
    const m = new Map<string, EffectInfo[]>();
    for (const e of effects) {
      if (!m.has(e.family)) m.set(e.family, []);
      m.get(e.family)!.push(e);
    }
    return [...m.entries()];
  }, [effects]);
  const effectById = useMemo(() => new Map(effects.map((e) => [e.id, e])), [effects]);
  const famName = (eid: number) => effectById.get(eid)?.family ?? "";

  const ipOf = (bar: number) =>
    fixtures.find((f) => f.legacy_bar_idx === bar)?.target_ip ?? "";

  const laneCount = (bar: number) =>
    Math.max(1, 1 + Math.max(0, ...clips.filter((c) => c.track === bar).map((c) => c.layer)));
  const rowHeight = (bar: number) => 14 + laneCount(bar) * LANE_H;

  // Lanes = 10 barras + una por fixture no-LED (movers). Los channel clips
  // (scope='fixture:<id>') se dibujan en su lane.
  const fixtureLanes = useMemo(() => fixtures.filter((f) => f.legacy_bar_idx == null), [fixtures]);
  const lanes: Lane[] = useMemo(() => [
    ...Array.from({ length: NUM_BARS }, (_, i): Lane => ({ key: `bar-${i}`, kind: "bar", bar: i, label: `Bar ${i}`, ip: ipOf(i) })),
    ...fixtureLanes.map((f): Lane => ({ key: `fx-${f.fixture_id}`, kind: "fixture", fixtureId: f.fixture_id, label: f.label || f.fixture_id, ip: f.profile_id })),
  ], [fixtureLanes, clips]);
  const clipsForLane = (lane: Lane) => lane.kind === "bar"
    ? clips.filter((c) => (c.category ?? "pixel") === "pixel" && c.track === lane.bar)
    : clips.filter((c) => c.scope === `fixture:${lane.fixtureId}`);
  const laneHeight = (lane: Lane) => {
    const cs = clipsForLane(lane);
    const maxLayer = Math.max(0, ...cs.map((c) => c.layer));
    return 14 + (maxLayer + 1) * LANE_H;
  };

  const snapMs = (ms: number) => {
    if (!snap || snapGrid === "off") return ms;
    // imán a markers cercanos (8 px)
    const tolMs = (8 / zoom) * 1000;
    for (const m of markers) {
      if (Math.abs(m.time_ms - ms) < tolMs) return m.time_ms;
    }
    const t = ms / 1000;
    // 'beat'/'bar' → snap al beat/downbeat REAL más cercano (del analyzer)
    if (snapGrid === "beat" && beats.length) {
      let best = beats[0], bd = 1e9;
      for (const b of beats) { const d = Math.abs(b - t); if (d < bd) { bd = d; best = b; } }
      return best * 1000;
    }
    if (snapGrid === "bar" && downbeats.length) {
      let best = downbeats[0], bd = 1e9;
      for (const b of downbeats) { const d = Math.abs(b - t); if (d < bd) { bd = d; best = b; } }
      return best * 1000;
    }
    // subdivisiones del beat
    const div = snapGrid === "half" ? 0.5 : snapGrid === "quarter" ? 0.25 : 1;
    const step = beatSec * div * 1000;
    return Math.round(ms / step) * step;
  };

  // Draw-to-create (efecto base / preset píxel en barras; preset de canal en fixture lanes)
  const draw = useRef<{ lane: Lane; startMs: number } | null>(null);
  const isChannelPreset = !!(activePreset && activePreset.kind === "channel");
  const hasDrawTarget = !!(activePreset || activeFx);
  // ¿La lane acepta el target de dibujo activo?
  const laneAccepts = (lane: Lane) =>
    lane.kind === "bar" ? (!!activeFx || (!!activePreset && !isChannelPreset))
      : isChannelPreset;
  const onLaneMouseDown = (e: React.MouseEvent, lane: Lane) => {
    if (tool !== "draw" || !laneAccepts(lane)) return;
    const r = lanesRef.current!.getBoundingClientRect();
    const startMs = snapMs(((e.clientX - r.left) / zoom) * 1000);
    draw.current = { lane, startMs };
    e.preventDefault();
  };
  useEffect(() => {
    const up = async (e: MouseEvent) => {
      const d = draw.current; draw.current = null;
      if (!d) return;
      const r = lanesRef.current!.getBoundingClientRect();
      const endMs = snapMs(((e.clientX - r.left) / zoom) * 1000);
      const a = Math.min(d.startMs, endMs);
      const dur = Math.max(300, Math.abs(endMs - d.startMs));
      if (d.lane.kind === "fixture" && isChannelPreset) {
        await control.call("add_preset_clip", {
          preset_id: activePreset!.preset_id, fixture_id: d.lane.fixtureId,
          start_ms: Math.round(a), end_ms: Math.round(a + dur),
        });
      } else if (d.lane.kind === "bar" && activePreset && !isChannelPreset) {
        await control.call("add_preset_clip", {
          preset_id: activePreset.preset_id, track: d.lane.bar,
          start_ms: Math.round(a), end_ms: Math.round(a + dur), scope: "per_bar",
        });
      } else if (d.lane.kind === "bar" && activeFx) {
        await control.call("add_clip", {
          track: d.lane.bar, start_ms: Math.round(a), end_ms: Math.round(a + dur),
          effect_id: activeFx.id, scope: "per_bar",
          color: cssColorToHex(famColor(activeFx.family)), label: activeFx.name,
        });
      }
      refreshClips();
    };
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, [activeFx, activePreset, isChannelPreset, zoom, snap, beatSec, refreshClips]);

  // ── Drag de clips: mover / redimensionar (tool select) ───────────────────
  const dragRef = useRef<null | { id: number; mode: "move" | "l" | "r"; origStart: number; origEnd: number; clientX0: number }>(null);
  const previewFor = (d: NonNullable<typeof dragRef.current>, clientX: number) => {
    const dms = ((clientX - d.clientX0) / zoom) * 1000;
    let start = d.origStart, end = d.origEnd;
    if (d.mode === "move") { start = Math.max(0, snapMs(d.origStart + dms)); end = start + (d.origEnd - d.origStart); }
    else if (d.mode === "l") { start = Math.max(0, Math.min(snapMs(d.origStart + dms), d.origEnd - 100)); }
    else { end = Math.max(snapMs(d.origEnd + dms), d.origStart + 100); }
    return { start, end };
  };
  const onClipMouseDown = (e: React.MouseEvent, c: Clip) => {
    if (tool !== "select") return;   // en draw, el mousedown lo gestiona la lane
    e.stopPropagation();
    selectClip(c.id);
    if (c.locked) return;
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const offX = e.clientX - rect.left;
    const mode = offX < 7 ? "l" : offX > rect.width - 7 ? "r" : "move";
    dragRef.current = { id: c.id, mode, origStart: c.start_ms, origEnd: c.end_ms, clientX0: e.clientX };
  };
  useEffect(() => {
    const move = (e: MouseEvent) => {
      const d = dragRef.current; if (!d) return;
      const { start, end } = previewFor(d, e.clientX);
      setDragPreview({ id: d.id, start, end });
    };
    const up = (e: MouseEvent) => {
      const d = dragRef.current; dragRef.current = null;
      setDragPreview(null);
      if (!d) return;
      if (Math.abs(e.clientX - d.clientX0) < 3) return;   // click puro, no mover
      const { start, end } = previewFor(d, e.clientX);
      const params: any = { clip_id: d.id };
      if (d.mode === "move") params.new_start_ms = Math.round(start);
      else if (d.mode === "l") { params.new_start_ms = Math.round(start); params.new_end_ms = Math.round(end); }
      else params.new_end_ms = Math.round(end);
      control.call("move_clip", params).then(() => refreshClips());
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
  }, [tool, zoom, snap, snapGrid, beats, downbeats, beatSec, refreshClips]);

  // Borrar clip seleccionado (ignorar si se está escribiendo en un campo)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el?.isContentEditable) return;
      if ((e.key === "Delete" || e.key === "Backspace") && selectedClipId != null) {
        e.preventDefault();
        control.call("delete_clip", { clip_id: selectedClipId }).then(() => {
          selectClip(null);
          refreshClips();
        });
      } else if (e.ctrlKey || e.metaKey) {
        return; // no pisar atajos con Ctrl (undo/save los gestiona App)
      } else if (e.key === "v" || e.key === "V") setTool("select");
      else if (e.key === "d" || e.key === "D" || e.key === "b" || e.key === "B") setTool("draw");
      else if (e.key === "c" || e.key === "C") setTool("cut");
      else if (e.key === "q" || e.key === "Q") setSnap((s) => !s);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedClipId, selectClip, refreshClips]);

  const download = (filename: string, content: string, mime: string) => {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const doExport = async (kind: "csv" | "qlc") => {
    const r = await control.call(kind === "csv" ? "export_csv" : "export_qlc");
    if (r.ok) download(r.filename, r.content, kind === "csv" ? "text/csv" : "application/xml");
  };

  const toggleMute = (bar: number) => {
    const on = !muted[bar];
    setMuted((m) => ({ ...m, [bar]: on }));
    control.call("set_track_mute", { track: bar, on });
  };
  const toggleSolo = (bar: number) => {
    const on = !solo[bar];
    setSolo((s) => ({ ...s, [bar]: on }));
    control.call("set_track_solo", { track: bar, on });
  };

  // ── Acciones de clip (menú contextual) ──────────────────────────────────
  const afterEdit = () => refreshClips();
  const dup = (c: Clip) => control.call("duplicate_clip", { clip_id: c.id }).then(afterEdit);
  const dupToAllBars = async (c: Clip) => {
    for (let bar = 0; bar < NUM_BARS; bar++) {
      if (bar !== c.track) await control.call("duplicate_clip", { clip_id: c.id, track: bar, start_ms: c.start_ms });
    }
    afterEdit();
  };
  const mirrorLR = (c: Clip) =>
    control.call("duplicate_clip", { clip_id: c.id, track: NUM_BARS - 1 - c.track, start_ms: c.start_ms }).then(afterEdit);
  const splitAt = (c: Clip) => control.call("split_clip", { clip_id: c.id, t_ms: Math.round(t * 1000) }).then(afterEdit);
  const toggleClipMute = (c: Clip) => control.call("set_clip_mute", { clip_id: c.id, muted: !c.muted }).then(afterEdit);
  const toggleClipLock = (c: Clip) => control.call("set_clip_lock", { clip_id: c.id, locked: !c.locked }).then(afterEdit);
  const delClip = (c: Clip) => control.call("delete_clip", { clip_id: c.id }).then(() => { selectClip(null); afterEdit(); });
  const pasteAt = (track: number, startMs: number) => {
    if (!clipboard) return;
    const dur = clipboard.end_ms - clipboard.start_ms;
    control.call("add_clip", {
      track, start_ms: Math.round(startMs), end_ms: Math.round(startMs + dur),
      effect_id: clipboard.effect_id, scope: clipboard.scope, color: clipboard.color,
      layer: clipboard.layer, label: clipboard.label, params: clipboard.params,
    }).then(afterEdit);
  };

  const openClipMenu = (e: React.MouseEvent, c: Clip) => {
    e.preventDefault(); e.stopPropagation();
    selectClip(c.id);
    const inside = c.start_ms < t * 1000 && t * 1000 < c.end_ms;
    setMenu({
      x: e.clientX, y: e.clientY, items: [
        { label: "Propiedades…", onClick: () => setInspector(true) },
        { type: "sep" },
        { label: "Duplicar", onClick: () => dup(c) },
        ...(c.track >= 0 ? [
          { label: "Duplicar a todas las barras", onClick: () => dupToAllBars(c) },
          { label: "Espejar L↔R", onClick: () => mirrorLR(c) },
        ] : []),
        { label: "Dividir en cursor", onClick: () => splitAt(c), disabled: !inside },
        { label: c.muted ? "Activar (unmute)" : "Silenciar (mute)", onClick: () => toggleClipMute(c) },
        { label: c.locked ? "Desbloquear" : "Bloquear", onClick: () => toggleClipLock(c) },
        { type: "sep" },
        { label: "Copiar", onClick: () => setClipboard(c), hint: "Ctrl+C" },
        { label: "Borrar", onClick: () => delClip(c), danger: true, hint: "Supr" },
      ],
    });
  };

  const openLaneMenu = (e: React.MouseEvent, lane: Lane) => {
    e.preventDefault();
    const r = lanesRef.current!.getBoundingClientRect();
    const startMs = snapMs(((e.clientX - r.left) / zoom) * 1000);
    const end = Math.round(startMs + 2000);
    const items: any[] = [];
    if (lane.kind === "bar") {
      items.push({ label: clipboard ? "Pegar aquí" : "Pegar (nada copiado)", disabled: !clipboard, onClick: () => pasteAt(lane.bar, startMs) });
      if (activePreset && !isChannelPreset) {
        items.push({ label: `Dibujar "${activePreset.name}" aquí`, onClick: () => control.call("add_preset_clip", { preset_id: activePreset.preset_id, track: lane.bar, start_ms: Math.round(startMs), end_ms: end, scope: "per_bar" }).then(afterEdit) });
      } else if (activeFx) {
        items.push({ label: `Dibujar "${activeFx.name}" aquí`, onClick: () => control.call("add_clip", { track: lane.bar, start_ms: Math.round(startMs), end_ms: end, effect_id: activeFx.id, scope: "per_bar", label: activeFx.name }).then(afterEdit) });
      } else {
        items.push({ label: "Elige un efecto/preset del banco", disabled: true, onClick: () => {} });
      }
    } else {
      if (isChannelPreset) {
        items.push({ label: `Dibujar "${activePreset!.name}" aquí`, onClick: () => control.call("add_preset_clip", { preset_id: activePreset!.preset_id, fixture_id: lane.fixtureId, start_ms: Math.round(startMs), end_ms: end }).then(afterEdit) });
      } else {
        items.push({ label: "Elige un preset de MOVER (⬡) del banco", disabled: true, onClick: () => {} });
      }
    }
    setMenu({ x: e.clientX, y: e.clientY, items });
  };

  // Info del efecto activo (preset o base) para generar
  const drawInfo = activePreset && !isChannelPreset
    ? { effect_id: activePreset.base_effect_id, color: activePreset.color, params: activePreset.params, name: activePreset.name }
    : activeFx ? { effect_id: activeFx.id, color: "#3a7acc", params: {}, name: activeFx.name } : null;
  const runGenerate = async () => {
    if (!drawInfo || !sections[genSec]) return;
    const s = sections[genSec];
    const base = { start_sec: s.start, end_sec: s.end, effect_id: drawInfo.effect_id, color: drawInfo.color, clip_params: drawInfo.params, trigger: genTrig, scope: "per_bar" };
    if (genAll) { for (let b = 0; b < NUM_BARS; b++) await control.call("generate_section", { ...base, track: b }); }
    else await control.call("generate_section", { ...base, track: 0 });
    setGenOpen(false);
    refreshClips();
  };

  const selClip = clips.find((c) => c.id === selectedClipId);
  const barTicks = Math.ceil(duration / barSec);

  return (
    <div className="tl">
      {/* LEFT — banco de efectos + efectos base */}
      <Browser
        activeFxId={activeFx?.id ?? null}
        activePresetId={activePreset?.preset_id ?? null}
        onPickEffect={(fx) => { setActiveFx(fx); setActivePreset(null); setTool("draw"); }}
        onPickPreset={(p) => { setActivePreset(p); setActiveFx(null); setTool("draw"); }}
      />

      {/* RIGHT — timeline */}
      <div className="tl-main">
        <div className="tl-toolbar">
          <div className="seg">
            {(["select", "draw", "cut"] as const).map((id) => (
              <button key={id} className={tool === id ? "on" : ""} onClick={() => setTool(id)}>{id}</button>
            ))}
          </div>
          <button className="btn sm ghost" title="Deshacer (Ctrl+Z)" onClick={() => control.call("undo").then(refreshClips)}>↩</button>
          <button className="btn sm ghost" title="Rehacer (Ctrl+Shift+Z)" onClick={() => control.call("redo").then(refreshClips)}>↪</button>
          {tool === "draw" && activePreset && (
            <div className="draw-tag" style={{ borderColor: activePreset.color }}>
              <span className="sw" style={{ background: activePreset.color }} />Dibujando preset: <b>{activePreset.name}</b>
            </div>
          )}
          {tool === "draw" && !activePreset && activeFx && (
            <div className="draw-tag" style={{ borderColor: famColor(activeFx.family) }}>
              <span className="sw" style={{ background: famColor(activeFx.family) }} />Dibujando: <b>{activeFx.name}</b>
            </div>
          )}
          {tool === "draw" && !hasDrawTarget && <span className="muted" style={{ fontSize: 11.5 }}>Elige algo del banco</span>}
          <span className="ph-spacer" style={{ flex: 1 }} />
          <button className="btn sm ghost" onClick={() => setSnap((s) => !s)} style={snap ? { color: "var(--acc)" } : undefined}>⊟ Snap {snap ? "on" : "off"}</button>
          <select className="field" style={{ height: 26, width: 88 }} value={snapGrid}
            disabled={!snap} onChange={(e) => setSnapGrid(e.target.value as any)} title="Rejilla de snap">
            <option value="bar">compás</option>
            <option value="beat">beat</option>
            <option value="half">½ beat</option>
            <option value="quarter">¼ beat</option>
            <option value="off">libre</option>
          </select>
          <button className="btn sm" onClick={() => setGenOpen(true)} disabled={!drawInfo} title="Generar clips en una sección con el efecto/preset activo">✨ Generar</button>
          <button className="btn sm ghost" title="Exportar CSV de clips" onClick={() => doExport("csv")}>⬇ CSV</button>
          <button className="btn sm ghost" title="Exportar workspace QLC+" onClick={() => doExport("qlc")}>⬇ QLC+</button>
          <div className="zoomctl">
            <button className="btn sm ghost" onClick={() => setZoom((z) => Math.max(3, z - 1.5))}>−</button>
            <span className="mono" style={{ width: 34, textAlign: "center", fontSize: 11, color: "var(--txt-3)" }}>{Math.round(zoom * 10) / 10}×</span>
            <button className="btn sm ghost" onClick={() => setZoom((z) => Math.min(20, z + 1.5))}>+</button>
          </div>
        </div>

        {/* ruler */}
        <div className="tl-rulerrow">
          <div className="tl-corner" style={{ width: HEAD_W }}><span className="mono" style={{ fontSize: 10, color: "var(--txt-4)" }}>BAR · BEAT</span></div>
          <div className="tl-rulerclip">
            <div className="tl-ruler" style={{ width: W }}
              title="Doble-clic: añadir marcador"
              onDoubleClick={(e) => {
                const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
                const ms = Math.round(((e.clientX - r.left) / zoom) * 1000);
                const name = window.prompt("Nombre del marcador:", fmtTime(ms / 1000));
                if (name != null) control.call("add_marker", { time_ms: ms, name }).then(refreshMarkers);
              }}>
              {sections.map((s, i) => {
                const next = sections[i + 1]?.start ?? duration;
                return (
                  <div key={i} className="ruler-sec" style={{ left: s.start * zoom, width: (next - s.start) * zoom, color: "var(--txt-3)" }}>
                    <span>{s.name}</span>
                  </div>
                );
              })}
              {Array.from({ length: barTicks }, (_, i) => (
                <div key={i} className="ruler-tick" style={{ left: i * barSec * zoom }}><span>{i + 1}</span></div>
              ))}
              {markers.map((m, i) => (
                <div key={i} className="ruler-marker" style={{ left: m.time_ms / 1000 * zoom }}
                  onContextMenu={(e) => { e.preventDefault(); control.call("delete_marker", { time_ms: m.time_ms }).then(refreshMarkers); }}
                  title={`${m.name} (clic derecho: borrar)`}>
                  <span style={{ background: m.color || "var(--warn)" }}>{m.name}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* tracks */}
        <div className="tl-scroll">
          <div className="tl-grid" style={{ width: HEAD_W + W }}>
            <div className="tl-heads" style={{ width: HEAD_W }}>
              {lanes.map((lane) => lane.kind === "bar" ? (
                <div key={lane.key} className="tl-head" style={{ height: rowHeight(lane.bar) }}>
                  <span className="sw" style={{ background: `oklch(0.75 0.16 ${lane.bar * 36})` }} />
                  <div className="hd-txt">
                    <div className="hd-name">Bar {lane.bar}{laneCount(lane.bar) > 1 ? ` [${laneCount(lane.bar)}]` : ""}</div>
                    <div className="hd-ip mono">{lane.ip}</div>
                  </div>
                  <div className="hd-btns">
                    <button className={"ms m" + (muted[lane.bar] ? " on" : "")} onClick={() => toggleMute(lane.bar)}>M</button>
                    <button className={"ms s" + (solo[lane.bar] ? " on" : "")} onClick={() => toggleSolo(lane.bar)}>S</button>
                  </div>
                </div>
              ) : (
                <div key={lane.key} className="tl-head" style={{ height: laneHeight(lane) }}>
                  <span className="sw" style={{ background: "var(--acc-2)" }} />
                  <div className="hd-txt">
                    <div className="hd-name">⬡ {lane.label}</div>
                    <div className="hd-ip mono">{lane.ip}</div>
                  </div>
                </div>
              ))}
            </div>

            <div className="tl-lanes" style={{ width: W }} ref={lanesRef}>
              <div className="tl-gridlines">
                {Array.from({ length: barTicks }, (_, i) => (
                  <div key={i} className="gl bar" style={{ left: i * barSec * zoom }} />
                ))}
              </div>
              {sections.map((s, i) => {
                const next = sections[i + 1]?.start ?? duration;
                return <div key={i} className="lane-sec" style={{ left: s.start * zoom, width: (next - s.start) * zoom, background: "color-mix(in oklab, var(--txt-3) 5%, transparent)" }} />;
              })}

              {lanes.map((lane) => {
                const h = lane.kind === "bar" ? rowHeight(lane.bar) : laneHeight(lane);
                const dim = lane.kind === "bar" && muted[lane.bar];
                return (
                  <div key={lane.key} className="tl-row" style={{ height: h, opacity: dim ? 0.4 : 1 }}
                    onMouseDown={(e) => onLaneMouseDown(e, lane)}
                    onContextMenu={(e) => openLaneMenu(e, lane)}>
                    {clipsForLane(lane).map((c) => {
                      const col = c.color || famColor(famName(c.effect_id));
                      const dp = dragPreview && dragPreview.id === c.id ? dragPreview : null;
                      const cs = dp ? dp.start : c.start_ms;
                      const ce = dp ? dp.end : c.end_ms;
                      return (
                        <div key={c.id}
                          className={"clip" + (selectedClipId === c.id ? " sel" : "") + (c.locked ? " locked" : "")}
                          onMouseDown={(e) => onClipMouseDown(e, c)}
                          onClick={(e) => { e.stopPropagation(); selectClip(c.id); }}
                          onContextMenu={(e) => openClipMenu(e, c)}
                          onDoubleClick={(e) => { e.stopPropagation(); selectClip(c.id); setInspector(true); }}
                          style={{
                            left: (cs / 1000) * zoom, width: ((ce - cs) / 1000) * zoom - 2,
                            top: 7 + c.layer * LANE_H, height: LANE_H - 4,
                            background: `color-mix(in oklab, ${col} 32%, var(--bg-2))`, borderColor: col,
                            cursor: tool === "select" && !c.locked ? "grab" : "pointer",
                          }}>
                          <span className="clip-grip-l" />
                          <span className="clip-bar" style={{ background: col }} />
                          <span className="clip-name">{c.label || (c.preset_id ? "preset" : effectById.get(c.effect_id)?.name) || "clip"}</span>
                          <span className="clip-grip" />
                        </div>
                      );
                    })}
                  </div>
                );
              })}

              {markers.map((m, i) => (
                <div key={"m" + i} className="lane-marker" style={{ left: m.time_ms / 1000 * zoom, background: m.color || "var(--warn)" }} />
              ))}

              <div className="tl-playhead" style={{ left: t * zoom }}>
                <div className="ph-flag mono">{fmtTime(t)}</div>
              </div>
            </div>
          </div>
        </div>

        <div className="tl-status">
          <span className="chip acc"><span className="d" />{clips.length} clips</span>
          <span className="muted">{NUM_BARS} tracks</span>
          <span className="ph-spacer" style={{ flex: 1 }} />
          {selClip && (
            <span className="mono muted">
              {selClip.label || effectById.get(selClip.effect_id)?.name} · {fmtTime(selClip.start_ms / 1000)}→{fmtTime(selClip.end_ms / 1000)} · Bar {selClip.track}
            </span>
          )}
          <span className="muted">Borrar <span className="kbd">⌫</span></span>
        </div>
      </div>

      {inspector && selClip && (
        <div className="clip-inspector">
          <div className="ci-head">
            <h4>Clip · {selClip.label || effectById.get(selClip.effect_id)?.name || "—"}</h4>
            <button className="x" onClick={() => setInspector(false)}>×</button>
          </div>
          <div className="ci-body">
            <div className="ci-row">
              <label>Efecto</label>
              <select value={selClip.effect_id}
                onChange={(e) => control.call("set_clip_effect", { clip_id: selClip.id, effect_id: +e.target.value, label: effectById.get(+e.target.value)?.name }).then(afterEdit)}>
                {families.map(([f, list]) => (
                  <optgroup key={f} label={f || "otros"}>
                    {list.map((fx) => <option key={fx.id} value={fx.id}>{fx.name}</option>)}
                  </optgroup>
                ))}
              </select>
            </div>
            <div className="ci-row">
              <label>Scope</label>
              <select value={selClip.scope}
                onChange={(e) => control.call("set_clip_scope", { clip_id: selClip.id, scope: e.target.value }).then(afterEdit)}>
                <option value="per_bar">per_bar</option>
                <option value="global">global</option>
                {groups.map((g) => <option key={g.name} value={`group:${g.name}`}>Grupo: {g.name}</option>)}
                {!["per_bar", "global"].includes(selClip.scope) && !groups.some((g) => `group:${g.name}` === selClip.scope) && <option value={selClip.scope}>{selClip.scope}</option>}
              </select>
            </div>
            <div className="ci-row">
              <label>Color</label>
              <input type="color" value={selClip.color || "#3a7acc"}
                onChange={(e) => control.call("set_clip_color", { clip_id: selClip.id, color: e.target.value }).then(afterEdit)} />
            </div>
            {Object.keys(selClip.params || {}).length > 0 && <div className="ci-sub">Parámetros</div>}
            {Object.entries(selClip.params || {}).map(([k, v]) => (
              <div className="ci-row" key={k}>
                <label>{k}</label>
                <input className="mono" defaultValue={String(v)} key={k + selClip.id}
                  onBlur={(e) => {
                    let val: any = e.target.value;
                    const n = Number(val);
                    if (val.trim() !== "" && !isNaN(n)) val = n;
                    control.call("set_clip_params", { clip_id: selClip.id, params: { [k]: val } }).then(afterEdit);
                  }} />
              </div>
            ))}
            <div className="ci-row" style={{ marginTop: 4, gap: 6 }}>
              <button className="btn sm" style={{ flex: 1 }} onClick={() => toggleClipMute(selClip)}>{selClip.muted ? "Unmute" : "Mute"}</button>
              <button className="btn sm" style={{ flex: 1 }} onClick={() => toggleClipLock(selClip)}>{selClip.locked ? "Unlock" : "Lock"}</button>
              <button className="btn sm" style={{ color: "var(--bad)" }} onClick={() => { delClip(selClip); setInspector(false); }}>Borrar</button>
            </div>
          </div>
        </div>
      )}

      <ContextMenu state={menu} onClose={() => setMenu(null)} />

      {genOpen && drawInfo && (
        <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setGenOpen(false); }}>
          <div className="preset-editor">
            <div className="ci-head"><h4>Generar · {drawInfo.name}</h4><button className="x" onClick={() => setGenOpen(false)}>×</button></div>
            <div className="ci-body">
              <div className="ci-row"><label>Sección</label>
                <select value={genSec} onChange={(e) => setGenSec(+e.target.value)}>
                  {sections.map((s, i) => <option key={i} value={i}>{s.name} ({fmtTime(s.start)})</option>)}
                </select></div>
              <div className="ci-row"><label>Disparo</label>
                <select value={genTrig} onChange={(e) => setGenTrig(e.target.value)}>
                  <option value="on_beat">en cada beat</option>
                  <option value="on_downbeat">en cada compás</option>
                  <option value="on_kick">en cada kick</option>
                  <option value="on_snare">en cada snare</option>
                  <option value="on_drop">en drops</option>
                  <option value="every_500ms">cada 500 ms</option>
                  <option value="fill">rellenar (1 clip)</option>
                </select></div>
              <div className="ci-row"><label>Barras</label>
                <select value={genAll ? "all" : "one"} onChange={(e) => setGenAll(e.target.value === "all")}>
                  <option value="all">Todas (0-9)</option>
                  <option value="one">Solo Bar 0</option>
                </select></div>
              <div className="ci-row" style={{ marginTop: 6 }}>
                <button className="btn primary sm" style={{ flex: 1 }} onClick={runGenerate}>Generar</button>
              </div>
              <p className="muted" style={{ fontSize: 10.5, lineHeight: 1.4 }}>Crea clips con el efecto/preset activo sincronizados a los eventos de la sección.</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// color CSS var → hex aproximado para guardar en el clip (el backend espera #hex).
// Como los colores se derivan de la familia en render, basta un hex neutro.
function cssColorToHex(_v: string): string {
  return "#3a7acc";
}
