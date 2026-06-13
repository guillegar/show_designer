import { useEffect, useRef, useState, useCallback } from "react";
import { control } from "../api/control";
import { stream, LEDS } from "../api/stream";
import type { AutosaveAvailableEvent } from "../api/stream";
import { useStore } from "../store";
import { Ico, fmtTime } from "../icons";
import type { TrackChain, MixerState } from "../api/types";

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

const NUM_TRACKS = 10;
// Throttle sliders a ~20 req/s: sólo enviar si pasaron >=50 ms desde el último envío
const SLIDER_THROTTLE_MS = 50;

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

// ── Panel Mixer ──────────────────────────────────────────────────────────────

function MixerPanel() {
  const [expanded, setExpanded] = useState(true);
  const [mixer, setMixer] = useState<MixerState>({ tracks: {}, master: {} });
  const [muted, setMuted] = useState<number[]>([]);
  const [solo, setSolo] = useState<number[]>([]);

  // Último timestamp de envío por clave (throttle ~20 req/s)
  const lastSent = useRef<Record<string, number>>({});

  const loadMixer = useCallback(() => {
    control.call("get_mixer").then((r) => {
      if (r.ok) setMixer(r.mixer as MixerState);
    }).catch(() => {});
    control.call("get_tracks_state").then((r) => {
      setMuted(r.muted ?? []);
      setSolo(r.solo ?? []);
    }).catch(() => {});
  }, []);

  useEffect(() => { loadMixer(); }, [loadMixer]);

  const sendThrottled = (key: string, fn: () => Promise<unknown>) => {
    const now = Date.now();
    if ((now - (lastSent.current[key] ?? 0)) >= SLIDER_THROTTLE_MS) {
      lastSent.current[key] = now;
      fn().catch(() => {});
    }
  };

  const setTrackBrightness = (track: number, value: number) => {
    const chain = { ...((mixer.tracks[track] as TrackChain) ?? {}), brightness: value };
    setMixer((m) => ({ ...m, tracks: { ...m.tracks, [track]: chain } }));
    sendThrottled(`t${track}`, () =>
      control.call("set_track_chain", { track, chain })
    );
  };

  const setMasterParam = (key: string, value: number) => {
    const masterNew = { ...(mixer.master ?? {}), [key]: value };
    setMixer((m) => ({ ...m, master: masterNew }));
    sendThrottled(`master_${key}`, () =>
      control.call("set_master", { master: masterNew })
    );
  };

  const toggleMute = (track: number) => {
    control.call("set_track_mute", { track }).then((r) => {
      setMuted(r.muted ?? []);
    }).catch(() => {});
  };

  const toggleSolo = (track: number) => {
    control.call("set_track_solo", { track }).then((r) => {
      setSolo(r.solo ?? []);
    }).catch(() => {});
  };

  const trackChain = (t: number): TrackChain =>
    (mixer.tracks[t] as TrackChain) ?? {};

  const masterFade = (mixer.master as any)?.blackout_fade ?? 1;
  const masterBrightness = (mixer.master as any)?.brightness ?? 1;

  return (
    <div className="mixer-panel">
      <div className="mixer-header" onClick={() => setExpanded((e) => !e)}>
        <span className="mixer-title">Mixer</span>
        <span className="ph-spacer" style={{ flex: 1 }} />
        <span className="mixer-toggle">{expanded ? "▾" : "▸"}</span>
      </div>

      {expanded && (
        <div className="mixer-body">
          {/* Pistas 0..9 */}
          <div className="mixer-tracks">
            {Array.from({ length: NUM_TRACKS }, (_, i) => (
              <div key={i} className={"mixer-track" + (muted.includes(i) ? " muted" : "") + (solo.includes(i) ? " solo" : "")}>
                <span className="mixer-track-num">{i}</span>
                <input
                  type="range" min="0" max="1" step="0.01"
                  value={(trackChain(i).brightness ?? 1)}
                  onChange={(e) => setTrackBrightness(i, parseFloat(e.target.value))}
                  className="mixer-slider"
                  title={`Pista ${i} · brightness`}
                />
                <button
                  className={"mixer-btn" + (muted.includes(i) ? " on warn" : "")}
                  onClick={() => toggleMute(i)}
                  title="Mute"
                >M</button>
                <button
                  className={"mixer-btn" + (solo.includes(i) ? " on acc" : "")}
                  onClick={() => toggleSolo(i)}
                  title="Solo"
                >S</button>
              </div>
            ))}
          </div>

          {/* Strip master */}
          <div className="mixer-master">
            <span className="mixer-master-label">Master</span>
            <div className="mixer-master-row">
              <span className="mixer-master-key">Brillo</span>
              <input
                type="range" min="0" max="1" step="0.01"
                value={masterBrightness}
                onChange={(e) => setMasterParam("brightness", parseFloat(e.target.value))}
                className="mixer-slider"
                title="Master brightness"
              />
              <span className="mixer-master-val">{Math.round(masterBrightness * 100)}%</span>
            </div>
            <div className="mixer-master-row">
              <span className="mixer-master-key">Blackout</span>
              <input
                type="range" min="0" max="1" step="0.01"
                value={masterFade}
                onChange={(e) => setMasterParam("blackout_fade", parseFloat(e.target.value))}
                className="mixer-slider blackout-slider"
                title="Blackout fade (0=negro, 1=libre)"
              />
              <span className="mixer-master-val">{Math.round(masterFade * 100)}%</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── B4: Banner de autosave disponible ────────────────────────────────────────

function AutosaveBanner({ event, onDone }: {
  event: AutosaveAvailableEvent;
  onDone: () => void;
}) {
  const restore = () => {
    if (!confirm(`¿Reemplazar el timeline actual con el autosave ${event.ts}?`)) return;
    control.call("restore_autosave", { filename: event.filename }).then((r) => {
      if (!r.ok) alert(r.error || "Error al restaurar");
      onDone();
    }).catch(() => onDone());
  };
  const discard = () => {
    control.call("discard_autosave_prompt").catch(() => {});
    onDone();
  };
  // Formatear timestamp legible: YYYYMMDDTHHMMSS → DD/MM/YYYY HH:MM:SS
  const ts = event.ts;
  const tsFormatted = ts.length >= 15
    ? `${ts.slice(6, 8)}/${ts.slice(4, 6)}/${ts.slice(0, 4)} ${ts.slice(9, 11)}:${ts.slice(11, 13)}:${ts.slice(13, 15)}`
    : ts;

  return (
    <div className="autosave-banner">
      <span className="autosave-banner-icon">⚠</span>
      <span className="autosave-banner-text">
        Hay un autosave más reciente que el show guardado (<b>{tsFormatted}</b>).
        ¿Quieres restaurarlo?
      </span>
      <button className="btn primary" onClick={restore}>Restaurar</button>
      <button className="btn ghost" onClick={discard}>Descartar</button>
    </div>
  );
}

// ── B4: Modal "Versiones…" ────────────────────────────────────────────────────

type AutosaveEntry = { filename: string; ts: string; size_kb: number };

function VersionesModal({ onClose }: { onClose: () => void }) {
  const [entries, setEntries] = useState<AutosaveEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    control.call("list_autosaves").then((r) => {
      if (r.ok) setEntries(r.autosaves as AutosaveEntry[]);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const loadCopy = (entry: AutosaveEntry) => {
    if (!confirm(`¿Reemplazar el timeline actual con el autosave ${entry.ts}?`)) return;
    control.call("restore_autosave", { filename: entry.filename }).then((r) => {
      if (r.ok) { onClose(); }
      else alert(r.error || "Error al cargar");
    }).catch(() => {});
  };

  const fmtTs = (ts: string) =>
    ts.length >= 15
      ? `${ts.slice(6, 8)}/${ts.slice(4, 6)}/${ts.slice(0, 4)} ${ts.slice(9, 11)}:${ts.slice(11, 13)}:${ts.slice(13, 15)}`
      : ts;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span>Versiones guardadas automáticamente</span>
          <button className="btn ghost" onClick={onClose}>✕</button>
        </div>
        {loading ? (
          <div className="modal-body" style={{ padding: 20, color: "var(--fg-dim)" }}>Cargando…</div>
        ) : entries.length === 0 ? (
          <div className="modal-body" style={{ padding: 20, color: "var(--fg-dim)" }}>No hay autosaves todavía.</div>
        ) : (
          <div className="modal-body">
            <table className="autosave-table">
              <thead>
                <tr><th>Fecha</th><th>Tamaño</th><th></th></tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.filename}>
                    <td>{fmtTs(e.ts)}</td>
                    <td>{e.size_kb} KB</td>
                    <td>
                      <button className="btn" style={{ fontSize: 11 }} onClick={() => loadCopy(e)}>
                        Cargar como copia
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Panel Render offline (B3) ────────────────────────────────────────────────

function RenderPanel() {
  const [status, setStatus] = useState<"idle" | "rendering" | "ready">("idle");
  const [pct, setPct] = useState(0);
  const [baked, setBaked] = useState(false);
  const [invalidated, setInvalidated] = useState(false);  // true cuando timeline cambió con baked activo
  const rev = useStore((s) => s.rev);

  // Detectar cambios del timeline mientras baked está activo
  useEffect(() => {
    if (baked) setInvalidated(true);
  }, [rev]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Cargar estado inicial
  const loadStatus = useCallback(() => {
    control.call("get_render_status").then((r) => {
      if (r.ok) setStatus(r.status as "idle" | "rendering" | "ready");
    }).catch(() => {});
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  // Suscribirse a eventos de progreso del stream
  useEffect(() => {
    return stream.onRenderProgress((e) => {
      setPct(Math.round(e.pct));
      if (e.done) {
        setStatus("ready");
        setPct(100);
      } else {
        setStatus("rendering");
      }
    });
  }, []);

  const startRender = () => {
    control.call("render_offline").then((r) => {
      if (r.ok) { setStatus("rendering"); setPct(0); }
      else alert(r.error || "Error al iniciar render");
    }).catch(() => {});
  };

  const toggleBaked = () => {
    if (baked) {
      control.call("toggle_baked", { enabled: false }).then((r) => {
        if (r.ok) { setBaked(false); setInvalidated(false); }
      }).catch(() => {});
    } else {
      control.call("toggle_baked", { enabled: true }).then((r) => {
        if (r.ok) { setBaked(true); setInvalidated(false); }
        else alert(r.error || "Sin render válido");
      }).catch(() => {});
    }
  };

  return (
    <div className="render-panel">
      <div className="render-header">
        <span className="render-title">Render offline</span>
        <span className="ph-spacer" style={{ flex: 1 }} />
        <button
          className={"btn" + (status === "rendering" ? " disabled" : "")}
          onClick={startRender}
          disabled={status === "rendering"}
          title="Bakear el timeline completo a frames (sin coste de CPU en directo)"
        >⬛ Render</button>
        <button
          className={"btn" + (baked ? " on acc" : "") + (status !== "ready" ? " disabled" : "")}
          onClick={toggleBaked}
          disabled={status !== "ready" && !baked}
          title="Activar/desactivar playback baked"
        >▶ Baked</button>
      </div>

      {status === "rendering" && (
        <div className="render-progress-wrap">
          <div className="render-progress-bar" style={{ width: `${pct}%` }} />
          <span className="render-progress-label">{pct}%</span>
        </div>
      )}

      {status === "ready" && (
        <div className="render-status ok">✓ Render listo</div>
      )}

      {invalidated && baked && (
        <div className="render-status warn">
          ⚠ Timeline modificado — render invalidado. Desactiva Baked o re-renderiza.
        </div>
      )}
    </div>
  );
}

// ── Vista principal ──────────────────────────────────────────────────────────

export function LiveView() {
  const t = useStore((s) => s.t);
  const section = useStore((s) => s.section);
  const clips = useStore((s) => s.clips);
  const fixtures = useStore((s) => s.fixtures);

  const [fb, setFb] = useState<Record<string, boolean>>({ timing_ok: true, color_ok: true });
  const [note, setNote] = useState("");
  const [showLeds, setShowLeds] = useState(true);
  const [log, setLog] = useState<any[]>([]);

  // B4: estado de autosave
  const [autosaveEvent, setAutosaveEvent] = useState<AutosaveAvailableEvent | null>(null);
  const [showVersiones, setShowVersiones] = useState(false);

  useEffect(() => {
    return stream.onAutosaveAvailable((e) => setAutosaveEvent(e));
  }, []);

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
      {/* B4: Banner de autosave (solo si hay uno más nuevo que show.json) */}
      {autosaveEvent && (
        <AutosaveBanner event={autosaveEvent} onDone={() => setAutosaveEvent(null)} />
      )}
      {/* B4: Modal de versiones */}
      {showVersiones && <VersionesModal onClose={() => setShowVersiones(false)} />}

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
        {/* B4: botón Versiones */}
        <div style={{ display: "flex", justifyContent: "flex-end", padding: "6px 10px 0" }}>
          <button className="btn ghost" style={{ fontSize: 11 }} onClick={() => setShowVersiones(true)}>
            🕐 Versiones…
          </button>
        </div>
        {/* Panel Render offline (B3) */}
        <RenderPanel />
        {/* Panel Mixer (B2) */}
        <MixerPanel />

        <div className="panel-head" style={{ borderTop: "1px solid var(--line-soft)" }}>
          <h3>Feedback</h3><span className="ph-spacer" /><span className="chip mono">{fmtTime(t)}</span>
        </div>

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
