import { useEffect, useRef, useState } from "react";
import { control } from "../api/control";
import { stream, LEDS, DmxState } from "../api/stream";
import type { BlackoutChangedEvent } from "../api/stream";
import { useStore, Fixture } from "../store";

// ── Editor de fixture (ROADMAP v4) ──────────────────────────────────────────
type FixtureDetail = {
  fixture_id: string; label: string; profile_id: string;
  universe: number; dmx_start: number; num_channels: number;
  artnet_ip?: string | null; patch_x?: number | null; patch_y?: number | null;
  height_m?: number | null; notes?: string | null;
  channel_map?: Array<{ch: number; role: string}> | null;
  kind_override?: string | null; legacy_bar_idx?: number | null; target_ip?: string | null;
  rotation?: number[] | null;
};
type FixtureType = { id: string; name: string; modes: Array<{name: string; channels: number}> };
type ConflictInfo = { fixture_id: string; name: string; address_range: string };
type OutputTarget = { type: string; ip?: string; port?: string };

function barAvg(barIdx: number): [number, number, number] {
  let r = 0, g = 0, b = 0;
  for (let i = 0; i < LEDS; i++) { const c = stream.ledRGB(barIdx, i); r += c[0]; g += c[1]; b += c[2]; }
  return [Math.round(r / LEDS), Math.round(g / LEDS), Math.round(b / LEDS)];
}
function fixtureColor(f: Fixture): [number, number, number] {
  if (f.legacy_bar_idx != null) return barAvg(f.legacy_bar_idx);
  const d = stream.latestDmx[f.fixture_id];
  if (d) return [Math.round((d.r ?? 0) * 255), Math.round((d.g ?? 0) * 255), Math.round((d.b ?? 0) * 255)];
  return [40, 44, 52];
}
function useLayout(fixtures: Fixture[]) {
  const xs = fixtures.map((f) => f.position?.[0] ?? 0);
  const zs = fixtures.map((f) => f.position?.[2] ?? f.position?.[1] ?? 0);
  const minX = Math.min(-1, ...xs), maxX = Math.max(1, ...xs);
  const minZ = Math.min(-1, ...zs), maxZ = Math.max(1, ...zs);
  const nx = (x: number) => (maxX === minX ? 0.5 : (x - minX) / (maxX - minX));
  const nz = (z: number) => (maxZ === minZ ? 0.3 : (z - minZ) / (maxZ - minZ));
  return { nx, nz, minX, maxX, minZ, maxZ };
}

// ── P2 — Context menu ────────────────────────────────────────────────────────

type CtxMenuState = { x: number; y: number; fixtureId: string } | null;

function CtxMenuItem({ label, danger, onClick }: {
  label: string; danger?: boolean; onClick: () => void;
}) {
  return (
    <button style={{ display: "block", width: "100%", textAlign: "left", border: "none",
      padding: "6px 14px", fontSize: 12, cursor: "pointer", background: "transparent",
      color: danger ? "var(--bad)" : "var(--txt-1)" }} onMouseDown={onClick}>
      {label}
    </button>
  );
}

function CtxMenu({ menu, onClose, onAction }: {
  menu: CtxMenuState; onClose: () => void;
  onAction: (action: string, id: string) => void;
}) {
  if (!menu) return null;
  const id = menu.fixtureId;
  const act = (a: string) => { onAction(a, id); onClose(); };
  return (
    <div style={{ position: "fixed", left: menu.x, top: menu.y, zIndex: 200,
      background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 6,
      boxShadow: "0 4px 16px rgba(0,0,0,0.5)", minWidth: 140, padding: "4px 0" }}
      onMouseLeave={onClose}>
      <CtxMenuItem label="Editar" onClick={() => act("edit")} />
      <CtxMenuItem label="Duplicar" onClick={() => act("duplicate")} />
      <CtxMenuItem label="Identify 2s" onClick={() => act("identify")} />
      <div style={{ height: 1, background: "var(--line)", margin: "3px 0" }} />
      <CtxMenuItem label="Borrar" danger onClick={() => act("delete")} />
    </div>
  );
}

// ── P2 — PatchStage con zoom, pan, multi-select, rubber-band, menú contextual ─

function PatchStage({ fixtures, onSelect, dirtyFixtureId, multiSel, onMultiSelToggle, onCtxAction, zoom, setZoom, panX, setPanX, panY, setPanY, fitRef }: {
  fixtures: Fixture[];
  onSelect: (id: string) => void;
  dirtyFixtureId?: string | null;
  multiSel: Set<string>;
  onMultiSelToggle: (id: string) => void;
  onCtxAction: (action: string, id: string) => void;
  zoom: number;
  setZoom: (z: number) => void;
  panX: number;
  setPanX: (x: number) => void;
  panY: number;
  setPanY: (y: number) => void;
  fitRef?: React.MutableRefObject<(() => void) | null>;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const sel = useStore((s) => s.selectedFixtureId);
  const refreshFixtures = useStore((s) => s.refreshFixtures);
  const L = useLayout(fixtures);
  const { nx, nz } = L;

  const [patchOverride, setPatchOverride] = useState<Record<string, [number, number]>>({});
  const [ctxMenu, setCtxMenu] = useState<CtxMenuState>(null);
  const [rubber, setRubber] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);

  // Stale-closure refs for global handlers (avoid re-registering on every render)
  const zoomRef = useRef(1);
  const panRef = useRef({ x: 0, y: 0 });
  const dragRef = useRef<{ id: string; moved: boolean } | null>(null);
  const panDragRef = useRef<{ ox: number; oy: number; sx: number; sy: number } | null>(null);
  const rubberStartRef = useRef<{ x1: number; y1: number } | null>(null);
  const fixturesRef = useRef(fixtures);
  fixturesRef.current = fixtures;
  const poRef = useRef(patchOverride);
  poRef.current = patchOverride;
  const mSelRef = useRef(multiSel);
  mSelRef.current = multiSel;
  const onTogRef = useRef(onMultiSelToggle);
  onTogRef.current = onMultiSelToggle;
  const refreshRef = useRef(refreshFixtures);
  refreshRef.current = refreshFixtures;
  zoomRef.current = zoom;
  panRef.current = { x: panX, y: panY };

  const pxOf = (f: Fixture): [number, number] => {
    const po = patchOverride[f.fixture_id];
    if (po) return po;
    if (f.patch_x != null) return [f.patch_x, f.patch_y ?? 0.5];
    return [nx(f.position?.[0] ?? 0), nz(f.position?.[2] ?? f.position?.[1] ?? 0)];
  };
  const pxOfRef = useRef(pxOf);
  pxOfRef.current = pxOf;

  // Convert client coords to canvas-space coords (accounting for zoom+pan)
  const toCanvas = (clientX: number, clientY: number) => {
    const cr = containerRef.current?.getBoundingClientRect();
    if (!cr) return { cx: 0, cy: 0 };
    const z = zoomRef.current, p = panRef.current;
    return { cx: (clientX - cr.left - p.x) / z, cy: (clientY - cr.top - p.y) / z };
  };

  // Find nearest fixture within 34px in canvas space
  const nearestFix = (cx: number, cy: number) => {
    const cv = canvasRef.current;
    if (!cv) return null;
    const m = 60, w = cv.clientWidth, h = cv.clientHeight;
    let best: Fixture | null = null, bd = 1e9;
    for (const f of fixturesRef.current) {
      const [fpx, fpy] = pxOfRef.current(f);
      const fcx = m + fpx * (w - 2 * m);
      const fcy = m + fpy * (h - 2 * m);
      const d = Math.hypot(cx - fcx, cy - fcy);
      if (d < bd && d < 34) { bd = d; best = f; }
    }
    return best;
  };

  // Canvas draw loop (rAF)
  useEffect(() => {
    let raf = 0;
    const m = 60;
    const roundRect = (c: CanvasRenderingContext2D, x: number, y: number, ww: number, hh: number, r: number) => {
      c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + ww, y, x + ww, y + hh, r);
      c.arcTo(x + ww, y + hh, x, y + hh, r); c.arcTo(x, y + hh, x, y, r); c.arcTo(x, y, x + ww, y, r); c.closePath();
    };
    const draw = () => {
      const cv = canvasRef.current;
      if (cv) {
        const dpr = Math.min(2, window.devicePixelRatio || 1);
        const w = cv.clientWidth, h = cv.clientHeight;
        if (cv.width !== w * dpr) { cv.width = w * dpr; cv.height = h * dpr; }
        const ctx = cv.getContext("2d")!;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);
        const step = 42;
        ctx.strokeStyle = "rgba(120,130,160,0.06)"; ctx.lineWidth = 1;
        for (let gx = 0; gx < w; gx += step) { ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, h); ctx.stroke(); }
        for (let gy = 0; gy < h; gy += step) { ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(w, gy); ctx.stroke(); }
        ctx.strokeStyle = "rgba(110,120,160,0.35)"; ctx.lineWidth = 1.5;
        ctx.setLineDash([6, 5]); ctx.strokeRect(m, m, w - 2 * m, h - 2 * m); ctx.setLineDash([]);
        ctx.fillStyle = "rgba(150,160,190,0.4)"; ctx.font = "11px 'JetBrains Mono'";
        ctx.fillText("ESCENARIO", m + 8, m + 18);
        ctx.fillText("◇ PÚBLICO", w / 2 - 30, h - m + 24);
        for (const f of fixtures) {
          const [fpx, fpy] = pxOf(f);
          const cx = m + fpx * (w - 2 * m);
          const cy = m + fpy * (h - 2 * m);
          const [r, g, b] = fixtureColor(f);
          const isSel = sel === f.fixture_id;
          const isMulti = multiSel.has(f.fixture_id);
          const kind = f.kind_override || f.kind || "led_strip";

          ctx.save(); ctx.translate(cx, cy); ctx.rotate(((f.rotation?.[1] ?? 0) * Math.PI) / 180);
          const grd = ctx.createRadialGradient(0, 0, 2, 0, 0, 46);
          grd.addColorStop(0, `rgba(${r},${g},${b},0.5)`); grd.addColorStop(1, `rgba(${r},${g},${b},0)`);
          ctx.fillStyle = grd; ctx.beginPath(); ctx.arc(0, 0, 46, 0, 7); ctx.fill();

          ctx.fillStyle = "#0a0c10";
          ctx.strokeStyle = isSel ? "#a070ff" : isMulti ? "#50c0ff" : "rgba(150,160,190,0.5)";
          ctx.lineWidth = (isSel || isMulti) ? 2.5 : 1.2;

          // D1: Shape por tipo
          if (kind === "moving_head") {
            ctx.beginPath(); ctx.arc(0, 0, 12, 0, 7); ctx.fill(); ctx.stroke();
            ctx.strokeStyle = `rgb(${r},${g},${b})`; ctx.beginPath(); ctx.moveTo(-8, 0); ctx.lineTo(8, 0);
            ctx.moveTo(0, -8); ctx.lineTo(0, 8); ctx.stroke();
          } else if (kind === "rgb_par" || kind === "dimmer") {
            ctx.beginPath(); ctx.arc(0, 0, 10, 0, 7); ctx.fill(); ctx.stroke();
          } else {
            const bw = 10, bh = 46;
            roundRect(ctx, -bw / 2, -bh / 2, bw, bh, 3); ctx.fill(); ctx.stroke();
            ctx.fillStyle = `rgb(${r},${g},${b})`; roundRect(ctx, -bw / 2 + 2.5, -bh / 2 + 3, bw - 5, bh - 6, 2); ctx.fill();
          }
          ctx.restore();
          ctx.fillStyle = isSel ? "#c9a8ff" : isMulti ? "#80d0ff" : "rgba(170,180,200,0.7)";
          ctx.font = "600 10px 'Hanken Grotesk'"; ctx.textAlign = "center";
          const lbl = (dirtyFixtureId === f.fixture_id ? "● " : "") + (f.label || f.fixture_id);
          ctx.fillText(lbl, cx, cy + 35);
        }
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [fixtures, sel, nx, nz, patchOverride, multiSel, dirtyFixtureId]);

  // Global mousemove/mouseup: fixture drag, pan drag, rubber-band
  useEffect(() => {
    const move = (e: MouseEvent) => {
      const d = dragRef.current;
      if (d) {
        const cv = canvasRef.current;
        const cr = containerRef.current?.getBoundingClientRect();
        if (!cv || !cr) return;
        const z = zoomRef.current, p = panRef.current;
        const m = 60, w = cv.clientWidth, h = cv.clientHeight;
        const cx = (e.clientX - cr.left - p.x) / z;
        const cy = (e.clientY - cr.top - p.y) / z;
        const px = Math.max(0, Math.min(1, (cx - m) / (w - 2 * m)));
        const py = Math.max(0, Math.min(1, (cy - m) / (h - 2 * m)));
        d.moved = true;
        setPatchOverride((o) => { const n = Object.assign({}, o); n[d.id] = [px, py]; return n; });
        return;
      }
      const pd = panDragRef.current;
      if (pd) {
        const nx2 = pd.ox + (e.clientX - pd.sx);
        const ny2 = pd.oy + (e.clientY - pd.sy);
        panRef.current = { x: nx2, y: ny2 };
        setPanX(nx2); setPanY(ny2);
        return;
      }
      const rb = rubberStartRef.current;
      if (rb) {
        const cr = containerRef.current?.getBoundingClientRect();
        if (!cr) return;
        const z = zoomRef.current, p = panRef.current;
        const x2 = (e.clientX - cr.left - p.x) / z;
        const y2 = (e.clientY - cr.top - p.y) / z;
        setRubber({ x1: rb.x1, y1: rb.y1, x2, y2 });
      }
    };
    const up = (e: MouseEvent) => {
      const d = dragRef.current;
      if (d) {
        dragRef.current = null;
        if (d.moved) {
          const po = poRef.current[d.id];
          if (po) {
            control.call("move_fixture", { fixture_id: d.id, x: po[0], y: po[1] })
              .then(() => {
                refreshRef.current();
                setPatchOverride((o) => { const n = Object.assign({}, o); delete n[d.id]; return n; });
              }).catch(() => {});
          }
        }
        return;
      }
      if (panDragRef.current) { panDragRef.current = null; return; }
      const rb = rubberStartRef.current;
      if (rb) {
        rubberStartRef.current = null;
        setRubber(null);
        const cv = canvasRef.current;
        const cr = containerRef.current?.getBoundingClientRect();
        if (!cv || !cr) return;
        const z = zoomRef.current, p = panRef.current;
        const m = 60, w = cv.clientWidth, h = cv.clientHeight;
        const x2 = (e.clientX - cr.left - p.x) / z;
        const y2 = (e.clientY - cr.top - p.y) / z;
        const rMinX = Math.min(rb.x1, x2), rMaxX = Math.max(rb.x1, x2);
        const rMinY = Math.min(rb.y1, y2), rMaxY = Math.max(rb.y1, y2);
        for (const f of fixturesRef.current) {
          const [fpx, fpy] = pxOfRef.current(f);
          const fcx = m + fpx * (w - 2 * m);
          const fcy = m + fpy * (h - 2 * m);
          if (fcx >= rMinX && fcx <= rMaxX && fcy >= rMinY && fcy <= rMaxY) {
            onTogRef.current(f.fixture_id);
          }
        }
      }
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
  }, []);

  // D2 — Fit-to-view: bbox de los fixtures en px de canvas → zoom+pan centrados.
  // Expuesto vía fitRef porque el tamaño del canvas solo se conoce aquí.
  if (fitRef) {
    fitRef.current = () => {
      const cv = canvasRef.current;
      const fxs = fixturesRef.current;
      if (!cv || fxs.length === 0) return;
      const m = 60, w = cv.clientWidth, h = cv.clientHeight;
      const pts = fxs.map((f) => pxOfRef.current(f));
      const xs = pts.map(([px]) => m + px * (w - 2 * m));
      const ys = pts.map(([, py]) => m + py * (h - 2 * m));
      const pad = 70; // margen extra alrededor del bbox (glow 46px + label)
      const minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad;
      const minY = Math.min(...ys) - pad, maxY = Math.max(...ys) + pad;
      const z = Math.max(0.25, Math.min(w / Math.max(1, maxX - minX), h / Math.max(1, maxY - minY), 3));
      const px2 = w / 2 - ((minX + maxX) / 2) * z;
      const py2 = h / 2 - ((minY + maxY) / 2) * z;
      zoomRef.current = z; panRef.current = { x: px2, y: py2 };
      setZoom(z); setPanX(px2); setPanY(py2);
    };
  }

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const cr = containerRef.current?.getBoundingClientRect();
    if (!cr) return;
    const factor = e.deltaY > 0 ? 0.85 : 1.18;
    const mx = e.clientX - cr.left, my = e.clientY - cr.top;
    const z = zoomRef.current, p = panRef.current;
    const nz2 = Math.max(0.25, Math.min(8, z * factor));
    const sf = nz2 / z;
    const np = { x: mx - (mx - p.x) * sf, y: my - (my - p.y) * sf };
    zoomRef.current = nz2; panRef.current = np;
    setZoom(nz2); setPanX(np.x); setPanY(np.y);
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    setCtxMenu(null);
    if (e.button === 1) {
      e.preventDefault();
      panDragRef.current = { ox: panRef.current.x, oy: panRef.current.y, sx: e.clientX, sy: e.clientY };
      return;
    }
    if (e.button !== 0) return;
    const { cx, cy } = toCanvas(e.clientX, e.clientY);
    const f = nearestFix(cx, cy);
    if (f) {
      if (e.shiftKey) {
        onMultiSelToggle(f.fixture_id);
      } else {
        onSelect(f.fixture_id);
        dragRef.current = { id: f.fixture_id, moved: false };
      }
    } else {
      rubberStartRef.current = { x1: cx, y1: cy };
    }
  };

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    const { cx, cy } = toCanvas(e.clientX, e.clientY);
    const f = nearestFix(cx, cy);
    if (f) setCtxMenu({ x: e.clientX, y: e.clientY, fixtureId: f.fixture_id });
  };

  let rubberStyle: { left: number; top: number; width: number; height: number } | null = null;
  if (rubber) {
    rubberStyle = {
      left: Math.min(rubber.x1, rubber.x2) * zoom + panX,
      top: Math.min(rubber.y1, rubber.y2) * zoom + panY,
      width: Math.abs(rubber.x2 - rubber.x1) * zoom,
      height: Math.abs(rubber.y2 - rubber.y1) * zoom,
    };
  }

  return (
    <div ref={containerRef}
      style={{ position: "relative", overflow: "hidden", width: "100%", height: "100%", cursor: "default" }}
      onWheel={handleWheel} onMouseDown={handleMouseDown} onContextMenu={handleContextMenu}>
      <canvas ref={canvasRef}
        style={{ display: "block", width: "100%", height: "100%",
          transform: `translate(${panX}px,${panY}px) scale(${zoom})`,
          transformOrigin: "0 0" }} />
      {rubberStyle && (
        <div style={{ position: "absolute", border: "1px dashed rgba(130,160,255,0.8)",
          background: "rgba(100,130,255,0.08)", pointerEvents: "none",
          left: rubberStyle.left, top: rubberStyle.top,
          width: rubberStyle.width, height: rubberStyle.height }} />
      )}
      {zoom !== 1 && (
        <button className="btn sm ghost"
          style={{ position: "absolute", bottom: 6, right: 6, fontSize: 10, padding: "2px 6px" }}
          onClick={() => { setZoom(1); setPanX(0); setPanY(0); zoomRef.current = 1; panRef.current = { x: 0, y: 0 }; }}>
          1:1
        </button>
      )}
      <CtxMenu menu={ctxMenu} onClose={() => setCtxMenu(null)} onAction={onCtxAction} />
    </div>
  );
}


