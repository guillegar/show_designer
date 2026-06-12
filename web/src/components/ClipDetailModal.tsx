/**
 * ClipDetailModal — Editor de detalle del clip (ROADMAP v2, Fase A4).
 *
 * Se abre con Alt+doble clic sobre un clip en el Timeline.
 * Tres zonas:
 *   A. Beat grid + micro-eventos (SVG con diamantes arrastrables)
 *   B. Curvas de automatización (lanes del clip, editables — deferred de A2)
 *   C. Inspector del micro-evento seleccionado (params_override + duration_ms)
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { control } from "../api/control";
import { useStore, Clip, EffectInfo } from "../store";
import type { AutomationLane, AutomationPoint, MicroEvent } from "../api/types";

// ── Constantes de layout del modal ───────────────────────────────────────────
const MODAL_PAD = 32;        // px de margen horizontal del inner content
const BEAT_ROW_H = 48;       // altura de la fila de micro-eventos
const AUTO_ROW_H = 72;       // altura de cada lane de automatización
const RULER_H = 20;          // altura de la regla de beats
const DIAMOND_R = 7;         // radio del diamante (medio lado del cuadrado rotado)

// ── Helpers ───────────────────────────────────────────────────────────────────

function beatMs(bpm: number): number {
  return 60000 / bpm;
}

/** Genera las posiciones de beat dentro del clip para la regla. */
function buildBeatGrid(clipStartMs: number, clipEndMs: number, bpm: number) {
  const bMs = beatMs(bpm);
  const beats: { t_ms_abs: number; t_ms_rel: number; isBeat1: boolean }[] = [];
  // Primer beat DESPUÉS o en clipStart
  const firstBeat = Math.ceil(clipStartMs / bMs) * bMs;
  for (let t = firstBeat; t < clipEndMs; t += bMs) {
    beats.push({
      t_ms_abs: t,
      t_ms_rel: t - clipStartMs,
      isBeat1: Math.round(t / bMs) % 4 === 0,
    });
  }
  return beats;
}

/** Snappea t_ms_rel al beat más cercano dentro del clip. */
function snapToBeat(t_ms_rel: number, clipDurMs: number, bpm: number): number {
  const bMs = beatMs(bpm);
  const snapped = Math.round(t_ms_rel / bMs) * bMs;
  return Math.max(0, Math.min(clipDurMs - 1, snapped));
}

/** Convierte un t_ms_rel a posición X en el SVG del modal. */
function tToX(t_ms_rel: number, clipDurMs: number, svgW: number): number {
  if (clipDurMs <= 0) return 0;
  return (t_ms_rel / clipDurMs) * svgW;
}

/** Convierte una posición X del SVG a t_ms_rel. */
function xToT(x: number, clipDurMs: number, svgW: number): number {
  if (svgW <= 0) return 0;
  return Math.max(0, Math.min(clipDurMs - 1, (x / svgW) * clipDurMs));
}

// ── Subcomponentes ─────────────────────────────────────────────────────────────

interface BeatRulerProps {
  clipStartMs: number;
  clipEndMs: number;
  bpm: number;
  svgW: number;
}

