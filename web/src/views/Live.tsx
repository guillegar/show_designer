import { useEffect, useRef, useState } from "react";
import { control } from "../api/control";
import { stream, LEDS } from "../api/stream";
import { useStore } from "../store";
import { Ico, fmtTime } from "../icons";

const FEEDBACK_CATS = [
  { key: "intensity_ok", label: "Intensidad OK", pos: true },
  { key: "timing_ok", label: "Timing preciso", pos: true },
  { key: "color_ok", label: "Color apropiado", pos: true },
  { key: "effect_visible", label: "Efecto visible", pos: true },
  { key: "transition_smooth", label: "Transición suave", pos: true },
  { key: "sync_music", label: "Sincro con música", pos: true },
  { key: "emotional_impact", label: "Impacto emocional", pos: true },
  { key: "need_brightness", label: "Más brillo", pos: false },
  { key: "need_contrast", label: "Más contraste", pos: false },
  { key: "too_busy", label: "Demasiado recargado", pos: false },
];

// Canvas de una barra: lee el frame binario real del stream en su propio rAF.
function BarCanvas({ barIdx }: { barIdx: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let raf = 0;
    const draw = () => {
      const cv = ref.current;
      if (cv) {
        const dpr = Math.min(2, window.devicePixelRatio || 1);
        const w = cv.clientWidth, h = cv.clientHeight;
        if (cv.width !== w * dpr) { cv.width = w * dpr; cv.height = h * dpr; }
        const ctx = cv.getContext("2d")!;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);
        const lh = h / LEDS;
        for (let i = 0; i < LEDS; i++) {
          const [r, g, b] = stream.ledRGB(barIdx, i);
          const y = h - (i + 1) * lh; // led 0 abajo
          ctx.fillStyle = `rgb(${r},${g},${b})`;
          ctx.fillRect(0, y, w, lh + 0.6);
        }
        const grd = ctx.createLinearGradient(0, 0, w, 0);
        grd.addColorStop(0, "rgba(255,255,255,0.10)");
        grd.addColorStop(0.5, "rgba(255,255,255,0)");
        grd.addColorStop(1, "rgba(0,0,0,0.22)");
        ctx.fillStyle = grd;
        ctx.fillRect(0, 0, w, h);
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [barIdx]);
  return <canvas ref={ref} className="bar-canvas" />;
}

function barAvg(barIdx: number): string {
  let r = 0, g = 0, b = 0;
  for (let i = 0; i < LEDS; i++) { const c = stream.ledRGB(barIdx, i); r += c[0]; g += c[1]; b += c[2]; }
  return `rgb(${Math.round(r / LEDS)},${Math.round(g / LEDS)},${Math.round(b / LEDS)})`;
}

export function LiveView() {
  const t = useStore((s) => s.t);
  const section = useStore((s) => s.section);
  const clips = useStore((s) => s.clips);
  const fixtures = useStore((s) => s.fixtures);

  const [fb, setFb] = useState<Record<string, boolean>>({ timing_ok: true, color_ok: true });
  const [note, setNote] = useState("");
  const [showLeds, setShowLeds] = useState(true);
  const [log, setLog] = useState<any[]>([]);

  // barras LED ordenadas por legacy_bar_idx
  const bars = fixtures
    .filter((f) => f.legacy_bar_idx != null)
    .sort((a, b) => (a.legacy_bar_idx! - b.legacy_bar_idx!));

  const loadLog = () => control.call("list_feedback").then((r) => setLog(r.entries || [])).catch(() => {});
  useEffect(() => { loadLog(); }, []);

  const t_ms = t * 1000;
  const activeCount = clips.filter((c) => t_ms >= c.start_ms && t_ms < c.end_ms).length;

  const markFeedback = async () => {
    await control.call("add_feedback", { t, section, text: note, cats: fb, pos: true });
    setNote("");
    loadLog();
  };

  return (
    <div className="live">
      <div className="live-stage">
        <div className="live-toolbar">
          <span className="live-title">Preview en vivo</span>
          <span className="chip acc"><span className="d" />{activeCount} efectos activos</span>
          <span className="ph-spacer" style={{ flex: 1 }} />
          <div className="seg">
            <button className={showLeds ? "on" : ""} onClick={() => setShowLeds(true)}>LEDs</button>
            <button className={!showLeds ? "on" : ""} onClick={() => setShowLeds(false)}>Sólido</button>
          </div>
          <span className="io-chip"><span className="led on" />192.168.1.201–210</span>
        </div>

        <div className="live-canvaswrap">
          <div className="stage-room">
            <div className="bars-row">
              {bars.map((b, i) => (
                <div key={b.fixture_id} className="bar-col">
                  <BarCanvas barIdx={b.legacy_bar_idx!} />
                  <span className="bar-label">{b.legacy_bar_idx}</span>
                  <div className="bar-glow" style={{ background: barAvg(b.legacy_bar_idx!), left: `${i * 10}%`, width: "10%" }} />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="live-side">
        <div className="panel-head"><h3>Feedback</h3><span className="ph-spacer" /><span className="chip mono">{fmtTime(t)}</span></div>

        <div className="fb-cats">
          {FEEDBACK_CATS.map((c) => (
            <button key={c.key}
              className={"fb-cat" + (fb[c.key] ? " on" : "") + (c.pos ? "" : " neg")}
              onClick={() => setFb((f) => ({ ...f, [c.key]: !f[c.key] }))}>
              <span className="box">{fb[c.key] && <Ico.check />}</span>
              {c.label}
            </button>
          ))}
        </div>

        <div className="fb-note">
          <textarea placeholder={`Nota en ${fmtTime(t)} · ${section}…`} value={note}
            onChange={(e) => setNote(e.target.value)} />
        </div>

        <div style={{ display: "flex", gap: 8, padding: "0 10px 10px" }}>
          <button className="btn primary" style={{ flex: 1 }} onClick={markFeedback}>+ Marcar feedback aquí</button>
          <button className="btn ghost" onClick={() => control.call("save_show")}><Ico.save width="14" /></button>
        </div>

        <div className="panel-head" style={{ borderTop: "1px solid var(--line-soft)" }}><h3>Historial</h3><span className="ph-spacer" /><span className="chip">{log.length}</span></div>
        <div className="fb-log">
          {log.map((e, i) => (
            <div key={i} className="fb-entry">
              <div className="er">
                <span className="et" onClick={() => control.call("seek", { t_sec: e.t })}>▸ {fmtTime(e.t)}</span>
                <span className="es">{e.section}</span>
                <span className="pin" style={{ background: e.pos ? "var(--ok)" : "var(--warn)" }} />
              </div>
              <div className="etx">{e.text}</div>
            </div>
          ))}
        </div>

        <div style={{ padding: 10, borderTop: "1px solid var(--line-soft)" }}>
          <div className="scope-row">
            <div className="scope-stat"><div className="k">Frames Art-Net</div><div className="v">{Math.floor(t * 30).toLocaleString()}</div></div>
            <div className="scope-stat"><div className="k">Universos</div><div className="v">{new Set(fixtures.map((f) => f.universe)).size}</div></div>
            <div className="scope-stat"><div className="k">LEDs</div><div className="v">{bars.length * LEDS}</div></div>
          </div>
        </div>
      </div>
    </div>
  );
}
