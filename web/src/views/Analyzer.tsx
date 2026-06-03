import { useEffect, useRef, useState } from "react";
import { control } from "../api/control";
import { useStore } from "../store";
import { Ico, fmtTime, fmtTimeMs } from "../icons";
import { ContextMenu, MenuState } from "../components/ContextMenu";

const SECTION_TYPES = ["", "intro", "verse", "build", "buildup", "drop", "chorus", "break", "breakdown", "bridge", "outro", "silence"];

type AzData = { peaks: number[]; beats: number[]; downbeats: number[]; kicks: number[]; snares: number[] };
const EMPTY: AzData = { peaks: [], beats: [], downbeats: [], kicks: [], snares: [] };

const OV = [
  { key: "downbeat", label: "downbeat", color: "var(--acc)" },
  { key: "beat", label: "beat", color: "var(--txt-2)" },
  { key: "kick", label: "kick", color: "var(--fam-flash)" },
  { key: "snare", label: "snare", color: "var(--fam-color)" },
];

function secColor(type: string): string {
  const m: Record<string, string> = {
    intro: "var(--txt-3)", verse: "var(--fam-wave)", build: "var(--fam-color)",
    buildup: "var(--fam-color)", drop: "var(--fam-flash)", chorus: "var(--fam-flash)",
    break: "var(--fam-gradient)", breakdown: "var(--fam-gradient)", outro: "var(--txt-3)",
  };
  return m[type] || "var(--txt-3)";
}

function Wave({ data, overlays, onContext }: { data: AzData; overlays: Record<string, boolean>; onContext: (timeSec: number, x: number, y: number) => void }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const t = useStore((s) => s.t);
  const duration = useStore((s) => s.duration) || 1;
  const sections = useStore((s) => s.sections);

  useEffect(() => {
    const cv = ref.current; if (!cv) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = cv.clientWidth, h = cv.clientHeight;
    if (cv.width !== w * dpr) { cv.width = w * dpr; cv.height = h * dpr; }
    const ctx = cv.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const X = (sec: number) => (sec / duration) * w;

    sections.forEach((s, i) => {
      const next = sections[i + 1]?.start ?? duration;
      if (i % 2) { ctx.fillStyle = "rgba(255,255,255,0.02)"; ctx.fillRect(X(s.start), 0, X(next) - X(s.start), h); }
    });

    const peaks = data.peaks, N = peaks.length || 1, mid = h * 0.52, playedX = X(t);
    for (let i = 0; i < peaks.length; i++) {
      const x = (i / N) * w, a = peaks[i];
      ctx.fillStyle = x <= playedX ? "rgba(120,230,180,0.85)" : "rgba(150,160,180,0.5)";
      ctx.fillRect(x, mid - a * mid * 0.92, Math.max(0.8, w / N - 0.3), a * mid * 0.92 * 2);
    }

    if (overlays.beat) { ctx.strokeStyle = "rgba(180,190,210,0.16)"; ctx.lineWidth = 1; data.beats.forEach((x) => { ctx.beginPath(); ctx.moveTo(X(x), h * 0.1); ctx.lineTo(X(x), h); ctx.stroke(); }); }
    if (overlays.downbeat) { ctx.strokeStyle = "rgba(0,224,138,0.5)"; ctx.lineWidth = 1.4; data.downbeats.forEach((x) => { ctx.beginPath(); ctx.moveTo(X(x), 0); ctx.lineTo(X(x), h); ctx.stroke(); }); }
    if (overlays.kick) { ctx.fillStyle = "rgba(240,120,90,0.9)"; data.kicks.forEach((x) => { ctx.beginPath(); ctx.arc(X(x), h - 10, 3, 0, 7); ctx.fill(); }); }
    if (overlays.snare) { ctx.fillStyle = "rgba(230,190,90,0.9)"; data.snares.forEach((x) => { ctx.beginPath(); ctx.arc(X(x), 12, 3, 0, 7); ctx.fill(); }); }

    const px = X(t);
    ctx.strokeStyle = "#00e08a"; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, h); ctx.stroke();
    ctx.fillStyle = "#00e08a"; ctx.beginPath(); ctx.moveTo(px - 5, 0); ctx.lineTo(px + 5, 0); ctx.lineTo(px, 7); ctx.fill();
  }, [t, overlays, data, sections, duration]);

  const onClick = (e: React.MouseEvent) => {
    const r = ref.current!.getBoundingClientRect();
    control.call("seek", { t_sec: ((e.clientX - r.left) / r.width) * duration });
  };
  const onCtx = (e: React.MouseEvent) => {
    e.preventDefault();
    const r = ref.current!.getBoundingClientRect();
    onContext(((e.clientX - r.left) / r.width) * duration, e.clientX, e.clientY);
  };
  return <canvas ref={ref} onClick={onClick} onContextMenu={onCtx} style={{ cursor: "text" }} />;
}