function BeatRuler({ clipStartMs, clipEndMs, bpm, svgW }: BeatRulerProps) {
  const clipDurMs = clipEndMs - clipStartMs;
  const beats = buildBeatGrid(clipStartMs, clipEndMs, bpm);
  return (
    <svg width={svgW} height={RULER_H} style={{ display: "block", flexShrink: 0 }}>
      {beats.map((b) => {
        const x = tToX(b.t_ms_rel, clipDurMs, svgW);
        return (
          <g key={b.t_ms_abs}>
            <line x1={x} y1={b.isBeat1 ? 0 : RULER_H * 0.4} x2={x} y2={RULER_H}
              stroke={b.isBeat1 ? "var(--acc)" : "var(--txt-4)"} strokeWidth={b.isBeat1 ? 1.5 : 1} />
            {b.isBeat1 && (
              <text x={x + 3} y={RULER_H - 4} fill="var(--txt-3)" fontSize={9}
                fontFamily="var(--mono)">
                {Math.round(b.t_ms_abs / beatMs(bpm))}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

interface MicroEventsRowProps {
  events: MicroEvent[];
  clip: Clip;
  bpm: number;
  snapOn: boolean;
  svgW: number;
  selectedEvUid: string | null;
  onSelect: (uid: string | null) => void;
  onAdd: (t_ms_rel: number) => void;
  onMove: (uid: string, t_ms_rel: number) => void;
  onDelete: (uid: string) => void;
}

function MicroEventsRow({
  events, clip, bpm, snapOn, svgW,
  selectedEvUid, onSelect, onAdd, onMove, onDelete,
}: MicroEventsRowProps) {
  const clipDurMs = clip.end_ms - clip.start_ms;
  const draggingRef = useRef<{ uid: string; startX: number; startT: number } | null>(null);

  const handleSvgMouseDown = (e: React.MouseEvent<SVGSVGElement>) => {
    if ((e.target as Element).closest(".ev-diamond")) return;
    const svgRect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
    let t = xToT(e.clientX - svgRect.left, clipDurMs, svgW);
    if (snapOn) t = snapToBeat(t, clipDurMs, bpm);
    onAdd(t);
  };

  const handleDiamondMouseDown = (e: React.MouseEvent, ev: MicroEvent) => {
    e.stopPropagation();
    onSelect(ev.uid);
    const svgRect = (e.currentTarget.closest("svg") as SVGSVGElement).getBoundingClientRect();
    draggingRef.current = {
      uid: ev.uid,
      startX: e.clientX - svgRect.left,
      startT: ev.t_ms_rel,
    };

    const onMouseMove = (me: MouseEvent) => {
      if (!draggingRef.current) return;
      const dx = me.clientX - (svgRect.left + draggingRef.current.startX) + tToX(draggingRef.current.startT, clipDurMs, svgW);
      let newT = xToT(dx, clipDurMs, svgW);
      if (snapOn) newT = snapToBeat(newT, clipDurMs, bpm);
      onMove(draggingRef.current.uid, newT);
    };
    const onMouseUp = () => {
      draggingRef.current = null;
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  };

  return (
    <svg width={svgW} height={BEAT_ROW_H} style={{ display: "block", cursor: "crosshair" }}
      onMouseDown={handleSvgMouseDown}>
      {/* fondo */}
      <rect width={svgW} height={BEAT_ROW_H} fill="var(--bg-inset)" rx={4} />
      {/* línea central */}
      <line x1={0} y1={BEAT_ROW_H / 2} x2={svgW} y2={BEAT_ROW_H / 2}
        stroke="var(--bg-3)" strokeWidth={1} />
      {/* diamantes */}
      {events.map((ev) => {
        const cx = tToX(ev.t_ms_rel, clipDurMs, svgW);
        const cy = BEAT_ROW_H / 2;
        const selected = ev.uid === selectedEvUid;
        const points = [
          `${cx},${cy - DIAMOND_R}`, `${cx + DIAMOND_R},${cy}`,
          `${cx},${cy + DIAMOND_R}`, `${cx - DIAMOND_R},${cy}`,
        ].join(" ");
        return (
          <g key={ev.uid} className="ev-diamond"
            onMouseDown={(e) => handleDiamondMouseDown(e, ev)}
            onDoubleClick={(e) => { e.stopPropagation(); onDelete(ev.uid); }}
            style={{ cursor: "grab" }}>
            <polygon points={points}
              fill={selected ? "var(--acc)" : "var(--acc-2)"}
              stroke={selected ? "var(--txt-1)" : "var(--acc-2)"}
              strokeWidth={selected ? 1.5 : 1}
              opacity={0.9} />
          </g>
        );
      })}
    </svg>
  );
}

interface AutomationLaneRowProps {
  lane: AutomationLane;
  clip: Clip;
  svgW: number;
  onUpdate: (lane: AutomationLane) => void;
}

function AutomationLaneRow({ lane, clip, svgW, onUpdate }: AutomationLaneRowProps) {
  const clipDurMs = clip.end_ms - clip.start_ms;
  const param = lane.target.split(":")[2] ?? lane.target;

  // Convierte puntos a coordenadas SVG
  const ptToXY = (pt: AutomationPoint) => ({
    x: tToX(pt.t_ms - clip.start_ms, clipDurMs, svgW),
    y: AUTO_ROW_H - 4 - (pt.value * (AUTO_ROW_H - 8)),
  });

  const polylinePoints = lane.points.map(ptToXY)
    .map(({ x, y }) => `${x},${y}`).join(" ");

  const draggingPt = useRef<{ idx: number; origPts: AutomationPoint[] } | null>(null);

  const handlePtMouseDown = (e: React.MouseEvent, idx: number) => {
    e.stopPropagation();
    draggingPt.current = { idx, origPts: lane.points };
    const svgRect = (e.currentTarget.closest("svg") as SVGSVGElement).getBoundingClientRect();

    const onMove = (me: MouseEvent) => {
      if (!draggingPt.current) return;
      const rawX = me.clientX - svgRect.left;
      const rawY = me.clientY - svgRect.top;
      const newTRel = xToT(rawX, clipDurMs, svgW);
      const newVal = Math.max(0, Math.min(1, 1 - (rawY - 4) / (AUTO_ROW_H - 8)));
      const pts = draggingPt.current.origPts.map((p, i) =>
        i === draggingPt.current!.idx
          ? { ...p, t_ms: clip.start_ms + newTRel, value: newVal }
          : p
      ).sort((a, b) => a.t_ms - b.t_ms);
      onUpdate({ ...lane, points: pts });
    };
    const onUp = () => {
      draggingPt.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const handleSvgClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if ((e.target as Element).closest(".auto-pt")) return;
    const svgRect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
    const tRel = xToT(e.clientX - svgRect.left, clipDurMs, svgW);
    const val = Math.max(0, Math.min(1, 1 - (e.clientY - svgRect.top - 4) / (AUTO_ROW_H - 8)));
    const newPt: AutomationPoint = { t_ms: clip.start_ms + tRel, value: val, shape: "linear" };
    const pts = [...lane.points, newPt].sort((a, b) => a.t_ms - b.t_ms);
    onUpdate({ ...lane, points: pts });
  };

  const handlePtDblClick = (e: React.MouseEvent, idx: number) => {
    e.stopPropagation();
    const pts = lane.points.filter((_, i) => i !== idx);
    onUpdate({ ...lane, points: pts });
  };

  const cycleShape = (e: React.MouseEvent, idx: number) => {
    e.preventDefault();
    const shapes: AutomationPoint["shape"][] = ["linear", "hold", "smooth"];
    const cur = lane.points[idx].shape ?? "linear";
    const next = shapes[(shapes.indexOf(cur) + 1) % shapes.length];
    const pts = lane.points.map((p, i) => i === idx ? { ...p, shape: next } : p);
    onUpdate({ ...lane, points: pts });
  };

  const shapeColor = (shape: AutomationPoint["shape"]) =>
    shape === "hold" ? "var(--warn)" : shape === "smooth" ? "var(--acc)" : "var(--txt-3)";

  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ fontSize: 10, color: "var(--txt-3)", fontFamily: "var(--mono)", marginBottom: 2 }}>
        {param}
        {!lane.enabled && <span style={{ color: "var(--txt-4)", marginLeft: 6 }}>(desactivada)</span>}
      </div>
      <svg width={svgW} height={AUTO_ROW_H} style={{ display: "block", cursor: "crosshair" }}
        onClick={handleSvgClick}>
        <rect width={svgW} height={AUTO_ROW_H} fill="var(--bg-inset)" rx={3} />
        {/* Grid lines 25/50/75% */}
        {[0.25, 0.5, 0.75].map((v) => (
          <line key={v} x1={0} x2={svgW}
            y1={AUTO_ROW_H - 4 - v * (AUTO_ROW_H - 8)}
            y2={AUTO_ROW_H - 4 - v * (AUTO_ROW_H - 8)}
            stroke="var(--bg-3)" strokeWidth={1} strokeDasharray="3,3" />
        ))}
        {lane.points.length > 1 && (
          <polyline points={polylinePoints}
            fill="none" stroke="var(--acc-2)" strokeWidth={1.5} opacity={0.8} />
        )}
        {lane.points.map((pt, idx) => {
          const { x, y } = ptToXY(pt);
          return (
            <circle key={idx} className="auto-pt" cx={x} cy={y} r={5}
              fill={shapeColor(pt.shape)}
              stroke="var(--txt-1)" strokeWidth={1}
              style={{ cursor: "grab" }}
              onMouseDown={(e) => handlePtMouseDown(e, idx)}
              onDoubleClick={(e) => handlePtDblClick(e, idx)}
              onContextMenu={(e) => cycleShape(e, idx)} />
          );
        })}
      </svg>
    </div>
  );
}

// ── Componente principal ───────────────────────────────────────────────────────

interface ClipDetailModalProps {
  clip: Clip;
  effects: EffectInfo[];
  onClose: () => void;
  onClipUpdate: () => void;
}

export function ClipDetailModal({ clip, effects, onClose, onClipUpdate }: ClipDetailModalProps) {
  const bpm = useStore((s) => s.song.bpm) || 120;
  const snapEnabled = true; // TODO: leer del estado global si se añade en A5

  const [events, setEvents] = useState<MicroEvent[]>(
    (clip.events ?? []).map((e: Record<string, unknown>) => e as unknown as MicroEvent)
  );
  const [lanes, setLanes] = useState<AutomationLane[]>([]);
  const [selectedEvUid, setSelectedEvUid] = useState<string | null>(null);
  const svgContainerRef = useRef<HTMLDivElement>(null);
  const [svgW, setSvgW] = useState(800);

  // Medir el ancho disponible para los SVGs
  useEffect(() => {
    const measure = () => {
      if (svgContainerRef.current) {
        setSvgW(svgContainerRef.current.clientWidth - 2);
      }
    };
    measure();
    const obs = new ResizeObserver(measure);
    if (svgContainerRef.current) obs.observe(svgContainerRef.current);
    return () => obs.disconnect();
  }, []);

  // Cargar lanes de automatización para este clip
  useEffect(() => {
    control.call("list_automation_lanes").then((r: { lanes?: AutomationLane[] }) => {
      const clipLanes = (r.lanes ?? []).filter((l: AutomationLane) =>
        l.target.startsWith(`clip:${clip.id}:`) || l.target.startsWith(`clip:${clip.uid}:`)
      );
      setLanes(clipLanes);
    }).catch(() => {});
  }, [clip.id, clip.uid]);

  // Sync events when clip changes (after refreshClips)
  useEffect(() => {
    setEvents((clip.events ?? []).map((e: Record<string, unknown>) => e as unknown as MicroEvent));
  }, [clip.events]);

  const effect = effects.find((e) => e.id === clip.effect_id);
  const clipDurMs = clip.end_ms - clip.start_ms;
  const selectedEv = events.find((e) => e.uid === selectedEvUid) ?? null;

  // ── Handlers de micro-eventos ──────────────────────────────────────────────

  const handleAddEvent = useCallback(async (t_ms_rel: number) => {
    const r = await control.call("add_micro_event", {
      clip_id: clip.id,
      t_ms_rel: Math.round(t_ms_rel),
      duration_ms: 100,
      params_override: {},
    });
    if (r.ok) {
      setEvents((r.clip.events ?? []) as MicroEvent[]);
      onClipUpdate();
    }
  }, [clip.id, onClipUpdate]);

  const handleMoveEvent = useCallback(async (uid: string, t_ms_rel: number) => {
    // Update optimista local
    setEvents((prev) => prev.map((e) => e.uid === uid ? { ...e, t_ms_rel: Math.round(t_ms_rel) } : e));
    const r = await control.call("update_micro_event", {
      clip_id: clip.id,
      event_uid: uid,
      t_ms_rel: Math.round(t_ms_rel),
    });
    if (r.ok) {
      setEvents((r.clip.events ?? []) as MicroEvent[]);
      onClipUpdate();
    }
  }, [clip.id, onClipUpdate]);

  const handleDeleteEvent = useCallback(async (uid: string) => {
    const r = await control.call("delete_micro_event", { clip_id: clip.id, event_uid: uid });
    if (r.ok) {
      setEvents((r.clip.events ?? []) as MicroEvent[]);
      if (selectedEvUid === uid) setSelectedEvUid(null);
      onClipUpdate();
    }
  }, [clip.id, selectedEvUid, onClipUpdate]);

  // ── Handlers de automatización ─────────────────────────────────────────────

  const handleLaneUpdate = useCallback(async (updatedLane: AutomationLane) => {
    // Update optimista
    setLanes((prev) => prev.map((l) => l.uid === updatedLane.uid ? updatedLane : l));
    await control.call("set_automation_points", {
      uid: updatedLane.uid,
      points: updatedLane.points,
    });
  }, []);

  // ── Edición del evento seleccionado ───────────────────────────────────────

  const handleEvParamChange = useCallback(async (paramKey: string, value: string) => {
    if (!selectedEv) return;
    const parsed = parseFloat(value);
    const newOverride = isNaN(parsed)
      ? (() => { const o = { ...selectedEv.params_override }; delete o[paramKey]; return o; })()
      : { ...selectedEv.params_override, [paramKey]: parsed };
    const r = await control.call("update_micro_event", {
      clip_id: clip.id,
      event_uid: selectedEv.uid,
      params_override: newOverride,
    });
    if (r.ok) {
      setEvents((r.clip.events ?? []) as MicroEvent[]);
      onClipUpdate();
    }
  }, [clip.id, selectedEv, onClipUpdate]);

  const handleEvDurationChange = useCallback(async (value: string) => {
    if (!selectedEv) return;
    const parsed = parseInt(value, 10);
    if (isNaN(parsed) || parsed < 1) return;
    const r = await control.call("update_micro_event", {
      clip_id: clip.id,
      event_uid: selectedEv.uid,
      duration_ms: parsed,
    });
    if (r.ok) {
      setEvents((r.clip.events ?? []) as MicroEvent[]);
      onClipUpdate();
    }
  }, [clip.id, selectedEv, onClipUpdate]);

  const handleAddLane = useCallback(async (param: string) => {
    const r = await control.call("add_automation_lane", {
      target: `clip:${clip.uid}:${param}`,
    });
    if (r.ok) {
      setLanes((prev) => [...prev, r.lane as AutomationLane]);
    }
  }, [clip.uid]);

  const effectParams = Object.keys(clip.params ?? {});

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="clip-detail-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="clip-detail-modal">
        {/* Header */}
        <div className="cdm-header">
          <div className="cdm-title">
            <span className="cdm-clip-bar" style={{ background: clip.color ?? "var(--acc-2)" }} />
            <strong>{clip.label || effect?.name || "Clip"}</strong>
            <span className="cdm-meta">{effect?.name} · {(clipDurMs / 1000).toFixed(2)}s</span>
          </div>
          <button className="x" onClick={onClose} title="Cerrar (Esc)">×</button>
        </div>

        {/* Content */}
        <div className="cdm-body">
          <div ref={svgContainerRef} className="cdm-svg-col">

            {/* Zona A: Beat grid + micro-eventos */}
            <div className="cdm-section-label">
              Micro-eventos
              <span className="cdm-hint">Clic = añadir · Arrastrar = mover · Doble clic = borrar</span>
            </div>
            <BeatRuler clipStartMs={clip.start_ms} clipEndMs={clip.end_ms} bpm={bpm} svgW={svgW} />
            <div style={{ marginTop: 4 }}>
              <MicroEventsRow
                events={events}
                clip={clip}
                bpm={bpm}
                snapOn={snapEnabled}
                svgW={svgW}
                selectedEvUid={selectedEvUid}
                onSelect={setSelectedEvUid}
                onAdd={handleAddEvent}
                onMove={handleMoveEvent}
                onDelete={handleDeleteEvent}
              />
            </div>

            {/* Zona B: Curvas de automatización */}
            {(lanes.length > 0 || effectParams.length > 0) && (
              <>
                <div className="cdm-section-label" style={{ marginTop: 16 }}>
                  Automatización
                  <span className="cdm-hint">Clic = punto · Arrastrar = mover · Doble clic = borrar · Clic derecho = ciclar forma</span>
                </div>
                {lanes.map((lane) => (
                  <AutomationLaneRow
                    key={lane.uid}
                    lane={lane}
                    clip={clip}
                    svgW={svgW}
                    onUpdate={handleLaneUpdate}
                  />
                ))}
                {effectParams.length > 0 && (
                  <div className="cdm-add-lane">
                    <span style={{ color: "var(--txt-3)", fontSize: 11, marginRight: 8 }}>
                      + Automatizar:
                    </span>
                    {effectParams.map((p) => {
                      const already = lanes.some((l) => l.target.endsWith(`:${p}`));
                      return (
                        <button key={p} className="cdm-lane-btn"
                          disabled={already}
                          onClick={() => handleAddLane(p)}
                          title={already ? "Ya existe una lane para este parámetro" : ""}>
                          {p}
                        </button>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </div>

          {/* Zona C: Inspector del evento seleccionado */}
          {selectedEv && (
            <div className="cdm-ev-inspector">
              <div className="cdm-section-label">Evento seleccionado</div>
              <div className="cdm-ev-row">
                <label>t (ms desde inicio)</label>
                <input type="number" value={selectedEv.t_ms_rel} min={0} max={clipDurMs - 1}
                  onChange={(e) => handleMoveEvent(selectedEv.uid, parseInt(e.target.value, 10) || 0)} />
              </div>
              <div className="cdm-ev-row">
                <label>Duración ventana (ms)</label>
                <input type="number" value={selectedEv.duration_ms} min={1} max={10000}
                  onChange={(e) => handleEvDurationChange(e.target.value)} />
              </div>
              {effectParams.length > 0 && (
                <>
                  <div className="cdm-section-label" style={{ marginTop: 12 }}>
                    Params override
                    <span className="cdm-hint">Vacío = heredar del clip</span>
                  </div>
                  {effectParams.map((p) => (
                    <div key={p} className="cdm-ev-row">
                      <label>{p}</label>
                      <input
                        type="text"
                        placeholder={(clip.params?.[p] ?? "—").toString()}
                        value={selectedEv.params_override[p] !== undefined
                          ? String(selectedEv.params_override[p])
                          : ""}
                        onChange={(e) => handleEvParamChange(p, e.target.value)}
                      />
                    </div>
                  ))}
                </>
              )}
              <button className="cdm-delete-btn"
                onClick={() => handleDeleteEvent(selectedEv.uid)}>
                Borrar evento
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