// ── J3 — GDTF Browser ────────────────────────────────────────────────────────

type GdtfProfile = { name: string; manufacturer: string; modes: string[]; channel_count: number; path: string };

function GdtfBrowserModal({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [profiles, setProfiles] = useState<GdtfProfile[]>([]);
  const [search, setSearch] = useState("");
  const [sel, setSel] = useState<GdtfProfile | null>(null);
  const [universe, setUniverse] = useState(11);
  const [dmxStart, setDmxStart] = useState(1);
  const [customName, setCustomName] = useState("");
  const [mode, setMode] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    control.call("list_gdtf_profiles").then((r: any) => {
      const list: GdtfProfile[] = r?.profiles ?? [];
      setProfiles(list);
    }).catch(() => {});
  }, []);

  useEffect(() => { if (sel) setMode(sel.modes[0] ?? ""); }, [sel]);

  const filtered = profiles.filter((p) => {
    const q = search.toLowerCase();
    return !q || p.name.toLowerCase().includes(q) || p.manufacturer.toLowerCase().includes(q);
  });

  const addFromGdtf = async () => {
    if (!sel) return;
    setStatus("Añadiendo...");
    try {
      const r: any = await control.call("add_fixture_from_gdtf", {
        profile_path: sel.path, universe, start_channel: dmxStart,
        name: customName || sel.name, mode_name: mode || undefined, count: quantity,
      });
      if (r?.ok) { setStatus("✓ Añadido"); setTimeout(() => { onAdded(); }, 800); }
      else setStatus("Error: " + (r?.error ?? "desconocido"));
    } catch (e: any) { setStatus("Error: " + e.message); }
  };

  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="preset-editor" style={{ width: 480, maxHeight: "80vh", display: "flex", flexDirection: "column" }}>
        <div className="ci-head"><h4>Biblioteca GDTF</h4><button className="x" onClick={onClose}>×</button></div>
        <div style={{ padding: "6px 14px" }}>
          <input className="field" style={{ width: "100%" }} placeholder="Buscar por nombre o fabricante..."
            value={search} onChange={(e) => setSearch(e.target.value)} autoFocus />
        </div>
        <div style={{ flex: 1, overflow: "auto", borderTop: "1px solid var(--line)", borderBottom: "1px solid var(--line)" }}>
          {filtered.length === 0 ? (
            <div style={{ padding: 16, color: "var(--txt-3)", fontSize: 12 }}>
              {profiles.length === 0 ? "No hay perfiles GDTF en profiles/" : "Sin resultados"}
            </div>
          ) : filtered.map((p) => (
            <div key={p.path} onClick={() => setSel(p)}
              style={{
                padding: "6px 14px", cursor: "pointer", fontSize: 12,
                background: sel?.path === p.path ? "rgba(255,255,255,0.06)" : undefined,
                borderBottom: "1px solid rgba(255,255,255,0.04)",
              }}>
              <div style={{ fontWeight: 600 }}>{p.name}</div>
              <div style={{ color: "var(--txt-3)" }}>{p.manufacturer} · {p.channel_count}ch · {p.modes.length} modo{p.modes.length !== 1 ? "s" : ""}</div>
            </div>
          ))}
        </div>
        {sel && (
          <div className="ci-body" style={{ flexShrink: 0 }}>
            <div style={{ fontSize: 11, color: "var(--txt-3)", marginBottom: 4 }}>{sel.path.split(/[/\\]/).pop()}</div>
            {sel.modes.length > 1 && (
              <div className="ci-row"><label>Modo DMX</label>
                <select value={mode} onChange={(e) => setMode(e.target.value)}>
                  {sel.modes.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
            )}
            <div className="ci-row"><label>Nombre</label><input value={customName} onChange={(e) => setCustomName(e.target.value)} placeholder={sel.name} /></div>
            <div className="ci-row"><label>Cantidad</label><input type="number" min={1} value={quantity} onChange={(e) => setQuantity(+e.target.value)} style={{ width: 80 }} /></div>
            <div className="ci-row"><label>Universo</label><input type="number" value={universe} onChange={(e) => setUniverse(+e.target.value)} style={{ width: 60 }} /></div>
            <div className="ci-row"><label>DMX start</label><input type="number" value={dmxStart} onChange={(e) => setDmxStart(+e.target.value)} style={{ width: 60 }} /></div>
            <div className="ci-row" style={{ marginTop: 6 }}>
              <button className="btn primary sm" style={{ flex: 1 }} onClick={addFromGdtf}>Añadir al rig</button>
              {status && <span style={{ fontSize: 11, marginLeft: 8, color: status.startsWith("✓") ? "var(--good)" : "var(--bad)" }}>{status}</span>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function AddFixtureModal({ profiles, onClose, onAdded }: {
  profiles: any[]; onClose: () => void; onAdded: () => void;
}) {
  const [profileId, setProfileId] = useState(profiles[0]?.profile_id ?? "");
  const [name, setName] = useState("");
  const [universe, setUniverse] = useState(11);
  const [dmxStart, setDmxStart] = useState(1);
  const [quantity, setQuantity] = useState(1);
  const create = async () => {
    const fid = (name || profileId || "fixture").toLowerCase().replace(/[^a-z0-9]+/g, "_") + "_" + Date.now().toString().slice(-4);
    await control.call("add_fixture", {
      fixture_id: fid, profile_id: profileId, universe, dmx_start: dmxStart,
      position: [0, 1, 0], label: name || fid, count: quantity,
    });
    onAdded();
  };
  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="preset-editor">
        <div className="ci-head"><h4>Añadir fixture{quantity > 1 ? ` (${quantity})` : ""}</h4><button className="x" onClick={onClose}>×</button></div>
        <div className="ci-body">
          <div className="ci-row"><label>Perfil</label>
            <select value={profileId} onChange={(e) => setProfileId(e.target.value)}>
              {profiles.map((p) => <option key={p.profile_id} value={p.profile_id}>{p.name} ({p.kind}, {p.num_channels}ch)</option>)}
            </select></div>
          <div className="ci-row"><label>Nombre</label><input value={name} onChange={(e) => setName(e.target.value)} placeholder="(auto)" /></div>
          <div className="ci-row"><label>Cantidad</label><input type="number" min={1} value={quantity} onChange={(e) => setQuantity(+e.target.value)} style={{ width: 80 }} /></div>
          <div className="ci-row"><label>Universo</label><input type="number" value={universe} onChange={(e) => setUniverse(+e.target.value)} /></div>
          <div className="ci-row"><label>DMX start</label><input type="number" value={dmxStart} onChange={(e) => setDmxStart(+e.target.value)} /></div>
          <div className="ci-row" style={{ marginTop: 6 }}><button className="btn primary sm" style={{ flex: 1 }} onClick={create}>Añadir</button></div>
        </div>
      </div>
    </div>
  );
}

// ── G4: Panel de salida DMX USB ──────────────────────────────────────────────

function DmxUsbPanel() {
  const [ports, setPorts] = useState<string[]>([]);
  const [universe, setUniverse] = useState("1");
  const [port, setPort] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const refresh = () => {
    control.call("list_dmx_ports").then((r: any) => {
      const list = r?.ports ?? [];
      setPorts(list);
      if (list.length > 0 && !port) setPort(list[0]);
    }).catch(() => {});
  };

  useEffect(() => { refresh(); }, []);

  const apply = () => {
    control.call("set_output_target", {
      universe: parseInt(universe, 10),
      type: "dmx_usb",
      port,
    }).then((r: any) => {
      setStatus(r?.ok ? "Configurado ✓" : (r?.error ?? "Error"));
      setTimeout(() => setStatus(null), 3000);
    }).catch((e: any) => { setStatus("Error: " + e.message); setTimeout(() => setStatus(null), 3000); });
  };

  return (
    <div className="osc-panel" style={{ borderTop: "1px solid var(--line)", flexShrink: 0 }}>
      <div className="panel-head" style={{ cursor: "pointer" }} onClick={() => { setOpen((v) => !v); if (!open) refresh(); }}>
        <h3>DMX USB</h3>
        <span className="ph-spacer" />
        <span className="chip" style={{ color: ports.length > 0 ? "var(--good)" : "var(--txt-3)" }}>
          {ports.length > 0 ? `${ports.length} puerto${ports.length > 1 ? "s" : ""}` : "sin puertos"}
        </span>
        <span style={{ marginLeft: 6, opacity: 0.5, fontSize: 11 }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <div style={{ padding: "0 14px 12px", fontSize: 12 }}>
          {ports.length === 0 ? (
            <div style={{ color: "var(--txt-3)", marginBottom: 8 }}>
              Sin puertos COM disponibles. Conecta el ENTTEC Open DMX y recarga.
            </div>
          ) : null}
          <div className="form-row">
            <span className="fl">Puerto COM</span>
            <div className="fv" style={{ gap: 6 }}>
              {ports.length > 0 ? (
                <select className="field" value={port} onChange={(e) => setPort(e.target.value)} style={{ flex: 1 }}>
                  {ports.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              ) : (
                <input className="field" placeholder="COM3" value={port}
                  onChange={(e) => setPort(e.target.value)} style={{ flex: 1 }} />
              )}
              <button className="btn sm ghost" onClick={refresh} title="Refrescar lista de puertos">↺</button>
            </div>
          </div>
          <div className="form-row">
            <span className="fl">Universo DMX</span>
            <div className="fv">
              <input className="field" type="number" min={1} max={512} value={universe}
                onChange={(e) => setUniverse(e.target.value)} style={{ width: 60 }} />
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
            <button className="btn sm primary" onClick={apply} disabled={!port}>
              Aplicar
            </button>
            {status && <span style={{ fontSize: 11, color: status.includes("✓") ? "var(--good)" : "var(--bad)" }}>{status}</span>}
          </div>
          <div style={{ marginTop: 8, color: "var(--txt-3)", lineHeight: 1.5 }}>
            ENTTEC Open DMX USB · 250 kbaud 8N2 · pyserial requerido
          </div>
        </div>
      )}
    </div>
  );
}

// ── L2: Panel de Webhooks ────────────────────────────────────────────────────

type WebhookCfg = { url: string; events: string[]; secret: string };

const ALL_EVENTS = ["on_cue_change", "on_clip_start", "on_clip_stop", "on_transport_change"];

// ── N2: Panel Bundle (backup / restauración) ──────────────────────────────

function BundlePanel() {
  const [open, setOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportPath, setExportPath] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{ slug?: string; warnings?: string[]; error?: string } | null>(null);

  const doExport = async (includeAudio: boolean) => {
    setExporting(true);
    setExportPath(null);
    try {
      const r = await control.call("export_show_bundle", { include_audio: includeAudio });
      if (r.ok) setExportPath(r.path);
      else setExportPath(`Error: ${r.error}`);
    } catch {
      setExportPath("Error de red");
    } finally {
      setExporting(false);
    }
  };

  const doImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportResult(null);
    const zipPath = (file as any).path ?? file.name;
    try {
      const r = await control.call("import_show_bundle", { zip_path: zipPath });
      setImportResult(r.ok ? { slug: r.slug, warnings: r.warnings } : { error: r.error });
    } catch {
      setImportResult({ error: "Error de red" });
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="osc-panel">
      <div className="osc-head" onClick={() => setOpen((o) => !o)} style={{ cursor: "pointer" }}>
        <span>📦 Bundle (backup)</span>
        <span style={{ marginLeft: "auto", opacity: 0.5 }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <div style={{ padding: "8px 12px", display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn sm" style={{ flex: 1 }} onClick={() => doExport(false)} disabled={exporting}>
              {exporting ? "Exportando…" : "📦 Exportar"}
            </button>
            <button className="btn sm ghost" onClick={() => doExport(true)} disabled={exporting}>+ audio</button>
          </div>
          {exportPath && (
            <div style={{ fontSize: 10, color: exportPath.startsWith("Error") ? "var(--bad)" : "var(--ok)", wordBreak: "break-all" }}>
              {exportPath}
            </div>
          )}
          <label style={{ fontSize: 11, cursor: "pointer", color: "var(--accent)" }}>
            📥 Importar bundle…
            <input type="file" accept=".zip" style={{ display: "none" }} onChange={doImport} disabled={importing} />
          </label>
          {importing && <div style={{ fontSize: 11, color: "var(--txt-4)" }}>Importando…</div>}
          {importResult && (
            <div style={{ fontSize: 11 }}>
              {importResult.error ? (
                <span style={{ color: "var(--bad)" }}>Error: {importResult.error}</span>
              ) : (
                <>
                  <span style={{ color: "var(--ok)" }}>Importado como "{importResult.slug}"</span>
                  {(importResult.warnings ?? []).map((w, i) => (
                    <div key={i} style={{ color: "var(--warn)", marginTop: 2 }}>⚠ {w}</div>
                  ))}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Patch UX: Mapa de canales DMX por universo ──────────────────────────────

type USlot = { fixture_id: string; label: string; start: number; end: number; num_channels: number };
const PATCH_PALETTE = [
  "#7b68ee", "#20b2aa", "#ff6b6b", "#ffa07a", "#4ecdc4",
  "#45b7d1", "#96ceb4", "#ff9f43", "#fd79a8", "#00b894",
  "#6c5ce7", "#fdcb6e", "#e17055", "#74b9ff", "#a29bfe",
];

function UniverseChannelMap({ fixtures, onSelectFixture }: {
  fixtures: Fixture[];
  onSelectFixture: (id: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const [activeU, setActiveU] = useState<string | null>(null);
  const [uMap, setUMap] = useState<Record<string, USlot[]>>({});

  useEffect(() => {
    control.call("get_universe_channel_map").then((r: any) => {
      if (!r?.ok) return;
      const m: Record<string, USlot[]> = r.universes ?? {};
      setUMap(m);
      setActiveU(prev => prev && m[prev] ? prev : (Object.keys(m).sort((a, b) => +a - +b)[0] ?? null));
    }).catch(() => {});
  }, [fixtures]);

  const universes = Object.keys(uMap).sort((a, b) => +a - +b);
  const slots = activeU ? (uMap[activeU] ?? []) : [];
  const usedCh = slots.reduce((s, f) => s + f.num_channels, 0);

  return (
    <div style={{ borderTop: "1px solid var(--line)", flexShrink: 0 }}>
      <div className="panel-head" style={{ cursor: "pointer" }} onClick={() => setOpen(v => !v)}>
        <h3>Mapa DMX</h3>
        <span className="ph-spacer" />
        {activeU && <span className="chip" style={{ color: "var(--txt-2)" }}>U{activeU} · {usedCh}/512 ch</span>}
        <span style={{ marginLeft: 6, opacity: 0.5, fontSize: 11 }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <div style={{ padding: "6px 14px 12px" }}>
          {universes.length === 0 ? (
            <div style={{ color: "var(--txt-3)", fontSize: 11 }}>Sin fixtures en el rig</div>
          ) : (
            <>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 8 }}>
                {universes.map(u => (
                  <button key={u}
                    className={"btn sm" + (u === activeU ? "" : " ghost")}
                    style={{ padding: "2px 8px", fontSize: 10 }}
                    onClick={() => setActiveU(u)}>U{u}</button>
                ))}
              </div>

              {/* Barra 512 canales */}
              <div style={{
                position: "relative", height: 30, borderRadius: 4, overflow: "hidden",
                background: "var(--bg-1)", border: "1px solid var(--line)", marginBottom: 4,
              }}>
                {/* Mostrar gaps primero (background) */}
                {(() => {
                  const sorted = [...slots].sort((a, b) => a.start - b.start);
                  const gaps: Array<{ start: number; end: number; size: number }> = [];
                  if (sorted.length === 0) {
                    gaps.push({ start: 1, end: 512, size: 512 });
                  } else {
                    if (sorted[0].start > 1) gaps.push({ start: 1, end: sorted[0].start - 1, size: sorted[0].start - 1 });
                    for (let i = 0; i < sorted.length - 1; i++) {
                      const gapStart = sorted[i].end + 1;
                      const gapEnd = sorted[i + 1].start - 1;
                      if (gapEnd >= gapStart) gaps.push({ start: gapStart, end: gapEnd, size: gapEnd - gapStart + 1 });
                    }
                    const lastEnd = sorted[sorted.length - 1].end;
                    if (lastEnd < 512) gaps.push({ start: lastEnd + 1, end: 512, size: 512 - lastEnd });
                  }
                  return gaps.map((gap) => {
                    const left = ((gap.start - 1) / 512) * 100;
                    const width = (gap.size / 512) * 100;
                    return (
                      <div key={`gap-${gap.start}`}
                        title={`Libre: ch ${gap.start}–${gap.end} (${gap.size}ch)`}
                        style={{
                          position: "absolute", left: `${left}%`, width: `${Math.max(width, 0.2)}%`,
                          top: 0, bottom: 0, background: "rgba(255,255,255,0.06)", cursor: "default",
                        }} />
                    );
                  });
                })()}

                {/* Mostrar slots usados */}
                {slots.map((slot, i) => {
                  const left = ((slot.start - 1) / 512) * 100;
                  const width = (slot.num_channels / 512) * 100;
                  return (
                    <div key={slot.fixture_id}
                      title={`${slot.label}: ch ${slot.start}–${slot.end} (${slot.num_channels}ch)`}
                      onClick={() => onSelectFixture(slot.fixture_id)}
                      style={{
                        position: "absolute", left: `${left}%`, width: `${Math.max(width, 0.15)}%`,
                        top: 0, bottom: 0, background: PATCH_PALETTE[i % PATCH_PALETTE.length],
                        opacity: 0.88, cursor: "pointer", borderRight: "1px solid rgba(0,0,0,0.25)",
                        display: "flex", alignItems: "center", paddingLeft: 3, overflow: "hidden", zIndex: 1,
                      }}>
                      {width > 4 && (
                        <span style={{ fontSize: 8, color: "#fff", fontWeight: 700,
                          whiteSpace: "nowrap", pointerEvents: "none" }}>{slot.start}</span>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Escala */}
              <div style={{ display: "flex", justifyContent: "space-between",
                fontSize: 9, color: "var(--txt-3)", marginBottom: 8 }}>
                {[1, 64, 128, 192, 256, 320, 384, 448, 512].map(n => <span key={n}>{n}</span>)}
              </div>

              {/* Leyenda */}
              {slots.map((slot, i) => (
                <div key={slot.fixture_id} onClick={() => onSelectFixture(slot.fixture_id)}
                  style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11,
                    cursor: "pointer", padding: "2px 3px", borderRadius: 3,
                    marginBottom: 2 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, flexShrink: 0,
                    background: PATCH_PALETTE[i % PATCH_PALETTE.length] }} />
                  <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {slot.label}
                  </span>
                  <span className="mono" style={{ fontSize: 10, color: "var(--txt-3)", flexShrink: 0 }}>
                    {slot.start}–{slot.end}
                  </span>
                </div>
              ))}
              {slots.length === 0 && (
                <div style={{ color: "var(--txt-3)", fontSize: 11 }}>Sin fixtures en U{activeU}</div>
              )}
              <div style={{ marginTop: 6, fontSize: 10, color: "var(--txt-3)" }}>
                {usedCh} ch usados · {512 - usedCh} libres
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── A3: Protocolo del universo editable inline en el editor de fixture ────────

const OUTPUT_TYPE_LABEL: Record<string, string> = {
  wled: "WLED (Art-Net)", artnet_node: "Nodo Art-Net", sacn: "sACN E1.31",
  dmx_usb: "DMX USB", sim_only: "Simulación",
};

function UniverseOutputInline({ universe, targets, onChanged }: {
  universe: number; targets: Record<string, OutputTarget>; onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [type, setType] = useState("wled");
  const [ip, setIp] = useState("");
  const [port, setPort] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  const cur = targets[String(universe)];

  useEffect(() => {
    setEditing(false);
    setType(cur?.type ?? "wled");
    setIp(cur?.ip ?? "");
    setPort(cur?.port ?? "");
    setStatus(null);
  }, [universe, cur?.type, cur?.ip, cur?.port]);

  const summary = !cur
    ? "sin configurar"
    : cur.type === "dmx_usb"
      ? `DMX USB · ${cur.port ?? "?"}`
      : cur.type === "sim_only"
        ? "simulación"
        : `${OUTPUT_TYPE_LABEL[cur.type] ?? cur.type}${cur.ip ? " → " + cur.ip : ""}`;

  const apply = () => {
    const params: any = { universe, type };
    if (type === "dmx_usb") params.port = port || "COM3";
    else if (type !== "sim_only") params.ip = ip;
    control.call("set_output_target", params).then((r: any) => {
      if (r?.ok) { setStatus("✓"); setEditing(false); onChanged(); }
      else setStatus("⚠");
      setTimeout(() => setStatus(null), 1500);
    }).catch(() => { setStatus("⚠"); setTimeout(() => setStatus(null), 1500); });
  };

  return (
    <div style={{ fontSize: 11, margin: "4px 0 6px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span style={{ color: "var(--txt-3)" }}>U{universe}: {summary}</span>
        <button className="btn sm ghost" style={{ fontSize: 10, padding: "1px 5px" }}
          onClick={() => setEditing((v) => !v)}>{editing ? "✕" : "Cambiar"}</button>
      </div>
      {editing && (
        <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 3, flexWrap: "wrap" }}>
          <select className="field" style={{ fontSize: 10, padding: "2px 4px" }}
            value={type} onChange={(e) => setType(e.target.value)}>
            {Object.entries(OUTPUT_TYPE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          {type === "dmx_usb" ? (
            <input className="field" placeholder="COM3" value={port}
              onChange={(e) => setPort(e.target.value)} style={{ width: 60, fontSize: 10 }} />
          ) : type !== "sim_only" ? (
            <input className="field" placeholder="IP" value={ip}
              onChange={(e) => setIp(e.target.value)} style={{ width: 90, fontSize: 10 }} />
          ) : null}
          <button className="btn sm primary" style={{ fontSize: 10, padding: "1px 6px" }} onClick={apply}>✓</button>
          {status && <span style={{ fontSize: 9, color: status === "✓" ? "var(--good)" : "var(--bad)" }}>{status}</span>}
        </div>
      )}
    </div>
  );
}

// ── Patch UX: Destinos Art-Net / WLED ────────────────────────────────────────

function OutputTargetsPanel() {
  const [open, setOpen] = useState(false);
  const [targets, setTargets] = useState<Record<string, OutputTarget>>({});
  const [editIps, setEditIps] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<string | null>(null);

  const load = () =>
    control.call("get_output_targets").then((r: any) => {
      if (!r?.ok) return;
      const t: Record<string, OutputTarget> = r.targets ?? {};
      setTargets(t);
      setEditIps(Object.fromEntries(Object.entries(t).map(([u, v]) => [u, v.ip ?? ""])));
    }).catch(() => {});

  useEffect(() => { if (open) load(); }, [open]);

  const apply = (universe: string) => {
    const t = targets[universe];
    if (!t) return;
    const ip = editIps[universe] ?? "";
    control.call("set_output_target", { universe: parseInt(universe), type: t.type, ip })
      .then((r: any) => {
        if (r?.ok) { setStatus("✓ Aplicado"); load(); }
        else setStatus(r?.error ?? "Error");
        setTimeout(() => setStatus(null), 2500);
      }).catch((e: any) => { setStatus("Error: " + e.message); setTimeout(() => setStatus(null), 3000); });
  };

  const univs = Object.keys(targets).sort((a, b) => +a - +b);

  return (
    <div style={{ borderTop: "1px solid var(--line)", flexShrink: 0 }}>
      <div className="panel-head" style={{ cursor: "pointer" }} onClick={() => setOpen(v => !v)}>
        <h3>Destinos Art-Net / WLED</h3>
        <span className="ph-spacer" />
        <span className="chip">{univs.length} univ</span>
        <span style={{ marginLeft: 6, opacity: 0.5, fontSize: 11 }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <div style={{ padding: "0 14px 12px", fontSize: 12 }}>
          <div style={{ color: "var(--txt-3)", fontSize: 10, marginBottom: 8, lineHeight: 1.4 }}>
            Universo → IP de destino. Cambios se aplican al router inmediatamente.
          </div>
          {univs.map(u => {
            const t = targets[u];
            const hasIp = t.ip !== undefined;
            return (
              <div key={u} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5 }}>
                <span style={{ width: 24, fontSize: 11, color: "var(--txt-2)", fontWeight: 600, flexShrink: 0 }}>U{u}</span>
                <span style={{ width: 58, fontSize: 10, color: "var(--txt-3)", flexShrink: 0 }}>{t.type}</span>
                {hasIp ? (
                  <>
                    <input className="field" style={{ flex: 1, fontSize: 11, padding: "2px 5px" }}
                      value={editIps[u] ?? ""}
                      onChange={e => setEditIps(p => ({ ...p, [u]: e.target.value }))}
                      onKeyDown={e => e.key === "Enter" && apply(u)}
                      placeholder="192.168.x.x" />
                    <button className="btn sm ghost" style={{ fontSize: 10, padding: "2px 7px" }}
                      onClick={() => apply(u)}>✓</button>
                  </>
                ) : (
                  <span style={{ fontSize: 10, color: "var(--txt-3)" }}>
                    {t.type === "sim_only" ? "simulación" : t.type}
                  </span>
                )}
              </div>
            );
          })}
          {univs.length === 0 && (
            <div style={{ color: "var(--txt-3)", fontSize: 11 }}>
              Sin destinos en output_targets.json
            </div>
          )}
          {status && (
            <div style={{ marginTop: 4, fontSize: 11,
              color: status.startsWith("✓") ? "var(--good)" : "var(--bad)" }}>{status}</div>
          )}
          <button className="btn sm ghost" style={{ marginTop: 8, fontSize: 10 }} onClick={load}>↺ Recargar</button>
        </div>
      )}
    </div>
  );
}

function WebhookPanel() {
  const [open, setOpen] = useState(false);
  const [cfgs, setCfgs] = useState<WebhookCfg[]>([]);
  const [newUrl, setNewUrl] = useState("");
  const [newEvents, setNewEvents] = useState<string[]>(["on_cue_change"]);
  const [newSecret, setNewSecret] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  const load = () =>
    control.call("webhook_get_config", {}).then((r: any) => setCfgs(r?.configs ?? [])).catch(() => {});

  useEffect(() => { if (open) load(); }, [open]);

  const save = (next: WebhookCfg[]) => {
    control.call("webhook_set_config", { configs: next }).then((r: any) => {
      if (r?.ok) { setCfgs(next); setStatus("Guardado ✓"); }
      else setStatus(r?.error ?? "Error");
      setTimeout(() => setStatus(null), 2500);
    }).catch((e: any) => { setStatus("Error: " + e.message); setTimeout(() => setStatus(null), 3000); });
  };

  const add = () => {
    if (!newUrl) return;
    const next = [...cfgs, { url: newUrl, events: newEvents, secret: newSecret }];
    save(next);
    setNewUrl(""); setNewEvents(["on_cue_change"]); setNewSecret("");
  };

  const remove = (i: number) => save(cfgs.filter((_, idx) => idx !== i));

  const test = (cfg: WebhookCfg) => {
    control.call("webhook_get_config", {}).then(() => {
      setStatus(`Test enviado a ${cfg.url}`);
      setTimeout(() => setStatus(null), 3000);
    }).catch(() => {});
  };

  const toggleEvent = (ev: string) =>
    setNewEvents((prev) => prev.includes(ev) ? prev.filter((e) => e !== ev) : [...prev, ev]);

  return (
    <div className="osc-panel" style={{ borderTop: "1px solid var(--line)", flexShrink: 0 }}>
      <div className="panel-head" style={{ cursor: "pointer" }} onClick={() => setOpen((v) => !v)}>
        <h3>Webhooks</h3>
        <span className="ph-spacer" />
        <span className="chip" style={{ color: cfgs.length > 0 ? "var(--good)" : "var(--txt-3)" }}>
          {cfgs.length > 0 ? `${cfgs.length} activo${cfgs.length > 1 ? "s" : ""}` : "sin webhooks"}
        </span>
        <span style={{ marginLeft: 6, opacity: 0.5, fontSize: 11 }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <div style={{ padding: "0 14px 12px", fontSize: 12 }}>
          {cfgs.length === 0 && (
            <div style={{ color: "var(--txt-3)", marginBottom: 8 }}>Sin webhooks configurados.</div>
          )}
          {cfgs.map((cfg, i) => (
            <div key={i} style={{ background: "var(--bg-1)", borderRadius: 4, padding: "6px 8px", marginBottom: 6 }}>
              <div className="mono" style={{ fontSize: 11, color: "var(--acc)", wordBreak: "break-all" }}>{cfg.url}</div>
              <div style={{ color: "var(--txt-3)", marginTop: 2 }}>
                {cfg.events.join(", ")}
                {cfg.secret ? " · firmado" : ""}
              </div>
              <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                <button className="btn sm ghost" onClick={() => test(cfg)}>Test</button>
                <button className="btn sm ghost" style={{ color: "var(--bad)" }} onClick={() => remove(i)}>×</button>
              </div>
            </div>
          ))}
          <div style={{ marginTop: 8, marginBottom: 4, color: "var(--txt-3)" }}>Añadir webhook</div>
          <div className="form-row">
            <span className="fl">URL</span>
            <div className="fv">
              <input className="field" placeholder="https://..." value={newUrl}
                onChange={(e) => setNewUrl(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
            </div>
          </div>
          <div className="form-row">
            <span className="fl">Eventos</span>
            <div className="fv" style={{ flexWrap: "wrap", gap: 4 }}>
              {ALL_EVENTS.map((ev) => (
                <label key={ev} style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 11, cursor: "pointer" }}>
                  <input type="checkbox" checked={newEvents.includes(ev)} onChange={() => toggleEvent(ev)} />
                  {ev.replace("on_", "")}
                </label>
              ))}
            </div>
          </div>
          <div className="form-row">
            <span className="fl">Secret</span>
            <div className="fv">
              <input className="field" placeholder="(opcional)" value={newSecret}
                onChange={(e) => setNewSecret(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
            <button className="btn sm primary" onClick={add} disabled={!newUrl || newEvents.length === 0}>
              + Añadir
            </button>
            {status && <span style={{ fontSize: 11, color: status.includes("✓") || status.includes("enviado") ? "var(--good)" : "var(--bad)" }}>{status}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

type OscClient = { ip: string; port: number };
type OscState = {
  enabled: boolean; available: boolean; active: boolean;
  port_in: number; port_out: number;
  clients_out: OscClient[];
  recv_log: { addr: string; args: unknown[]; ts: number }[];
};

function OscPanel() {
  const [osc, setOsc] = useState<OscState | null>(null);
  const [open, setOpen] = useState(false);
  const [newIp, setNewIp] = useState("");
  const [newPort, setNewPort] = useState("8002");

  const load = () => control.call("osc_get_state").then((r) => setOsc(r as OscState)).catch(() => {});
  useEffect(() => { load(); }, []);

  const save = (patch: Partial<OscState>) => {
    const next = { ...osc, ...patch } as OscState;
    control.call("osc_set_config", {
      port_in: next.port_in, port_out: next.port_out,
      enabled: next.enabled, clients_out: next.clients_out,
    }).then((r) => setOsc(r as OscState)).catch(() => {});
  };

  const addClient = () => {
    if (!newIp || !newPort) return;
    const clients = [...(osc?.clients_out ?? []), { ip: newIp, port: +newPort }];
    save({ clients_out: clients });
    setNewIp(""); setNewPort("8002");
  };
  const removeClient = (i: number) => {
    const clients = (osc?.clients_out ?? []).filter((_, idx) => idx !== i);
    save({ clients_out: clients });
  };

  return (
    <div className="osc-panel" style={{ borderTop: "1px solid var(--line)", flexShrink: 0 }}>
      <div className="panel-head" style={{ cursor: "pointer" }} onClick={() => setOpen((v) => !v)}>
        <h3>OSC</h3>
        <span className="ph-spacer" />
        {osc && <span className="chip" style={{ color: osc.active ? "var(--good)" : osc.enabled ? "var(--warn)" : "var(--txt-3)" }}>
          {osc.active ? "activo" : osc.enabled ? "error" : "desactivado"}
        </span>}
        <span style={{ marginLeft: 6, opacity: 0.5, fontSize: 11 }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && osc && (
        <div style={{ padding: "0 14px 12px", fontSize: 12 }}>
          {!osc.available && (
            <div style={{ color: "var(--warn)", marginBottom: 8 }}>python-osc no instalado — pip install python-osc</div>
          )}
          <div className="form-row">
            <span className="fl">Activar</span>
            <div className="fv">
              <input type="checkbox" checked={osc.enabled} onChange={(e) => save({ enabled: e.target.checked })} />
            </div>
          </div>
          <div className="form-row">
            <span className="fl">Puerto IN</span>
            <div className="fv">
              <input className="field" type="number" style={{ width: 70 }} value={osc.port_in}
                onChange={(e) => setOsc((s) => s ? { ...s, port_in: +e.target.value } : s)}
                onBlur={() => save({ port_in: osc.port_in })} />
              <span style={{ marginLeft: 6, color: "var(--txt-3)" }}>UDP escucha</span>
            </div>
          </div>
          <div className="form-row">
            <span className="fl">Puerto OUT</span>
            <div className="fv">
              <input className="field" type="number" style={{ width: 70 }} value={osc.port_out}
                onChange={(e) => setOsc((s) => s ? { ...s, port_out: +e.target.value } : s)}
                onBlur={() => save({ port_out: osc.port_out })} />
            </div>
          </div>

          <div style={{ marginTop: 8, marginBottom: 4, color: "var(--txt-3)" }}>Destinos OUT</div>
          {osc.clients_out.map((c, i) => (
            <div key={i} className="form-row" style={{ gap: 6 }}>
              <span className="mono" style={{ fontSize: 11 }}>{c.ip}:{c.port}</span>
              <span className="ph-spacer" />
              <button className="btn sm ghost" onClick={() => removeClient(i)}>×</button>
            </div>
          ))}
          <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
            <input className="field" placeholder="IP" value={newIp} onChange={(e) => setNewIp(e.target.value)} style={{ width: 110 }} />
            <input className="field" type="number" placeholder="puerto" value={newPort} onChange={(e) => setNewPort(e.target.value)} style={{ width: 60 }} />
            <button className="btn sm" onClick={addClient}>+ Add</button>
          </div>

          {osc.recv_log.length > 0 && (
            <>
              <div style={{ marginTop: 10, marginBottom: 4, color: "var(--txt-3)" }}>Recibidos (últimos {osc.recv_log.length})</div>
              <div style={{ maxHeight: 100, overflow: "auto", background: "var(--bg-1)", borderRadius: 4, padding: "4px 6px" }}>
                {[...osc.recv_log].reverse().map((e, i) => (
                  <div key={i} className="mono" style={{ fontSize: 10, color: "var(--txt-2)", borderBottom: "1px solid var(--line)", padding: "2px 0" }}>
                    <span style={{ color: "var(--acc)" }}>{e.addr}</span>{" "}
                    {JSON.stringify(e.args)}
                    <span style={{ float: "right", opacity: 0.5 }}>{new Date(e.ts * 1000).toLocaleTimeString()}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          <div style={{ marginTop: 8 }}>
            <button className="btn sm ghost" onClick={load}>↺ Refrescar</button>
          </div>

          <div style={{ marginTop: 8, color: "var(--txt-3)", lineHeight: 1.4 }}>
            IN: /show/go_cue · /show/goto_t · /macro/brightness · /macro/strobe · /live/trigger · /live/stop_all
          </div>
        </div>
      )}
    </div>
  );
}

// ── E4: Panel de test de output (mapa de barras + Blackout) ─────────────────

function FixtureTestPanel({ fixtures }: { fixtures: Fixture[] }) {
  const [blackout, setBlackout] = useState(false);
  const [testColor, setTestColor] = useState("#ffffff");
  const [testActive, setTestActive] = useState<number | null>(null);
  const [identifying, setIdentifying] = useState<string | null>(null);
  const [chaseActive, setChaseActive] = useState<Set<number>>(new Set());
  const [identifyDuration, setIdentifyDuration] = useState(2000);

  // Sincronizar blackout con eventos del stream
  useEffect(() => {
    return stream.onBlackoutChanged((e: BlackoutChangedEvent) => {
      setBlackout(e.enabled);
    });
  }, []);

  const toggleBlackout = () => {
    const next = !blackout;
    control.call("blackout", { enabled: next }).catch(() => {});
    setBlackout(next);
  };

  const hexToRgb = (hex: string) => {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return { r, g, b };
  };

  const identify = (f: Fixture) => {
    setIdentifying(f.fixture_id);
    const { r, g, b } = hexToRgb(testColor);
    control.call("identify_fixture", {
      fixture_id: f.fixture_id,
      duration_ms: identifyDuration,
      color: [r, g, b],
    }).catch(() => {});
    setTimeout(() => setIdentifying(null), identifyDuration + 100);
  };

  const startChase = (universe: number) => {
    control.call("chase_test", { universe }).then((r: any) => {
      if (r?.ok) setChaseActive((prev) => new Set([...prev, universe]));
    }).catch(() => {});
  };
  const stopChase = (universe: number) => {
    control.call("chase_stop", { universe }).then(() => {
      setChaseActive((prev) => { const n = new Set(prev); n.delete(universe); return n; });
    }).catch(() => {});
  };

  const testUniverse = (universe: number) => {
    const { r, g, b } = hexToRgb(testColor);
    control.call("test_universe", { universe, r, g, b }).then((res) => {
      if (res.ok) {
        if (res.active) setTestActive(universe);
        else if (testActive === universe) setTestActive(null);
      }
    }).catch(() => {});
  };

  const barFixtures = fixtures.filter((f) => f.legacy_bar_idx != null)
    .sort((a, b) => (a.legacy_bar_idx ?? 0) - (b.legacy_bar_idx ?? 0));

  return (
    <div className="output-test-panel" style={{ padding: "10px 14px", borderTop: "1px solid var(--line)" }}>
      {/* Header con BLACKOUT */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <span style={{ fontWeight: 600, fontSize: 12, color: "var(--txt-2)" }}>Output Test</span>
        <span className="ph-spacer" style={{ flex: 1 }} />
        <span style={{
          fontSize: 11,
          color: blackout ? "var(--bad)" : "var(--good)",
          fontWeight: 600,
        }}>
          {blackout ? "BLACKOUT ACTIVO" : "Output OK"}
        </span>
        <button
          className={"btn" + (blackout ? " on" : "")}
          style={{
            background: blackout ? "var(--bad)" : undefined,
            color: blackout ? "#fff" : undefined,
            fontWeight: 700,
            fontSize: 12,
            padding: "4px 12px",
          }}
          onClick={toggleBlackout}
          title="Blackout duro instantáneo (E4)"
        >⬛ BLACKOUT</button>
      </div>

      {/* Color picker + duración para test/identify */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 11, color: "var(--txt-3)" }}>Color:</span>
        <input
          type="color"
          value={testColor}
          onChange={(e) => setTestColor(e.target.value)}
          style={{ width: 30, height: 22, border: "none", cursor: "pointer", background: "none" }}
        />
        <span className="mono" style={{ fontSize: 10, color: "var(--txt-3)" }}>{testColor.toUpperCase()}</span>
        <span style={{ fontSize: 11, color: "var(--txt-3)", marginLeft: 4 }}>dur:</span>
        <input type="number" min={200} max={10000} step={100} value={identifyDuration}
          onChange={(e) => setIdentifyDuration(+e.target.value)}
          style={{ width: 52, fontSize: 11 }} className="field" />
        <span style={{ fontSize: 10, color: "var(--txt-3)" }}>ms</span>
      </div>

      {/* Mapa de barras */}
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {barFixtures.map((f) => {
          const universe = f.universe ?? (f.legacy_bar_idx != null ? f.legacy_bar_idx + 1 : null);
          const isIdentifying = identifying === f.fixture_id;
          const isTestActive = universe != null && testActive === universe;
          const [r, g, b] = fixtureColor(f);
          return (
            <div
              key={f.fixture_id}
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "3px 6px",
                borderRadius: 4,
                border: isTestActive ? "1px solid var(--acc-2)" : "1px solid transparent",
                background: isIdentifying ? "rgba(255,255,255,0.06)" : undefined,
              }}
            >
              <span
                style={{
                  width: 14, height: 14, borderRadius: 2, flexShrink: 0,
                  background: `rgb(${r},${g},${b})`,
                  border: "1px solid rgba(255,255,255,0.15)",
                }}
              />
              <span style={{ fontSize: 11, minWidth: 70, color: "var(--txt-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {f.label || f.fixture_id}
              </span>
              <span className="mono" style={{ fontSize: 10, color: "var(--txt-3)", minWidth: 30 }}>
                {universe != null ? `U${universe}` : "—"}
              </span>
              <span className="ph-spacer" style={{ flex: 1 }} />
              <button
                className={"btn sm ghost" + (isIdentifying ? " on" : "")}
                style={{ fontSize: 10, padding: "1px 6px" }}
                onClick={() => identify(f)}
                title={`Identificar con color ${testColor} durante ${identifyDuration}ms`}
              >🔦</button>
              <button
                className={"btn sm ghost" + (isTestActive ? " on acc" : "")}
                style={{ fontSize: 10, padding: "1px 6px" }}
                onClick={() => universe != null && testUniverse(universe)}
                disabled={universe == null}
                title={isTestActive ? "Desactivar test" : "Test universo con color seleccionado"}
              >🎨</button>
              {universe != null && (
                chaseActive.has(universe) ? (
                  <button className="btn sm on acc" style={{ fontSize: 10, padding: "1px 6px" }}
                    onClick={() => stopChase(universe)} title="Detener chase">⏹</button>
                ) : (
                  <button className="btn sm ghost" style={{ fontSize: 10, padding: "1px 6px" }}
                    onClick={() => startChase(universe)} title="Chase rojo→verde→azul→blanco 500ms">▶Chase</button>
                )
              )}
            </div>
          );
        })}
        {barFixtures.length === 0 && (
          <div style={{ fontSize: 11, color: "var(--txt-3)", padding: "4px 0" }}>
            Sin barras LED en el rig
          </div>
        )}
      </div>
    </div>
  );
}

function FixtureEditorPanel({ fixtureId, onBack, onRefresh, universeIpMap, fixtures }: {
  fixtureId: string;
  onBack: () => void;
  onRefresh: () => void;
  universeIpMap: Record<number, string>;
  fixtures: Fixture[];
}) {
  const [detail, setDetail] = useState<FixtureDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [types, setTypes] = useState<FixtureType[]>([]);
  const [form, setForm] = useState<Partial<FixtureDetail>>({});
  const [dirty, setDirty] = useState(false);
  const [conflicts, setConflicts] = useState<ConflictInfo[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const [identifying, setIdentifying] = useState(false);
  const [testColor, setTestColor] = useState("#ffffff");
  const [targets, setTargets] = useState<Record<string, OutputTarget>>({});
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const selectFixture = useStore((s) => s.selectFixture);

  // Sync patch_x/patch_y bidireccional: canvas drag → inputs
  const storeFixture = fixtures.find((f) => f.fixture_id === fixtureId);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setLoadError(null);
    control.call("get_fixture_detail", { fixture_id: fixtureId })
      .then((r: any) => {
        if (cancelled) return;
        if (!r?.ok) {
          setLoadError(r?.error ?? "Error al cargar fixture");
          return;
        }
        setDetail(r.fixture);
        setForm(r.fixture);
        setDirty(false);
      }).catch((e: any) => {
        if (!cancelled) setLoadError(e?.message ?? "Error de conexión");
      });
    control.call("list_fixture_types")
      .then((r: any) => { if (!cancelled && r?.ok) setTypes(r.types ?? []); })
      .catch(() => {});
    control.call("get_output_targets")
      .then((r: any) => { if (!cancelled && r?.ok) setTargets(r.targets ?? {}); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [fixtureId]);

  useEffect(() => {
    if (!dirty && storeFixture) {
      setForm((prev) => ({
        ...prev,
        patch_x: storeFixture.patch_x,
        patch_y: storeFixture.patch_y,
      }));
    }
  }, [storeFixture?.patch_x, storeFixture?.patch_y, dirty]);

  const update = (fields: Partial<FixtureDetail>) => {
    const next = { ...form, ...fields };
    setForm(next);
    setDirty(true);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => autoSave(next), 400);
    if ("dmx_start" in fields || "universe" in fields) {
      control.call("update_fixture", {
        fixture_id: fixtureId,
        universe: next.universe,
        start_address: next.dmx_start,
        dry_run: true,
      }).then((r: any) => { if (r?.ok) setConflicts(r.conflicts ?? []); }).catch(() => {});
    }
  };

  const autoSave = async (cur: Partial<FixtureDetail>) => {
    const r: any = await control.call("update_fixture", {
      fixture_id: fixtureId,
      name: cur.label,
      start_address: cur.dmx_start,
      universe: cur.universe,
      kind_override: cur.kind_override,
      notes: cur.notes,
      patch_x: cur.patch_x,
      patch_y: cur.patch_y,
      height_m: cur.height_m,
      channel_map: cur.channel_map,
      target_ip: cur.target_ip,
      rotation_y: cur.rotation?.[1],
    }).catch(() => null);
    if (r?.ok) { setDirty(false); setConflicts([]); onRefresh(); }
    else if (r?.conflicts?.length > 0) setConflicts(r.conflicts);
  };

  const save = async () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    await autoSave(form);
    if (!conflicts.length) {
      const name = form.label || fixtureId;
      setToast(`${name} guardada ✓`);
      setTimeout(() => setToast(null), 2500);
    }
  };

  const identify = () => {
    setIdentifying(true);
    const hex = testColor.replace("#", "");
    const ri = parseInt(hex.slice(0, 2), 16);
    const gi = parseInt(hex.slice(2, 4), 16);
    const bi = parseInt(hex.slice(4, 6), 16);
    control.call("identify_fixture", { fixture_id: fixtureId, duration_ms: 2000, color: [ri, gi, bi] }).catch(() => {});
    setTimeout(() => setIdentifying(false), 2100);
  };

  if (loadError) return (
    <div style={{ padding: 16, fontSize: 12 }}>
      <div style={{ color: "var(--bad)", marginBottom: 8 }}>⚠ {loadError}</div>
      <div style={{ color: "var(--txt-3)", marginBottom: 10, fontSize: 11 }}>
        Reinicia el servidor Python si acabas de actualizar el código.
      </div>
      <button className="btn sm ghost" onClick={onBack}>← Volver</button>
    </div>
  );

  if (!detail) return (
    <div style={{ padding: 16, color: "var(--txt-3)", fontSize: 12 }}>Cargando…</div>
  );

  const numChannels = form.num_channels ?? detail.num_channels ?? 0;
  const addrStart = form.dmx_start ?? 1;
  const addrEnd = addrStart + numChannels - 1;
  const ipForUniverse = universeIpMap[form.universe ?? detail.universe] ?? detail.artnet_ip ?? null;
  const isCustomMode = (form.kind_override ?? "") === "custom";

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Header */}
      <div className="panel-head" style={{ borderBottom: "1px solid var(--line)", gap: 6, flexShrink: 0 }}>
        <button className="btn sm ghost" onClick={onBack} style={{ fontSize: 11, padding: "2px 7px" }}>← Fixtures</button>
        <span style={{ fontWeight: 600, fontSize: 12, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {dirty ? "● " : ""}{form.label || fixtureId}
        </span>
        <button className="btn sm ghost" title="Duplicar fixture con siguiente dirección libre"
          style={{ fontSize: 11, padding: "2px 7px" }}
          onClick={async () => {
            const r: any = await control.call("duplicate_fixture", { fixture_id: fixtureId }).catch(() => null);
            if (r?.ok) { onRefresh(); onBack(); }
            else if (r?.error) setToast("⚠ " + r.error);
          }}>⊕</button>
        <button className="btn sm primary" title="Guardar" onClick={save} style={{ fontSize: 12, padding: "2px 8px" }}>✓</button>
      </div>
      {toast && (
        <div style={{ margin: "4px 10px 0", padding: "3px 7px", background: "rgba(80,180,80,0.15)", borderRadius: 4, fontSize: 11, color: "var(--good)", flexShrink: 0 }}>
          {toast}
        </div>
      )}

      <div style={{ flex: 1, overflow: "auto", padding: "0 12px 12px" }}>

        {/* IDENTIDAD */}
        <div className="ci-sub" style={{ margin: "10px 0 4px" }}>IDENTIDAD</div>
        <div className="form-row">
          <span className="fl">Nombre</span>
          <div className="fv">
            <input className="field" value={form.label ?? ""} style={{ flex: 1 }}
              onChange={(e) => update({ label: e.target.value })} />
          </div>
        </div>
        <div className="form-row">
          <span className="fl">Tipo</span>
          <div className="fv">
            <select className="field" value={form.kind_override || form.profile_id || ""}
              style={{ flex: 1 }}
              onChange={(e) => update({ kind_override: e.target.value || null })}>
              {types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              {!types.find((t) => t.id === (form.kind_override || form.profile_id)) && (
                <option value={form.profile_id || ""}>{form.profile_id || "(sin tipo)"}</option>
              )}
            </select>
          </div>
        </div>
        <div className="form-row" style={{ alignItems: "flex-start" }}>
          <span className="fl" style={{ paddingTop: 4 }}>Notas</span>
          <div className="fv">
            <textarea className="field" value={form.notes ?? ""} rows={2}
              style={{ flex: 1, resize: "vertical", fontSize: 11, fontFamily: "inherit", minHeight: 34 }}
              onChange={(e) => update({ notes: e.target.value })} />
          </div>
        </div>

        {/* DMX — ART-NET */}
        <div className="ci-sub" style={{ margin: "10px 0 4px" }}>DMX — ART-NET</div>
        <div className="form-row">
          <span className="fl">Universo</span>
          <div className="fv" style={{ gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <select className="field" value={form.universe ?? 1} style={{ width: 60 }}
              onChange={(e) => update({ universe: parseInt(e.target.value, 10) })}>
              {Array.from({ length: 15 }, (_, i) => i + 1).map((u) => (
                <option key={u} value={u}>{u}{universeIpMap[u] ? ` · ${universeIpMap[u]}` : ""}</option>
              ))}
            </select>
            {ipForUniverse && (
              <span className="mono" style={{ fontSize: 10, color: "var(--txt-3)" }}>{ipForUniverse}</span>
            )}
          </div>
        </div>
        <div className="form-row">
          <span className="fl">DMX start</span>
          <div className="fv" style={{ gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <input className="field" type="number" min={1} max={512}
              value={addrStart} style={{ width: 60 }}
              onChange={(e) => update({ dmx_start: parseInt(e.target.value, 10) || 1 })} />
            <button className="btn sm ghost" title="Asignar primera dirección libre en este universo"
              style={{ fontSize: 10, padding: "2px 7px" }}
              onClick={async () => {
                const r: any = await control.call("next_free_address", {
                  universe: form.universe ?? detail.universe,
                  num_channels: numChannels || 1,
                }).catch(() => null);
                if (r?.ok) update({ dmx_start: r.address });
                else if (r?.error) setToast("⚠ " + r.error);
              }}>→ Libre</button>
            {numChannels > 0 && (
              <span style={{ fontSize: 10, color: "var(--txt-3)" }}>
                {numChannels} ch · {addrStart}–{addrEnd}
              </span>
            )}
          </div>
        </div>
        {conflicts.length > 0 && (
          <div style={{ marginBottom: 6, padding: "4px 7px", background: "rgba(255,140,0,0.1)", borderRadius: 4, borderLeft: "2px solid var(--warn)", fontSize: 11 }}>
            {conflicts.map((c) => (
              <div key={c.fixture_id} style={{ color: "var(--warn)" }}>
                ⚠ Conflicto con {c.name} ({c.address_range})
              </div>
            ))}
          </div>
        )}

        {/* RED / SALIDA — IP + protocolo del universo */}
        {universeIpMap && (
          <>
            <div className="ci-sub" style={{ margin: "10px 0 4px" }}>RED / SALIDA</div>
            {targets && <UniverseOutputInline universe={form.universe ?? 1} targets={targets}
              onChanged={() => {
                control.call("get_output_targets")
                  .then((r: any) => { if (r?.ok) setTargets(r.targets ?? {}); })
                  .catch(() => {});
              }} />}
            <div className="form-row">
              <span className="fl">IP fixture</span>
              <div className="fv" style={{ gap: 6, alignItems: "center" }}>
                <input className="field" type="text" placeholder="192.168.x.x (vacío = universo)"
                  value={form.target_ip ?? ""} style={{ flex: 1 }}
                  onChange={(e) => update({ target_ip: e.target.value || null })} />
                <span style={{ fontSize: 10, color: "var(--txt-3)" }}>opcional</span>
              </div>
            </div>
          </>
        )}

        {/* CANALES — solo si modo custom */}
        {isCustomMode && (
          <>
            <div className="ci-sub" style={{ margin: "10px 0 4px" }}>CANALES</div>
            {(form.channel_map ?? []).map((entry, i) => (
              <div className="form-row" key={i}>
                <span className="fl">Ch {entry.ch}</span>
                <div className="fv" style={{ gap: 6 }}>
                  <input className="field" value={entry.role} style={{ flex: 1 }}
                    placeholder="role (ej. red)"
                    onChange={(e) => {
                      const next = (form.channel_map ?? []).map((c, idx) =>
                        idx === i ? { ...c, role: e.target.value } : c);
                      update({ channel_map: next });
                    }} />
                  <button className="btn sm ghost" style={{ color: "var(--bad)", padding: "1px 6px" }}
                    onClick={() => update({ channel_map: (form.channel_map ?? []).filter((_, idx) => idx !== i) })}>×</button>
                </div>
              </div>
            ))}
            <button className="btn sm ghost" style={{ marginTop: 4, fontSize: 11 }}
              onClick={() => {
                const nextCh = (form.channel_map ?? []).length + 1;
                update({ channel_map: [...(form.channel_map ?? []), { ch: nextCh, role: "" }] });
              }}>+ Añadir canal</button>
          </>
        )}

        {/* POSICIÓN */}
        <div className="ci-sub" style={{ margin: "10px 0 4px" }}>POSICIÓN</div>
        <div className="form-row">
          <span className="fl">X</span>
          <div className="fv" style={{ gap: 6, alignItems: "center" }}>
            <input className="field" type="number" step={0.01} min={0} max={1}
              value={form.patch_x != null ? Math.round(form.patch_x * 1000) / 1000 : ""}
              placeholder="0.00" style={{ width: 68 }}
              onChange={(e) => update({ patch_x: parseFloat(e.target.value) })} />
            <span style={{ fontSize: 10, color: "var(--txt-3)" }}>canvas 0–1</span>
          </div>
        </div>
        <div className="form-row">
          <span className="fl">Y</span>
          <div className="fv" style={{ gap: 6, alignItems: "center" }}>
            <input className="field" type="number" step={0.01} min={0} max={1}
              value={form.patch_y != null ? Math.round(form.patch_y * 1000) / 1000 : ""}
              placeholder="0.00" style={{ width: 68 }}
              onChange={(e) => update({ patch_y: parseFloat(e.target.value) })} />
            <span style={{ fontSize: 10, color: "var(--txt-3)" }}>canvas 0–1</span>
          </div>
        </div>
        <div className="form-row">
          <span className="fl">Altura</span>
          <div className="fv" style={{ gap: 6, alignItems: "center" }}>
            <input className="field" type="number" step={0.1}
              value={form.height_m != null ? form.height_m : ""}
              placeholder="2.5" style={{ width: 68 }}
              onChange={(e) => update({ height_m: e.target.value !== "" ? parseFloat(e.target.value) : null })} />
            <span style={{ fontSize: 10, color: "var(--txt-3)" }}>m</span>
          </div>
        </div>
        <div className="form-row">
          <span className="fl">Rotación (Y)</span>
          <div className="fv" style={{ gap: 6, alignItems: "center" }}>
            <input className="field" type="number" step={1} min={0} max={360}
              value={form.rotation?.[1] != null ? Math.round(form.rotation[1]) : ""}
              placeholder="0" style={{ width: 68 }}
              onChange={(e) => {
                const ry = e.target.value !== "" ? parseFloat(e.target.value) : 0;
                update({ rotation: [form.rotation?.[0] ?? 0, ry, form.rotation?.[2] ?? 0] });
              }} />
            <span style={{ fontSize: 10, color: "var(--txt-3)" }}>°</span>
          </div>
        </div>

        {/* TEST EN VIVO */}
        <div className="ci-sub" style={{ margin: "10px 0 4px" }}>TEST EN VIVO</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <button className={"btn sm" + (identifying ? " on acc" : "")}
            onClick={identify} disabled={identifying} title="Identificar fixture 2 s">
            🔦 Identify
          </button>
          <input type="color" value={testColor} onChange={(e) => setTestColor(e.target.value)}
            style={{ width: 26, height: 24, border: "none", cursor: "pointer", background: "none" }} />
          <span className="mono" style={{ fontSize: 10, color: "var(--txt-3)" }}>{testColor.toUpperCase()}</span>
        </div>

        {/* Borrar */}
        <div style={{ marginTop: 14, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
          <button className="btn ghost" style={{ color: "var(--bad)", fontSize: 11 }}
            onClick={() => {
              control.call("delete_fixture", { fixture_id: fixtureId })
                .then(() => { selectFixture(null); onBack(); onRefresh(); })
                .catch(() => {});
            }}>Borrar fixture</button>
        </div>
      </div>
    </div>
  );
}

export function PatchView() {
  const fixtures = useStore((s) => s.fixtures);
  const sel = useStore((s) => s.selectedFixtureId);
  const selectFixture = useStore((s) => s.selectFixture);
  const refreshFixtures = useStore((s) => s.refreshFixtures);

  const [editingFixtureId, setEditingFixtureId] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<any[]>([]);
  const [adding, setAdding] = useState(false);
  const [gdtfBrowser, setGdtfBrowser] = useState(false);
  const [dirtyInEditor, setDirtyInEditor] = useState(false);
  const [search, setSearch] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  // E1 — filters
  const [filterUniverse, setFilterUniverse] = useState<number | null>(null);
  const [filterUnpositioned, setFilterUnpositioned] = useState(false);
  // P2 — multi-select
  const [multiSel, setMultiSel] = useState<Set<string>>(new Set());

  // D2 — Canvas zoom/pan (moved from PatchStage for Fit button access)
  const [zoom, setZoom] = useState(1);
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const fitRef = useRef<(() => void) | null>(null);

  // Phase B — bulk operations
  const [bulkRepatchModal, setBulkRepatchModal] = useState(false);
  const [bulkAlignModal, setBulkAlignModal] = useState(false);
  const [bulkRenameModal, setBulkRenameModal] = useState(false);
  const [bulkRepatchForm, setBulkRepatchForm] = useState({ universe: 1, startAddress: 1 });
  const [bulkRenameForm, setBulkRenameForm] = useState({ pattern: "Fixture {n}", startNum: 1 });

  // E2 — Import rig modal
  const [importRigModal, setImportRigModal] = useState(false);
  const [otherProjects, setOtherProjects] = useState<any[]>([]);
  const [selectedRigSlug, setSelectedRigSlug] = useState<string | null>(null);

  // F1 — Sequential rig test (cancel via ref: el bucle async no ve state actualizado)
  const [seqTestActive, setSeqTestActive] = useState(false);
  const seqCancelRef = useRef(false);

  const openEditor = (id: string) => {
    selectFixture(id);
    setEditingFixtureId(id);
    setDirtyInEditor(false);
  };

  // D3: Keyboard shortcuts — Ctrl+A, Esc, arrows (nudge), Del (delete), Ctrl+D (dup)
  useEffect(function() {
    function onKey(e: KeyboardEvent) {
      const isInput = (e.target as any)?.tagName === "INPUT" || (e.target as any)?.tagName === "TEXTAREA";
      if ((e.ctrlKey || e.metaKey) && e.key === "a") {
        e.preventDefault();
        setMultiSel(new Set(fixtures.map(function(f) { return f.fixture_id; })));
      } else if (e.key === "Escape") {
        setMultiSel(new Set());
      } else if (!isInput && (e.ctrlKey || e.metaKey) && e.key === "d") {
        e.preventDefault();
        if (multiSel.size > 0) multiDuplicate();
        else if (sel) control.call("duplicate_fixture", { fixture_id: sel }).then(() => refreshFixtures()).catch(() => {});
      } else if (!isInput && e.key === "Delete") {
        e.preventDefault();
        if (multiSel.size > 0) multiDelete();
        else if (sel) {
          control.call("delete_fixture", { fixture_id: sel })
            .then(() => { refreshFixtures(); setEditingFixtureId((cur) => cur === sel ? null : cur); })
            .catch(() => {});
        }
      } else if (!isInput && ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) {
        e.preventDefault();
        const target = sel || (multiSel.size > 0 ? Array.from(multiSel)[0] : null);
        if (target) {
          const f = fixtures.find((fx) => fx.fixture_id === target);
          if (f) {
            const step = e.shiftKey ? 0.05 : 0.01;
            const delta = { ArrowUp: [0, -step], ArrowDown: [0, step], ArrowLeft: [-step, 0], ArrowRight: [step, 0] }[e.key] || [0, 0];
            const newX = Math.max(0, Math.min(1, (f.patch_x ?? 0.5) + delta[0]));
            const newY = Math.max(0, Math.min(1, (f.patch_y ?? 0.5) + delta[1]));
            control.call("move_fixture", { fixture_id: target, x: newX, y: newY }).then(() => refreshFixtures()).catch(() => {});
          }
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return function() { window.removeEventListener("keydown", onKey); };
  }, [fixtures, sel, multiSel]);

  const handleMultiSelToggle = (id: string) => {
    setMultiSel((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleCtxAction = (action: string, id: string) => {
    if (action === "edit") { openEditor(id); return; }
    if (action === "identify") { control.call("identify_fixture", { fixture_id: id }).catch(() => {}); return; }
    if (action === "duplicate") {
      control.call("duplicate_fixture", { fixture_id: id }).then(() => refreshFixtures()).catch(() => {});
      return;
    }
    if (action === "delete") {
      control.call("delete_fixture", { fixture_id: id })
        .then(() => { refreshFixtures(); setEditingFixtureId((cur) => cur === id ? null : cur); })
        .catch(() => {});
    }
  };

  const multiDuplicate = () => {
    Array.from(multiSel).forEach((id) => control.call("duplicate_fixture", { fixture_id: id }).catch(() => {}));
    setTimeout(refreshFixtures, 400);
    setMultiSel(new Set());
  };

  const multiDelete = () => {
    const toDelete = Array.from(multiSel);
    toDelete.forEach((id) => control.call("delete_fixture", { fixture_id: id }).catch(() => {}));
    setTimeout(() => {
      refreshFixtures();
      setEditingFixtureId((cur) => cur && toDelete.includes(cur) ? null : cur);
    }, 400);
    setMultiSel(new Set());
  };

  const doBulkRepatch = async () => {
    const res = await control.call("bulk_repatch", {
      fixture_ids: Array.from(multiSel),
      universe: bulkRepatchForm.universe,
      start_address: bulkRepatchForm.startAddress,
    }).catch(() => null);
    if (res?.ok) {
      setToast("✓ Re-patched");
      setTimeout(() => setToast(null), 2500);
      setBulkRepatchModal(false);
      setMultiSel(new Set());
      refreshFixtures();
    } else if (res?.error) {
      setToast("⚠ " + res.error);
      setTimeout(() => setToast(null), 3000);
    }
  };

  const doBulkAlignH = async () => {
    const sorted = Array.from(multiSel)
      .map((id) => ({ id, pos: fixtures.find((f) => f.fixture_id === id)?.patch_x ?? 0 }))
      .sort((a, b) => a.pos - b.pos);
    const minX = Math.min(...sorted.map((s) => s.pos));
    const moves = sorted.map((s) => ({ fixture_id: s.id, x: minX }));
    const res = await control.call("bulk_move", { moves }).catch(() => null);
    if (res?.ok) {
      setToast("✓ Aligned H");
      setTimeout(() => setToast(null), 2500);
      setMultiSel(new Set());
      refreshFixtures();
    }
  };

  const doBulkAlignV = async () => {
    const sorted = Array.from(multiSel)
      .map((id) => ({ id, pos: fixtures.find((f) => f.fixture_id === id)?.patch_y ?? 0 }))
      .sort((a, b) => a.pos - b.pos);
    const minY = Math.min(...sorted.map((s) => s.pos));
    const moves = sorted.map((s) => ({ fixture_id: s.id, y: minY }));
    const res = await control.call("bulk_move", { moves }).catch(() => null);
    if (res?.ok) {
      setToast("✓ Aligned V");
      setTimeout(() => setToast(null), 2500);
      setMultiSel(new Set());
      refreshFixtures();
    }
  };

  const doBulkDistribute = async () => {
    const sorted = Array.from(multiSel)
      .map((id) => ({ id, pos: fixtures.find((f) => f.fixture_id === id)?.patch_x ?? 0 }))
      .sort((a, b) => a.pos - b.pos);
    if (sorted.length < 2) return;
    const minX = sorted[0].pos;
    const maxX = sorted[sorted.length - 1].pos;
    const step = (maxX - minX) / (sorted.length - 1);
    const moves = sorted.map((s, i) => ({ fixture_id: s.id, x: minX + i * step }));
    const res = await control.call("bulk_move", { moves }).catch(() => null);
    if (res?.ok) {
      setToast("✓ Distributed");
      setTimeout(() => setToast(null), 2500);
      setMultiSel(new Set());
      refreshFixtures();
    }
  };

  const doBulkRename = async () => {
    const res = await control.call("bulk_rename", {
      fixture_ids: Array.from(multiSel),
      pattern: bulkRenameForm.pattern,
      start_num: bulkRenameForm.startNum,
    }).catch(() => null);
    if (res?.ok) {
      setToast("✓ Renamed");
      setTimeout(() => setToast(null), 2500);
      setBulkRenameModal(false);
      setMultiSel(new Set());
      refreshFixtures();
    }
  };

  // E2 — Import rig from another project
  const loadOtherProjects = () => {
    control.call("list_projects_detailed", {}).then((r) => {
      setOtherProjects((r.projects || []).filter((p: any) => !p.is_current));
      setImportRigModal(true);
    }).catch(() => {});
  };

  const doImportRig = async () => {
    if (!selectedRigSlug) return;
    const res = await control.call("apply_rig", { from_slug: selectedRigSlug }).catch(() => null);
    if (res?.ok) {
      setToast("✓ Rig imported");
      setTimeout(() => setToast(null), 2500);
      setImportRigModal(false);
      setSelectedRigSlug(null);
      refreshFixtures();
    } else if (res?.error) {
      setToast("⚠ " + res.error);
      setTimeout(() => setToast(null), 3000);
    }
  };

  // F1 — Sequential rig test (identify each fixture in sequence)
  const doSequentialTest = async () => {
    setSeqTestActive(true);
    seqCancelRef.current = false;
    const testFixtures = fixtures.filter(f => f.universe != null);
    let canceled = false;
    for (let i = 0; i < testFixtures.length; i++) {
      if (seqCancelRef.current) { canceled = true; break; }
      const f = testFixtures[i];
      control.call("identify_fixture", { fixture_id: f.fixture_id, duration_ms: 1000 }).catch(() => {});
      await new Promise(r => setTimeout(r, 1200));
    }
    setSeqTestActive(false);
    setToast(canceled ? "⏹ Test cancelado" : "✓ Test secuencial completo");
    setTimeout(() => setToast(null), 2500);
  };

  useEffect(() => { control.call("list_fixture_profiles").then((r) => setProfiles(r.profiles || [])).catch(() => {}); }, []);

  // Mapa universo → IP derivado de los fixtures del rig
  const universeIpMap = Object.fromEntries(
    fixtures.filter((f) => f.target_ip).map((f) => [f.universe, f.target_ip!])
  ) as Record<number, string>;

  // Si el fixture editado fue borrado, volver a la lista
  useEffect(() => {
    if (editingFixtureId && !fixtures.find((f) => f.fixture_id === editingFixtureId)) {
      setEditingFixtureId(null);
    }
  }, [fixtures, editingFixtureId]);

  return (
    <div className="patch">
      <div className="patch-stage">
        <div className="patch-toolbar">
          <button className="btn sm" onClick={() => setAdding(true)}>+ Fixture</button>
          <button className="btn sm ghost" onClick={() => setGdtfBrowser(true)} title="Añadir fixture desde perfil GDTF">GDTF</button>
          <button className="btn sm ghost" onClick={() => fitRef.current?.()}
            title="Ajustar zoom y pan a todos los fixtures">⊡ Fit</button>
          <button className="btn sm ghost" onClick={loadOtherProjects} title="Importar rig de otro proyecto">📥 Rig</button>
          <button className={`btn sm ghost${seqTestActive ? " on" : ""}`}
            onClick={() => { if (seqTestActive) seqCancelRef.current = true; else doSequentialTest(); }}
            title="Test secuencial de todos los fixtures">{seqTestActive ? "⏹ Stop" : "▶ Test"}</button>
          <span style={{ flex: 1 }} />
          <span className="mono" style={{ fontSize: 10, color: "var(--txt-3)" }}>1:{(1/zoom).toFixed(1)}</span>
        </div>
        <PatchStage fixtures={fixtures} onSelect={openEditor}
          dirtyFixtureId={dirtyInEditor ? editingFixtureId : null}
          multiSel={multiSel} onMultiSelToggle={handleMultiSelToggle}
          onCtxAction={handleCtxAction} fitRef={fitRef}
          zoom={zoom} setZoom={setZoom} panX={panX} setPanX={setPanX} panY={panY} setPanY={setPanY} />
        {multiSel.size > 0 && (
          <div className="patch-toolbar" style={{ borderTop: "1px solid var(--line)", paddingTop: 4 }}>
            <span style={{ fontSize: 11, color: "var(--txt-2)" }}>{multiSel.size} sel.</span>
            <button className="btn sm ghost" onClick={multiDuplicate}>Duplicar</button>
            <button className="btn sm ghost" onClick={() => setBulkRepatchModal(true)}>Re-patch…</button>
            <button className="btn sm ghost" onClick={doBulkAlignH} title="Alinear horizontalmente">Alin.H</button>
            <button className="btn sm ghost" onClick={doBulkAlignV} title="Alinear verticalmente">Alin.V</button>
            <button className="btn sm ghost" onClick={doBulkDistribute} title="Distribuir espaciado">Dist.</button>
            <button className="btn sm ghost" onClick={() => setBulkRenameModal(true)}>Renombrar…</button>
            <button className="btn sm ghost" style={{ color: "var(--bad)" }} onClick={multiDelete}>Borrar</button>
            <button className="btn sm ghost" onClick={() => setMultiSel(new Set())}>✕</button>
          </div>
        )}
        <div className="patch-legend">
          <div className="lg">Shift+click=multi · Ctrl+A=todo · Esc=limpiar · Rueda=zoom · Btn-medio=pan · Clic-der=menú</div>
        </div>

        {/* Phase B — Bulk Repatch Modal */}
        {bulkRepatchModal && (
          <div className="modal-overlay" onClick={() => setBulkRepatchModal(false)}>
            <div className="modal-box" onClick={(e) => e.stopPropagation()}>
              <div className="modal-head">
                <h3>Re-patch en lote</h3>
                <button className="btn sm ghost" onClick={() => setBulkRepatchModal(false)}>✕</button>
              </div>
              <div className="modal-body" style={{ gap: 10, display: "flex", flexDirection: "column" }}>
                <div className="form-row" style={{ padding: "6px 10px" }}>
                  <span className="fl">Universo</span>
                  <div className="fv">
                    <select className="field" value={bulkRepatchForm.universe}
                      onChange={(e) => setBulkRepatchForm((p) => ({ ...p, universe: parseInt(e.target.value, 10) }))}>
                      {Array.from({ length: 15 }, (_, i) => i + 1).map((u) => (
                        <option key={u} value={u}>{u}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="form-row" style={{ padding: "6px 10px" }}>
                  <span className="fl">Dirección inicial</span>
                  <div className="fv">
                    <input className="field" type="number" min={1} max={512}
                      value={bulkRepatchForm.startAddress}
                      onChange={(e) => setBulkRepatchForm((p) => ({ ...p, startAddress: parseInt(e.target.value, 10) || 1 }))} />
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", padding: "10px" }}>
                  <button className="btn sm ghost" onClick={() => setBulkRepatchModal(false)}>Cancelar</button>
                  <button className="btn sm" onClick={doBulkRepatch}>Re-patch</button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Phase B — Bulk Rename Modal */}
        {bulkRenameModal && (
          <div className="modal-overlay" onClick={() => setBulkRenameModal(false)}>
            <div className="modal-box" onClick={(e) => e.stopPropagation()}>
              <div className="modal-head">
                <h3>Renombrar en lote</h3>
                <button className="btn sm ghost" onClick={() => setBulkRenameModal(false)}>✕</button>
              </div>
              <div className="modal-body" style={{ gap: 10, display: "flex", flexDirection: "column" }}>
                <div className="form-row" style={{ padding: "6px 10px" }}>
                  <span className="fl">Patrón</span>
                  <div className="fv">
                    <input className="field" value={bulkRenameForm.pattern}
                      placeholder="Ej: Barra {n}" style={{ flex: 1 }}
                      onChange={(e) => setBulkRenameForm((p) => ({ ...p, pattern: e.target.value }))} />
                    <span style={{ fontSize: 10, color: "var(--txt-3)" }}>use {"{n}"} para número</span>
                  </div>
                </div>
                <div className="form-row" style={{ padding: "6px 10px" }}>
                  <span className="fl">Empezar en</span>
                  <div className="fv">
                    <input className="field" type="number" min={1}
                      value={bulkRenameForm.startNum}
                      onChange={(e) => setBulkRenameForm((p) => ({ ...p, startNum: parseInt(e.target.value, 10) || 1 }))} />
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", padding: "10px" }}>
                  <button className="btn sm ghost" onClick={() => setBulkRenameModal(false)}>Cancelar</button>
                  <button className="btn sm" onClick={doBulkRename}>Renombrar</button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* E2 — Import Rig Modal */}
        {importRigModal && (
          <div className="modal-overlay" onClick={() => setImportRigModal(false)}>
            <div className="modal-box" onClick={(e) => e.stopPropagation()}>
              <div className="modal-head">
                <h3>Importar rig de otro proyecto</h3>
                <button className="btn sm ghost" onClick={() => setImportRigModal(false)}>✕</button>
              </div>
              <div className="modal-body" style={{ gap: 10, display: "flex", flexDirection: "column" }}>
                {otherProjects.length === 0 ? (
                  <div style={{ fontSize: 12, color: "var(--txt-3)", padding: "10px" }}>
                    No hay otros proyectos disponibles
                  </div>
                ) : (
                  <>
                    <div style={{ fontSize: 11, color: "var(--txt-2)", padding: "6px 10px" }}>
                      Selecciona un proyecto para importar su rig:
                    </div>
                    <div style={{ maxHeight: "300px", overflow: "auto", border: "1px solid var(--line)", borderRadius: 4 }}>
                      {otherProjects.map((p: any) => (
                        <div key={p.slug}
                          style={{
                            padding: "8px 10px",
                            cursor: "pointer",
                            background: selectedRigSlug === p.slug ? "var(--acc-1)" : "transparent",
                            borderLeft: selectedRigSlug === p.slug ? "3px solid var(--acc-2)" : "none",
                            color: selectedRigSlug === p.slug ? "var(--txt)" : "var(--txt-2)",
                          }}
                          onClick={() => setSelectedRigSlug(p.slug)}>
                          <div style={{ fontWeight: 600, fontSize: 12 }}>{p.name || p.slug}</div>
                          <div style={{ fontSize: 10, color: "var(--txt-3)", marginTop: 2 }}>
                            {p.rig?.fixture_count ?? 0} fixtures · {p.song?.title || "sin canción"}
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                )}
                <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", padding: "10px" }}>
                  <button className="btn sm ghost" onClick={() => setImportRigModal(false)}>Cancelar</button>
                  <button className="btn sm" onClick={doImportRig} disabled={!selectedRigSlug}>Importar</button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="patch-side">
        {editingFixtureId ? (
          <FixtureEditorPanel
            key={editingFixtureId}
            fixtureId={editingFixtureId}
            onBack={() => setEditingFixtureId(null)}
            onRefresh={refreshFixtures}
            universeIpMap={universeIpMap}
            fixtures={fixtures}
          />
        ) : (
          <>
            <div className="panel-head"><h3>Fixtures</h3><span className="ph-spacer" /><span className="chip">{fixtures.length}</span></div>
            {/* Buscador y filtros E1 */}
            <div style={{ padding: "5px 10px 3px", borderBottom: "1px solid var(--line)", flexShrink: 0 }}>
              <input className="field" placeholder="Buscar fixture…" value={search}
                onChange={e => setSearch(e.target.value)}
                style={{ width: "100%", fontSize: 11, padding: "3px 7px", marginBottom: 4 }} />
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap", fontSize: 10 }}>
                {Array.from(new Set(fixtures.map(f => f.universe))).sort((a, b) => a - b).map(u => (
                  <button key={u} className={`btn xs ${filterUniverse === u ? "" : "ghost"}`}
                    style={{ padding: "2px 6px", fontSize: 9 }}
                    onClick={() => setFilterUniverse(filterUniverse === u ? null : u)}>U{u}</button>
                ))}
                <button className={`btn xs ${filterUnpositioned ? "" : "ghost"}`}
                  style={{ padding: "2px 6px", fontSize: 9 }}
                  onClick={() => setFilterUnpositioned(!filterUnpositioned)}>📍 Sin pos</button>
              </div>
            </div>
            <div style={{ flex: "0 0 auto", maxHeight: "30%", overflow: "auto" }}>
              {fixtures
                .filter(f => !search || (f.label || f.fixture_id).toLowerCase().includes(search.toLowerCase()))
                .filter(f => !filterUniverse || f.universe === filterUniverse)
                .filter(f => !filterUnpositioned || f.patch_x == null)
                .map((f) => {
                  const [r, g, b] = fixtureColor(f);
                  return (
                    <div key={f.fixture_id} className={"fix-item" + (sel === f.fixture_id ? " sel" : "")}
                      onClick={() => openEditor(f.fixture_id)}>
                      <span className="sw" style={{ background: `rgb(${r},${g},${b})` }} />
                      <div className="fi-txt">
                        <div className="fi-name">{f.label || f.fixture_id}</div>
                        <div className="fi-meta">U{f.universe} · ch {f.dmx_start}{f.target_ip ? ` · ${f.target_ip}` : ""}</div>
                      </div>
                      <span className="fi-leds" style={{ fontSize: 10, color: "var(--txt-3)" }}>
                        {f.legacy_bar_idx != null ? `${LEDS} px` : f.profile_id}
                      </span>
                    </div>
                  );
                })}
            </div>
            {/* Mapa de canales DMX */}
            <UniverseChannelMap fixtures={fixtures} onSelectFixture={openEditor} />
            <FixtureTestPanel fixtures={fixtures} />
            <OutputTargetsPanel />
            <DmxUsbPanel />
            <OscPanel />
            <WebhookPanel />
            {/* N2: Bundle backup */}
            <BundlePanel />
          </>
        )}
      </div>

      {adding && <AddFixtureModal profiles={profiles} onClose={() => setAdding(false)}
        onAdded={() => { setAdding(false); refreshFixtures(); }} />}
      {gdtfBrowser && <GdtfBrowserModal onClose={() => setGdtfBrowser(false)}
        onAdded={() => { setGdtfBrowser(false); refreshFixtures(); }} />}

      {/* Toast notification */}
      {toast && (
        <div style={{
          position: "fixed", bottom: 20, right: 20, background: "var(--bg-2)",
          color: "var(--txt)", padding: "10px 14px", borderRadius: 6,
          fontSize: 12, boxShadow: "0 4px 12px rgba(0,0,0,0.3)", zIndex: 1000,
        }}>
          {toast}
        </div>
      )}
    </div>
  );
}
