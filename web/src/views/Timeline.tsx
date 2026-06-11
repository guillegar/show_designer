import { useEffect, useMemo, useRef, useState } from "react";
import Moveable from "react-moveable";
import Selecto from "react-selecto";
import { control } from "../api/control";
import { useStore, famColor, EffectInfo, Clip, Preset } from "../store";
import { fmtTime } from "../icons";
import { ContextMenu, MenuState } from "../components/ContextMenu";
import { Browser } from "../components/Browser";
import { ClipInspector } from "../components/ClipInspector";
import { ToastContainer, useToast } from "../components/Toast";
import { HelpOverlay } from "../components/HelpOverlay";
import { xToMs, msToX } from "./timelineGeometry";

const NUM_BARS = 10;
const LANE_H = 22;
const HEAD_W = 188;

type Lane =
  | { key: string; kind: "bar"; bar: number; label: string; ip: string }
  | { key: string; kind: "fixture"; fixtureId: string; label: string; ip: string };

export function TimelineView() {
  const { toasts, addToast, dismissToast } = useToast();

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

  const MIN_ZOOM = 2;
  const MAX_ZOOM = 50;
  const DEFAULT_ZOOM = 7;

  const [tool, setTool] = useState<"select" | "draw" | "cut">("select");
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
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
  const [lastEffectDuration, setLastEffectDuration] = useState(() => {
    const saved = localStorage.getItem("sd_lastEffectDuration");
    return saved ? parseInt(saved, 10) : 500;
  });
  const [selectedClipIds, setSelectedClipIds] = useState<Set<string>>(new Set());
  const [showHelp, setShowHelp] = useState(false);
  const lanesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    control.call("analyzer_list_beats").then((r) => setBeats(r.beats || [])).catch(() => {});
    control.call("analyzer_list_downbeats").then((r) => setDownbeats(r.downbeats || [])).catch(() => {});
  }, []);

  useEffect(() => {
    localStorage.setItem("sd_lastEffectDuration", lastEffectDuration.toString());
  }, [lastEffectDuration]);

  // Remember duration when clip is selected
  useEffect(() => {
    if (selectedClipId != null) {
      const c = clips.find(x => x.id === selectedClipId);
      if (c) {
        const dur = c.end_ms - c.start_ms;
        if (dur > 100 && dur < 60000) {
          setLastEffectDuration(dur);
        }
      }
    }
  }, [selectedClipId, clips]);

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

    const tolMs = (8 / zoom) * 1000;

    // Snap to markers first (8px tolerance)
    for (const m of markers) {
      if (Math.abs(m.time_ms - ms) < tolMs) return m.time_ms;
    }

    // Snap to computed gridlines
    if (gridlines.length > 0) {
      const nearestLine = gridlines.reduce((best, { t }) => {
        const lineMs = t * 1000;
        return Math.abs(lineMs - ms) < Math.abs(best - ms) ? lineMs : best;
      }, ms);

      if (Math.abs(nearestLine - ms) < tolMs) return nearestLine;
    }

    // Fallback: snap using BPM calculation
    const div = snapGrid === "half" ? 0.5 : snapGrid === "quarter" ? 0.25 : 1;
    const step = beatSec * div * 1000;
    return Math.round(ms / step) * step;
  };

  // Memoized gridline computation — ADAPTIVE to zoom.
  // Visual density is decoupled from snap granularity: only the finest level whose
  // lines are at least MIN_PX apart is drawn. Otherwise lines collapse into a solid
  // wall (e.g. ¼ beat at 7× = ~1.7px apart). Snapping still uses the chosen grid.
  const gridlines = useMemo(() => {
    const lines: { t: number; kind: "bar" | "beat" | "subdiv" }[] = [];

    if (snapGrid === "off") return [];

    const MIN_PX = 7; // minimum on-screen gap between rendered lines

    const subStep = snapGrid === "quarter" ? beatSec * 0.25
      : snapGrid === "half" ? beatSec * 0.5
      : beatSec;
    const wantsSub = snapGrid === "half" || snapGrid === "quarter";
    const wantsBeats = snapGrid !== "bar";

    // Pick the finest level that is still readable at the current zoom
    let renderStep: number;
    if (wantsSub && subStep * zoom >= MIN_PX) renderStep = subStep;
    else if (wantsBeats && beatSec * zoom >= MIN_PX) renderStep = beatSec;
    else if (barSec * zoom >= MIN_PX) renderStep = barSec;
    else return []; // even bars would be a wall — hide the grid

    const tol = 0.001;
    const MAX = 1500; // safety cap
    let n = 0;
    for (let t = 0; t <= duration + barSec && n < MAX; t += renderStep, n++) {
      const isBar = Math.abs(t - Math.round(t / barSec) * barSec) < tol;
      const isBeat = Math.abs(t - Math.round(t / beatSec) * beatSec) < tol;
      lines.push({ t, kind: isBar ? "bar" : isBeat ? "beat" : "subdiv" });
    }
    return lines;
  }, [snapGrid, bpm, duration, beatSec, barSec, zoom]);

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

  // Click-to-paint: apply effect to existing clip in draw mode
  // Or Ctrl+Click for multi-select
  const onClipClick = async (e: React.MouseEvent, c: Clip) => {
    e.stopPropagation();

    // Ctrl+Click: multi-select toggle
    if ((e.ctrlKey || e.metaKey) && tool === "select") {
      const newSet = new Set(selectedClipIds);
      if (newSet.has(c.id)) {
        newSet.delete(c.id);
      } else {
        newSet.add(c.id);
      }
      setSelectedClipIds(newSet);
      return;
    }

    // Draw mode: paint selected clips
    if (tool === "draw") {
      // Apply effect to all selected clips, or just this one if none selected
      const targets = selectedClipIds.size > 0 ? Array.from(selectedClipIds) : [c.id];

      for (const clipId of targets) {
        try {
          if (activePreset) {
            await control
              .call("set_clip_preset", {
                clip_id: clipId,
                preset_id: activePreset.preset_id,
              })
              .catch(async () => {
                if (activeFx) {
                  await control.call("set_clip_effect", {
                    clip_id: clipId,
                    effect_id: activeFx.id,
                  });
                }
              });
          } else if (activeFx) {
            await control.call("set_clip_effect", {
              clip_id: clipId,
              effect_id: activeFx.id,
            });
          }
        } catch (err) {
          console.warn(`Failed to paint clip ${clipId}:`, err);
        }
      }

      selectClip(c.id);
      setLastEffectDuration(c.end_ms - c.start_ms);
      addToast(
        `✓ ${targets.length} clip(s) painted`,
        "success"
      );
      await refreshClips();
      // Create undo snapshot
      try {
        await control.call("snapshot");
      } catch (e) {
        // Undo not available
      }
      return;
    }
  };
  useEffect(() => {
    const up = async (e: MouseEvent) => {
      const d = draw.current; draw.current = null;
      if (!d) return;
      const r = lanesRef.current!.getBoundingClientRect();
      const endMs = snapMs(((e.clientX - r.left) / zoom) * 1000);
      const a = Math.min(d.startMs, endMs);
      const dragDist = Math.abs(endMs - d.startMs);

      // If drag is very short (< 50ms), use last remembered duration
      let dur = dragDist;
      if (dragDist < 50) {
        dur = lastEffectDuration;
      } else if (dragDist > 100) {
        // Drag was long enough: remember this duration for next short click
        setLastEffectDuration(dragDist);
      }
      dur = Math.max(100, dur);
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

  // ── Interacción de clips: Moveable (mover/redimensionar) + Selecto (multi-sel) ──
  const moveableRef = useRef<any>(null);
  const selectoRef = useRef<any>(null);
  const rowRefs = useRef<Map<string, HTMLElement>>(new Map());
  const [moveTargets, setMoveTargets] = useState<(HTMLElement | SVGElement)[]>([]);
  const [dropBar, setDropBar] = useState<number | null>(null);
  const dropPosRef = useRef<{ bar: number; layer: number } | null>(null); // destino bajo el cursor
  const [clipboardClips, setClipboardClips] = useState<Clip[]>([]); // portapapeles multi-clip

  // Líneas-guía de snap (rejilla BPM) como posiciones X en píxeles para Moveable.
  const verticalGuidelines = useMemo(
    () => (snap ? gridlines.map((g) => msToX(g.t * 1000, zoom)) : []),
    [snap, gridlines, zoom]
  );

  // Hit-test: clientY → { bar, layer } usando rects MEDIDOS (las filas tienen
  // altura variable según nº de layers). El layer se deduce de la Y dentro de la
  // fila; se permite una capa nueva justo debajo de las existentes.
  const barLayerAtClientY = (clientY: number): { bar: number; layer: number } | null => {
    let res: { bar: number; layer: number } | null = null;
    rowRefs.current.forEach((el, key) => {
      if (!key.startsWith("bar-")) return;
      const r = el.getBoundingClientRect();
      if (clientY >= r.top && clientY < r.bottom) {
        const bar = parseInt(key.slice(4), 10);
        const localY = clientY - r.top - 7; // 7 = padding superior usado en el clip
        const maxLayer = Math.max(0, ...clips.filter((c) => c.track === bar).map((c) => c.layer));
        // round (no floor): cada capa tiene una zona de destino amplia; se permite
        // una capa nueva justo debajo de las existentes.
        const layer = Math.max(0, Math.min(Math.round(localY / LANE_H), maxLayer + 1));
        res = { bar, layer };
      }
    });
    return res;
  };

  const clipFromEl = (el: Element | null | undefined): Clip | undefined => {
    const id = el?.getAttribute?.("data-clip-id");
    return id != null ? clips.find((c) => c.id === id) : undefined;
  };

  const commitMoves = async (calls: Array<Record<string, any>>) => {
    if (!calls.length) { moveableRef.current?.updateRect(); return; }
    try {
      for (const params of calls) await control.call("move_clip", params);
      await refreshClips();
      try { await control.call("snapshot"); } catch {}
    } catch (err) {
      console.error("[Timeline] move_clip failed:", err);
    }
  };

  // Mantener los targets de Moveable sincronizados con la selección (sin locked).
  useEffect(() => {
    if (!lanesRef.current) { setMoveTargets([]); return; }
    const ids = selectedClipIds.size > 0
      ? [...selectedClipIds]
      : (selectedClipId != null ? [selectedClipId] : []);
    const els = ids
      .filter((id) => !clips.find((c) => c.id === id)?.locked)
      .map((id) => lanesRef.current!.querySelector<HTMLElement>(`[data-clip-id="${id}"]`))
      .filter((el): el is HTMLElement => !!el);
    setMoveTargets(els);
  }, [selectedClipId, selectedClipIds, clips, zoom, lanes.length, tool]);

  // Reposicionar los controles de Moveable tras cambios de layout.
  useEffect(() => { moveableRef.current?.updateRect(); }, [zoom, clips, moveTargets]);

  // ── Handlers Moveable: mover (1 clip) ──────────────────────────────────────
  const onClipDrag = (e: any) => {
    // El clip sigue al cursor en ambos ejes (estilo DAW); sube z-index para no
    // quedar tapado por otras filas al cruzarlas.
    e.target.style.transform = `translate(${e.translate[0]}px, ${e.translate[1]}px)`;
    e.target.style.zIndex = "20";
    const clientY = e.clientY ?? e.inputEvent?.clientY;
    if (clientY != null) {
      const pos = barLayerAtClientY(clientY);
      dropPosRef.current = pos;
      setDropBar(pos ? pos.bar : null);
    }
  };
  const onClipDragEnd = (e: any) => {
    const dest = dropPosRef.current;
    dropPosRef.current = null;
    setDropBar(null);
    e.target.style.transform = ""; // React reposiciona vía `left` tras el commit
    e.target.style.zIndex = "";
    const c = clipFromEl(e.target);
    if (!c || !e.lastEvent) { moveableRef.current?.updateRect(); return; }
    const dx = e.lastEvent.translate[0];
    const newStart = Math.max(0, Math.round(c.start_ms + xToMs(dx, zoom)));
    const params: any = { clip_id: c.id, new_start_ms: newStart };
    if (c.track >= 0 && dest) {
      if (dest.bar !== c.track) params.new_track = dest.bar;
      if (dest.layer !== c.layer) params.new_layer = dest.layer;
    }
    commitMoves([params]);
  };

  // ── Handlers Moveable: redimensionar (1 clip) ──────────────────────────────
  const onClipResize = (e: any) => {
    e.target.style.width = `${e.width}px`;
    e.target.style.transform = e.drag.transform;
  };
  const onClipResizeEnd = (e: any) => {
    e.target.style.transform = "";
    e.target.style.width = "";
    const c = clipFromEl(e.target);
    if (!c || !e.lastEvent) { moveableRef.current?.updateRect(); return; }
    const { width, drag, direction } = e.lastEvent;
    let newStart = c.start_ms;
    let newEnd = c.end_ms;
    if (direction[0] === -1) { // borde izquierdo: cambia inicio
      newStart = Math.max(0, Math.round(c.start_ms + xToMs(drag.translate[0], zoom)));
      newEnd = Math.max(newStart + 50, Math.round(newStart + xToMs(width, zoom)));
    } else { // borde derecho: cambia fin
      newEnd = Math.max(c.start_ms + 50, Math.round(c.start_ms + xToMs(width, zoom)));
    }
    commitMoves([{ clip_id: c.id, new_start_ms: newStart, new_end_ms: newEnd }]);
  };

  // ── Handlers Moveable: mover en GRUPO (multi-selección) ────────────────────
  // Sigue al cursor en XY; cada clip resuelve su bar+layer destino por su propia
  // posición (hit-test del centro), preservando la disposición relativa del grupo.
  const onClipDragGroup = (e: any) => {
    e.events.forEach((ev: any) => {
      ev.target.style.transform = `translate(${ev.translate[0]}px, ${ev.translate[1]}px)`;
      ev.target.style.zIndex = "20";
    });
  };
  const onClipDragGroupEnd = (e: any) => {
    const calls: any[] = [];
    e.events.forEach((ev: any) => {
      const rect = ev.target.getBoundingClientRect();
      const centerY = rect.top + rect.height / 2;
      const dest = barLayerAtClientY(centerY);
      ev.target.style.transform = "";
      ev.target.style.zIndex = "";
      const c = clipFromEl(ev.target);
      if (!c || !ev.lastEvent) return;
      const params: any = { clip_id: c.id, new_start_ms: Math.max(0, Math.round(c.start_ms + xToMs(ev.lastEvent.translate[0], zoom))) };
      if (c.track >= 0 && dest) {
        if (dest.bar !== c.track) params.new_track = dest.bar;
        if (dest.layer !== c.layer) params.new_layer = dest.layer;
      }
      calls.push(params);
    });
    commitMoves(calls);
  };

  // ── Selecto: rubber-band + delegar drag a Moveable (gesto único) ───────────
  const onSelectoDragStart = (e: any) => {
    if (tool !== "select") { e.stop(); return; }
    const target = e.inputEvent.target as HTMLElement;
    const mv = moveableRef.current;
    if (mv?.isMoveableElement?.(target) || moveTargets.some((t) => t === target || (t as HTMLElement).contains?.(target))) {
      e.stop();
    }
  };
  const onSelectoSelectEnd = (e: any) => {
    if (e.isDragStart) {
      e.inputEvent.preventDefault();
      moveableRef.current?.waitToChangeTarget?.().then(() => {
        moveableRef.current?.dragStart(e.inputEvent);
      });
    }
    setMoveTargets(e.selected);
    const ids = (e.selected as HTMLElement[])
      .map((el) => el.getAttribute("data-clip-id") || "")
      .filter((s) => s !== "");
    setSelectedClipIds(new Set(ids));
    if (ids.length === 1) selectClip(ids[0]);
    else if (ids.length === 0) selectClip(null);
  };

  // Copy/Paste & Keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el?.isContentEditable) return;

      if ((e.key === "Delete" || e.key === "Backspace") && (selectedClipIds.size > 0 || selectedClipId != null)) {
        e.preventDefault();
        const ids = selectedClipIds.size > 0 ? [...selectedClipIds] : [selectedClipId as string];
        (async () => {
          for (const id of ids) await control.call("delete_clip", { clip_id: id });
          setSelectedClipIds(new Set());
          setMoveTargets([]);
          selectClip(null);
          await refreshClips();
          try { await control.call("snapshot"); } catch {}
        })();
      } else if (e.key === "0" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        setZoom(DEFAULT_ZOOM);
      } else if (e.key === "[") {
        e.preventDefault();
        setLastEffectDuration(d => Math.max(100, d - 50));
      } else if (e.key === "]") {
        e.preventDefault();
        setLastEffectDuration(d => Math.min(60000, d + 50));
      } else if ((e.key === "c" || e.key === "C") && (e.ctrlKey || e.metaKey)) {
        // Copy: grupo (selectedClipIds) o clip único
        e.preventDefault();
        const ids = selectedClipIds.size > 0
          ? [...selectedClipIds]
          : (selectedClipId != null ? [selectedClipId] : []);
        const picked = ids.map((id) => clips.find((x) => x.id === id)).filter(Boolean) as Clip[];
        if (picked.length) {
          setClipboardClips(picked);
          setClipboard(picked[0]);
          addToast(`✓ ${picked.length} clip(s) copiado(s)`, "success");
        }
      } else if ((e.key === "a" || e.key === "A") && (e.ctrlKey || e.metaKey) && !e.shiftKey) {
        // Ctrl+A: select all clips in current track
        e.preventDefault();
        if (selectedClipId != null) {
          const c = clips.find(x => x.id === selectedClipId);
          if (c) {
            const trackClips = clips.filter(x => x.track === c.track);
            const ids = new Set(trackClips.map(x => x.id));
            setSelectedClipIds(ids);
            addToast(`✓ ${ids.size} clips selected (track)`, "info");
          }
        }
      } else if ((e.key === "a" || e.key === "A") && e.shiftKey && (e.ctrlKey || e.metaKey)) {
        // Ctrl+Shift+A: select all clips globally
        e.preventDefault();
        const ids = new Set(clips.map(x => x.id));
        setSelectedClipIds(ids);
        addToast(`✓ ${ids.size} clips selected (all)`, "info");
      } else if ((e.key === "v" || e.key === "V") && (e.ctrlKey || e.metaKey)) {
        // Paste: pega el grupo (o clip único) anclado al playhead, manteniendo
        // los offsets relativos de tiempo y los track/layer originales.
        e.preventDefault();
        const src = clipboardClips.length ? clipboardClips : (clipboard ? [clipboard] : []);
        if (src.length) {
          const minStart = Math.min(...src.map((cl) => cl.start_ms));
          const anchor = Math.round(useStore.getState().t * 1000); // playhead actual
          (async () => {
            const newIds: string[] = [];
            for (const cl of src) {
              const dur = cl.end_ms - cl.start_ms;
              const start = anchor + (cl.start_ms - minStart);
              const res = await control.call("add_clip", {
                track: cl.track,
                start_ms: Math.round(start),
                end_ms: Math.round(start + dur),
                effect_id: cl.effect_id,
                scope: cl.scope,
                color: cl.color,
                label: cl.label,
                layer: cl.layer,
                params: cl.params,
              });
              const id = res?.clip?.id;
              if (id != null) newIds.push(id);
            }
            addToast(`✓ ${src.length} clip(s) pegado(s)`, "success");
            await refreshClips();
            // Seleccionar los recién pegados para colocarlos como grupo
            if (newIds.length) {
              setSelectedClipIds(new Set(newIds));
              selectClip(newIds.length === 1 ? newIds[0] : null);
            }
            try { await control.call("snapshot"); } catch {}
          })();
        }
      } else if (e.ctrlKey || e.metaKey) {
        return; // no pisar atajos con Ctrl (undo/save los gestiona App)
      } else if (e.key === "?") {
        e.preventDefault();
        setShowHelp((s) => !s);
      } else if (e.key === "v" || e.key === "V") setTool("select");
      else if (e.key === "d" || e.key === "D" || e.key === "b" || e.key === "B") setTool("draw");
      else if (e.key === "c" || e.key === "C") setTool("cut");
      else if (e.key === "q" || e.key === "Q") setSnap((s) => !s);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedClipId, selectedClipIds, clips, clipboard, clipboardClips, selectClip, refreshClips]);

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
            <button className="btn sm ghost" onClick={() => setZoom((z) => Math.max(MIN_ZOOM, z - 1))} title="Zoom out (−)">−</button>
            <span className="mono" style={{ width: 34, textAlign: "center", fontSize: 11, color: "var(--txt-3)" }}>{Math.round(zoom * 10) / 10}×</span>
            <button className="btn sm ghost" onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z + 1))} title="Zoom in (+)">+</button>
            <button className="btn sm ghost" onClick={() => setZoom(DEFAULT_ZOOM)} title="Reset zoom (Ctrl+0)">↺</button>
          </div>
          <span className="duration-memory" title="Last effect duration ([/] to adjust ±50ms)">
            {(lastEffectDuration / 1000).toFixed(2)}s
          </span>
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
                {gridlines.map(({ t, kind }, i) => (
                  <div
                    key={`grid-${kind}-${i}`}
                    className={`gl gl-${kind}`}
                    style={{ left: t * zoom }}
                    title={`${kind.toUpperCase()} @ ${t.toFixed(2)}s`}
                  />
                ))}
              </div>
              {sections.map((s, i) => {
                const next = sections[i + 1]?.start ?? duration;
                return <div key={i} className="lane-sec" style={{ left: s.start * zoom, width: (next - s.start) * zoom, background: "color-mix(in oklab, var(--txt-3) 5%, transparent)" }} />;
              })}

              {lanes.map((lane) => {
                const h = lane.kind === "bar" ? rowHeight(lane.bar) : laneHeight(lane);
                const dim = lane.kind === "bar" && muted[lane.bar];
                const isDrop = lane.kind === "bar" && dropBar === lane.bar;
                return (
                  <div key={lane.key}
                    ref={(el) => { if (el) rowRefs.current.set(lane.key, el); else rowRefs.current.delete(lane.key); }}
                    className={"tl-row" + (isDrop ? " drop-target" : "")}
                    style={{ height: h, opacity: dim ? 0.4 : 1 }}
                    onMouseDown={(e) => onLaneMouseDown(e, lane)}
                    onContextMenu={(e) => openLaneMenu(e, lane)}>
                    {clipsForLane(lane).map((c) => {
                      const col = c.color || famColor(famName(c.effect_id));
                      return (
                        <div key={c.id}
                          data-clip-id={c.id}
                          data-track={c.track}
                          className={"clip" + (selectedClipId === c.id || selectedClipIds.has(c.id) ? " sel" : "") + (c.locked ? " locked" : "") + (tool === "draw" && (activeFx || activePreset) ? " clip-paintable" : "")}
                          onMouseDown={(e) => {
                            e.stopPropagation(); // evita que la lane cree un clip (draw) o Selecto rubber-band
                            if (tool !== "select" || c.locked) return;
                            // Si el clip ya está en una multi-selección, no la rompas (drag de grupo).
                            if (selectedClipIds.has(c.id) && selectedClipIds.size > 1) {
                              selectClip(c.id);
                              return;
                            }
                            selectClip(c.id);
                            setSelectedClipIds(new Set());
                            setMoveTargets([e.currentTarget as HTMLElement]);
                          }}
                          onClick={(e) => {
                            if (tool === "draw") { onClipClick(e, c); return; }
                            if (tool === "cut") {
                              e.stopPropagation();
                              const r = lanesRef.current!.getBoundingClientRect();
                              const ms = Math.round(((e.clientX - r.left) / zoom) * 1000);
                              if (ms > c.start_ms + 20 && ms < c.end_ms - 20) {
                                control.call("split_clip", { clip_id: c.id, t_ms: ms }).then(async () => {
                                  addToast("✂ Clip dividido", "success");
                                  await refreshClips();
                                  try { await control.call("snapshot"); } catch {}
                                });
                              }
                            }
                          }}
                          onContextMenu={(e) => openClipMenu(e, c)}
                          onDoubleClick={(e) => { e.stopPropagation(); selectClip(c.id); setInspector(true); }}
                          title={tool === "draw" ? "Click para pintar el efecto" : `${c.label || effectById.get(c.effect_id)?.name || "clip"} · ${((c.end_ms - c.start_ms) / 1000).toFixed(2)}s`}
                          style={{
                            left: (c.start_ms / 1000) * zoom, width: ((c.end_ms - c.start_ms) / 1000) * zoom - 2,
                            top: 7 + c.layer * LANE_H, height: LANE_H - 4,
                            background: `color-mix(in oklab, ${col} 32%, var(--bg-2))`, borderColor: col,
                            cursor: tool === "select" && !c.locked ? "grab" : "pointer",
                          }}>
                          <span className="clip-bar" style={{ background: col }} />
                          <span className="clip-name">{c.label || (c.preset_id ? "preset" : effectById.get(c.effect_id)?.name) || "clip"}</span>
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

              {/* Multi-selección por rubber-band (solo en modo select) */}
              {tool === "select" && (
                <Selecto
                  ref={selectoRef}
                  dragContainer={".tl-lanes"}
                  selectableTargets={[".clip"]}
                  hitRate={0}
                  selectByClick={true}
                  selectFromInside={false}
                  toggleContinueSelect={["ctrl"]}
                  ratio={0}
                  onDragStart={onSelectoDragStart}
                  onSelectEnd={onSelectoSelectEnd}
                />
              )}

              {/* Mover / redimensionar / arrastrar entre tracks (solo select) */}
              {tool === "select" && (
                <Moveable
                  ref={moveableRef}
                  target={moveTargets}
                  draggable={true}
                  resizable={true}
                  renderDirections={["w", "e"]}
                  origin={false}
                  keepRatio={false}
                  edge={false}
                  snappable={true}
                  snapDirections={{ left: true, right: true }}
                  elementSnapDirections={{ left: true, right: true }}
                  verticalGuidelines={verticalGuidelines}
                  snapThreshold={6}
                  throttleDrag={0}
                  onDrag={onClipDrag}
                  onDragEnd={onClipDragEnd}
                  onDragGroup={onClipDragGroup}
                  onDragGroupEnd={onClipDragGroupEnd}
                  onResize={onClipResize}
                  onResizeEnd={onClipResizeEnd}
                />
              )}
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
            <button className="x" onClick={() => setInspector(false)}>×</button>
          </div>
          <div className="ci-body">
            <ClipInspector
              clip={selClip}
              effects={effects}
              lastDuration={lastEffectDuration}
              onDurationChange={setLastEffectDuration}
              onClipUpdate={afterEdit}
            />
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

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {showHelp && <HelpOverlay onClose={() => setShowHelp(false)} />}
    </div>
  );
}

// color CSS var → hex aproximado para guardar en el clip (el backend espera #hex).
// Como los colores se derivan de la familia en render, basta un hex neutro.
function cssColorToHex(_v: string): string {
  return "#3a7acc";
}