export function AnalyzerView() {
  const t = useStore((s) => s.t);
  const bpm = useStore((s) => s.song.bpm);
  const sections = useStore((s) => s.sections);
  const refreshSections = useStore((s) => s.refreshSections);
  const [data, setData] = useState<AzData>(EMPTY);
  const [overlays, setOverlays] = useState<Record<string, boolean>>({ beat: true, downbeat: true, kick: true, snare: true });
  const [side, setSide] = useState<"sections" | "events" | "thr">("sections");
  const [thr, setThr] = useState<Record<string, number>>({ kick: 50, snare: 45, hat: 35, onset: 55 });
  const [menu, setMenu] = useState<MenuState>(null);

  const loadEvents = async () => {
    const [pk, be, db, ki, sn] = await Promise.all([
      control.call("analyzer_waveform_peaks", { buckets: 1100 }).catch(() => ({ peaks: [] })),
      control.call("analyzer_list_beats").catch(() => ({ beats: [] })),
      control.call("analyzer_list_downbeats").catch(() => ({ downbeats: [] })),
      control.call("analyzer_list_events", { kind: "kick" }).catch(() => ({ events: [] })),
      control.call("analyzer_list_events", { kind: "snare" }).catch(() => ({ events: [] })),
    ]);
    const evTimes = (r: any) => (r.events || []).map((e: any) => e.time_sec ?? e.time ?? e.start);
    setData({
      peaks: pk.peaks || [], beats: be.beats || [], downbeats: db.downbeats || [],
      kicks: evTimes(ki), snares: evTimes(sn),
    });
  };
  useEffect(() => { loadEvents(); }, []);

  const setSectionLabel = (idx: number, name: string, type: string) =>
    control.call("analyzer_set_section_label", { idx, name, type }).then(refreshSections);

  const waveCtx = (timeSec: number, x: number, y: number) => {
    setMenu({ x, y, items: [
      { label: `+ Kick manual aquí (${fmtTime(timeSec)})`, onClick: () => control.call("analyzer_add_manual_event", { time_sec: timeSec, kind: "kick" }).then(loadEvents) },
      { label: `+ Snare manual aquí`, onClick: () => control.call("analyzer_add_manual_event", { time_sec: timeSec, kind: "snare" }).then(loadEvents) },
      { type: "sep" },
      { label: "Deshabilitar kick cercano", onClick: () => control.call("analyzer_disable_event", { time_sec: timeSec, kind: "kick", tolerance_ms: 120 }).then(loadEvents) },
      { label: "Deshabilitar snare cercano", onClick: () => control.call("analyzer_disable_event", { time_sec: timeSec, kind: "snare", tolerance_ms: 120 }).then(loadEvents) },
    ] });
  };

  const counts: Record<string, number> = {
    downbeat: data.downbeats.length, beat: data.beats.length,
    kick: data.kicks.length, snare: data.snares.length,
  };

  const saveThr = async () => {
    for (const [k, v] of Object.entries(thr)) {
      await control.call("analyzer_set_event_threshold", { kind: k, value: v / 100 }).catch(() => {});
    }
  };

  return (
    <div className="az">
      <div className="az-main">
        <div className="az-wavewrap">
          <div className="az-overlay-toggles">
            {OV.map((ev) => (
              <button key={ev.key} className={"ov-tog" + (overlays[ev.key] ? " on" : "")}
                onClick={() => setOverlays((o) => ({ ...o, [ev.key]: !o[ev.key] }))}>
                <span className="d" style={{ background: ev.color }} />{ev.label}<span className="c">{counts[ev.key] ?? 0}</span>
              </button>
            ))}
          </div>
          <div className="az-wave"><Wave data={data} overlays={overlays} onContext={waveCtx} /></div>
          <div style={{ display: "flex", alignItems: "center", gap: 14, fontSize: 11.5, color: "var(--txt-3)" }}>
            <span className="chip acc"><span className="d" />Beat grid: {Math.round(bpm)} BPM</span>
            <span className="muted">Click en la onda para mover el playhead</span>
            <span className="ph-spacer" style={{ flex: 1 }} />
            <span className="mono muted">{fmtTimeMs(t)}</span>
          </div>
        </div>

        <div className="az-side">
          <div className="az-tabs">
            <button className={"az-tab" + (side === "sections" ? " on" : "")} onClick={() => setSide("sections")}>Secciones</button>
            <button className={"az-tab" + (side === "events" ? " on" : "")} onClick={() => setSide("events")}>Eventos</button>
            <button className={"az-tab" + (side === "thr" ? " on" : "")} onClick={() => setSide("thr")}>Umbrales</button>
          </div>

          {side === "sections" && (
            <div className="panel-body">
              <table className="tbl">
                <thead><tr><th>Inicio</th><th>Nombre</th><th>Tipo</th></tr></thead>
                <tbody>
                  {sections.map((s, i) => (
                    <tr key={i}>
                      <td className="mono" onClick={() => control.call("seek", { t_sec: s.start })} style={{ cursor: "pointer" }}>{fmtTime(s.start)}</td>
                      <td><input className="field" style={{ width: "100%", height: 24, padding: "0 6px" }} defaultValue={s.name} key={"sn" + i + s.name}
                        onBlur={(e) => setSectionLabel(s.idx ?? i, e.target.value, s.type)} /></td>
                      <td><select className="field" style={{ height: 24, padding: "0 4px" }} value={s.type}
                        onChange={(e) => setSectionLabel(s.idx ?? i, s.name, e.target.value)}>
                        {SECTION_TYPES.map((ty) => <option key={ty} value={ty}>{ty || "—"}</option>)}
                      </select></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {side === "events" && (
            <div className="panel-body">
              <table className="tbl">
                <thead><tr><th>Tipo</th><th>Cuenta</th><th>Estado</th></tr></thead>
                <tbody>
                  {OV.map((ev) => (
                    <tr key={ev.key}>
                      <td style={{ color: "var(--txt)", fontWeight: 600 }}><span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: ev.color, marginRight: 8 }} />{ev.label}</td>
                      <td className="mono">{counts[ev.key] ?? 0}</td>
                      <td><span className="chip" style={overlays[ev.key] ? { background: "var(--acc-dim)", color: "var(--acc)" } : undefined}>{overlays[ev.key] ? "activo" : "oculto"}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {side === "thr" && (
            <div className="panel-body" style={{ paddingTop: 6 }}>
              {Object.entries(thr).map(([k, v]) => (
                <div key={k} className="slider-row">
                  <span className="lab">{k}</span>
                  <input className="rng" type="range" min="0" max="100" value={v}
                    onChange={(e) => setThr((s) => ({ ...s, [k]: +e.target.value }))} />
                  <span className="val">{v}%</span>
                </div>
              ))}
              <div style={{ padding: 12 }}>
                <button className="btn primary" style={{ width: "100%" }} onClick={saveThr}><Ico.save width="14" /> Guardar curación</button>
                <p className="muted" style={{ fontSize: 11, marginTop: 10, lineHeight: 1.5 }}>Los umbrales se guardan en la curación del análisis (no pisa el análisis crudo).</p>
              </div>
            </div>
          )}
        </div>
      </div>
      <ContextMenu state={menu} onClose={() => setMenu(null)} />
    </div>
  );
}
