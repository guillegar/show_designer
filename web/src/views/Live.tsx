import { useEffect, useRef, useState, useCallback } from "react";
import { control } from "../api/control";
import { stream, LEDS } from "../api/stream";
import type { AutosaveAvailableEvent } from "../api/stream";
import { useStore } from "../store";
import { Ico, fmtTime } from "../icons";
import type { TrackChain, MixerState, LiveSlot, LiveState, MacrosState } from "../api/types";

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

// ── C2: Macro Strip ──────────────────────────────────────────────────────────

const MACRO_DEFAULTS: MacrosState = {
  brightness_mul: 1.0,
  speed_mul: 1.0,
  hue_shift: 0.0,
  strobe_rate: 0.0,
};

type MacroDef = {
  key: keyof MacrosState;
  label: string;
  icon: string;
  min: number;
  max: number;
  step: number;
  center?: number;  // valor de "centro" visual (default = para doble-click reset)
};

const MACRO_DEFS: MacroDef[] = [
  { key: "brightness_mul", label: "Brightness ×", icon: "🔆", min: 0, max: 2, step: 0.01, center: 1.0 },
  { key: "speed_mul",      label: "Speed ×",       icon: "⚡", min: 0, max: 4, step: 0.02, center: 1.0 },
  { key: "hue_shift",      label: "Hue Shift",     icon: "🎨", min: -180, max: 180, step: 1, center: 0 },
  { key: "strobe_rate",    label: "Strobe Hz",      icon: "🔦", min: 0, max: 30, step: 0.5, center: 0 },
];

function MacroStrip() {
  const [macros, setMacros] = useState<MacrosState>({ ...MACRO_DEFAULTS });
  const lastSent = useRef<Record<string, number>>({});

  const sendMacro = useCallback((key: keyof MacrosState, value: number) => {
    const now = Date.now();
    if ((now - (lastSent.current[key] ?? 0)) >= SLIDER_THROTTLE_MS) {
      lastSent.current[key] = now;
      control.call("set_macro", { name: key, value }).catch(() => {});
    }
  }, []);

  const handleChange = (key: keyof MacrosState, value: number) => {
    setMacros((m) => ({ ...m, [key]: value }));
    sendMacro(key, value);
  };

  const handleDoubleClick = (def: MacroDef) => {
    const dflt = MACRO_DEFAULTS[def.key];
    setMacros((m) => ({ ...m, [def.key]: dflt }));
    control.call("set_macro", { name: def.key, value: dflt }).catch(() => {});
  };

  const fmtVal = (def: MacroDef, v: number) => {
    if (def.key === "hue_shift") return `${v > 0 ? "+" : ""}${v.toFixed(0)}°`;
    if (def.key === "strobe_rate") return v === 0 ? "OFF" : `${v.toFixed(1)} Hz`;
    return `×${v.toFixed(2)}`;
  };

  return (
    <div className="macro-strip">
      <div className="macro-strip-head">
        <span className="macro-strip-title">Macros en vivo</span>
        <button
          className="btn ghost"
          style={{ fontSize: 10 }}
          onClick={() => {
            setMacros({ ...MACRO_DEFAULTS });
            for (const def of MACRO_DEFS) {
              control.call("set_macro", { name: def.key, value: MACRO_DEFAULTS[def.key] }).catch(() => {});
            }
          }}
          title="Resetear todas las macros a su valor por defecto"
        >↺ Reset</button>
      </div>
      <div className="macro-strip-body">
        {MACRO_DEFS.map((def) => {
          const v = macros[def.key];
          const isDefault = v === MACRO_DEFAULTS[def.key];
          return (
            <div key={def.key} className={"macro-row" + (isDefault ? "" : " active")}>
              <div className="macro-label-row">
                <span className="macro-icon">{def.icon}</span>
                <span className="macro-label">{def.label}</span>
                <span className="macro-val">{fmtVal(def, v)}</span>
              </div>
              <input
                type="range"
                min={def.min} max={def.max} step={def.step}
                value={v}
                onChange={(e) => handleChange(def.key, parseFloat(e.target.value))}
                onDoubleClick={() => handleDoubleClick(def)}
                className="macro-slider"
                title={`${def.label} · doble clic para resetear`}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── C1: Performance Grid ─────────────────────────────────────────────────────

// Teclas por defecto: slots 0-7 = "1"-"8", slots 8-15 = "q"-"i"
const DEFAULT_KEYS = ["1","2","3","4","5","6","7","8","q","w","e","r","t","y","u","i"];
const QUANTIZE_LABELS: Record<string, string> = { bar: "BAR", beat: "BEAT", free: "FREE" };
const MODE_LABELS: Record<string, string> = { oneshot: "1×", loop: "↻", hold: "↓" };

function SlotConfigModal({ slot, patterns, onSave, onClose }: {
  slot: LiveSlot;
  patterns: { uid: string; name: string; color: string }[];
  onSave: (patch: Partial<LiveSlot>) => void;
  onClose: () => void;
}) {
  const [patUid, setPatUid] = useState(slot.pattern_uid ?? "");
  const [quantize, setQuantize] = useState<LiveSlot["quantize"]>(slot.quantize);
  const [mode, setMode] = useState<LiveSlot["mode"]>(slot.mode);
  const [key, setKey] = useState(slot.key);

  const save = () => {
    onSave({ pattern_uid: patUid || null, quantize, mode, key });
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box live-slot-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span>Configurar slot {slot.idx + 1}</span>
          <button className="btn ghost" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body" style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
          <label className="slot-cfg-row">
            <span>Pattern</span>
            <select value={patUid} onChange={(e) => setPatUid(e.target.value)}
              className="slot-cfg-select">
              <option value="">— vacío —</option>
              {patterns.map((p) => (
                <option key={p.uid} value={p.uid}>{p.name}</option>
              ))}
            </select>
          </label>
          <label className="slot-cfg-row">
            <span>Cuantización</span>
            <select value={quantize} onChange={(e) => setQuantize(e.target.value as LiveSlot["quantize"])}
              className="slot-cfg-select">
              <option value="bar">Bar (compás)</option>
              <option value="beat">Beat</option>
              <option value="free">Free (inmediato)</option>
            </select>
          </label>
          <label className="slot-cfg-row">
            <span>Modo</span>
            <select value={mode} onChange={(e) => setMode(e.target.value as LiveSlot["mode"])}
              className="slot-cfg-select">
              <option value="oneshot">Oneshot (una pasada)</option>
              <option value="loop">Loop (repite)</option>
              <option value="hold">Hold (mientras pulsado)</option>
            </select>
          </label>
          <label className="slot-cfg-row">
            <span>Tecla</span>
            <input type="text" maxLength={1} value={key}
              onChange={(e) => setKey(e.target.value.toLowerCase())}
              className="slot-cfg-key" placeholder={DEFAULT_KEYS[slot.idx]} />
          </label>
          <button className="btn primary" onClick={save} style={{ marginTop: 4 }}>
            Guardar
          </button>
        </div>
      </div>
    </div>
  );
}

function PerformanceGrid() {
  const patterns = useStore((s) => s.patterns);
  const [liveState, setLiveState] = useState<LiveState>({
    slots: [], active: [], armed: [],
  });
  const [configSlot, setConfigSlot] = useState<LiveSlot | null>(null);

  // Cargar estado inicial
  const loadState = useCallback(() => {
    control.call("get_live_state").then((r) => {
      if (r.ok) setLiveState({ slots: r.slots as LiveSlot[], active: r.active, armed: r.armed });
    }).catch(() => {});
  }, []);

  useEffect(() => { loadState(); }, [loadState]);

  // Suscribirse a cambios del stream
  useEffect(() => {
    return stream.onLiveStateChanged((e) => {
      setLiveState({ slots: e.slots as LiveSlot[], active: e.active, armed: e.armed });
    });
  }, []);

  // Keydown global: disparar slots por tecla
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.repeat) return;
      const k = e.key.toLowerCase();
      if (liveState.slots.length === 0) return;
      const slotIdx = liveState.slots.findIndex(
        (s) => (s.key || DEFAULT_KEYS[s.idx]) === k
      );
      if (slotIdx < 0) return;
      e.preventDefault();
      const slot = liveState.slots[slotIdx];
      if (slot.mode === "hold") {
        // hold: disparar en keydown, liberar en keyup
        control.call("live_trigger", { slot_idx: slotIdx }).catch(() => {});
        const onUp = (ue: KeyboardEvent) => {
          if (ue.key.toLowerCase() === k) {
            control.call("live_release", { slot_idx: slotIdx }).catch(() => {});
            window.removeEventListener("keyup", onUp);
          }
        };
        window.addEventListener("keyup", onUp);
      } else {
        control.call("live_trigger", { slot_idx: slotIdx }).catch(() => {});
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [liveState.slots]);

  const triggerSlot = (slot: LiveSlot) => {
    control.call("live_trigger", { slot_idx: slot.idx }).catch(() => {});
  };

  const releaseSlot = (slot: LiveSlot) => {
    control.call("live_release", { slot_idx: slot.idx }).catch(() => {});
  };

  const stopAll = () => {
    control.call("live_stop_all").catch(() => {});
  };

  const saveSlotConfig = (slot: LiveSlot, patch: Partial<LiveSlot>) => {
    control.call("live_assign_slot", {
      slot_idx: slot.idx,
      pattern_uid: patch.pattern_uid ?? null,
      key: patch.key ?? "",
      quantize: patch.quantize ?? "bar",
      mode: patch.mode ?? "oneshot",
    }).catch(() => {});
  };

  // Lookup del nombre de pattern para un slot
  const patternName = (uid: string | null) => {
    if (!uid) return "— vacío —";
    const p = patterns.find((x) => x.uid === uid);
    return p ? p.name : uid.slice(0, 8);
  };

  const patternColor = (uid: string | null): string => {
    if (!uid) return "var(--bg-2)";
    const p = patterns.find((x) => x.uid === uid);
    return p ? p.color : "#555";
  };

  return (
    <div className="perf-grid-wrap">
      <div className="perf-grid-header">
        <span className="perf-grid-title">Performance Grid</span>
        <span className="ph-spacer" style={{ flex: 1 }} />
        <button className="btn warn" onClick={stopAll} title="Detener todos los slots (pánico)">
          ⏹ STOP ALL
        </button>
      </div>

      <div className="perf-grid">
        {liveState.slots.map((slot) => {
          const hasPattern = !!slot.pattern_uid;
          const displayKey = slot.key || DEFAULT_KEYS[slot.idx] || "";
          const color = hasPattern ? patternColor(slot.pattern_uid) : undefined;
          const cls = [
            "perf-slot",
            slot.active ? "active" : "",
            slot.armed ? "armed" : "",
            !hasPattern ? "empty" : "",
          ].filter(Boolean).join(" ");

          return (
            <div key={slot.uid} className={cls}
              style={color ? { "--slot-color": color } as React.CSSProperties : undefined}
              onMouseDown={() => hasPattern && triggerSlot(slot)}
              onMouseUp={() => slot.mode === "hold" && releaseSlot(slot)}
            >
              {/* Barra de color del pattern */}
              {hasPattern && (
                <div className="perf-slot-bar" style={{ background: patternColor(slot.pattern_uid) }} />
              )}

              {/* Nombre del pattern */}
              <div className="perf-slot-name">
                {patternName(slot.pattern_uid)}
              </div>

              {/* Fila inferior: tecla, modo, cuantización */}
              <div className="perf-slot-meta">
                <span className="perf-slot-key">{displayKey.toUpperCase()}</span>
                <span className="perf-slot-mode">{MODE_LABELS[slot.mode]}</span>
                {slot.degraded ? (
                  <span className="perf-slot-badge free">FREE</span>
                ) : (
                  <span className="perf-slot-badge">{QUANTIZE_LABELS[slot.quantize]}</span>
                )}
              </div>

              {/* Botón de configuración */}
              <button
                className="perf-slot-cfg"
                onClick={(e) => { e.stopPropagation(); setConfigSlot(slot); }}
                title="Configurar slot"
              >⚙</button>

              {/* Indicador armado */}
              {slot.armed && <div className="perf-slot-armed-dot" />}
            </div>
          );
        })}
      </div>

      {/* Modal de configuración de slot */}
      {configSlot && (
        <SlotConfigModal
          slot={configSlot}
          patterns={patterns as { uid: string; name: string; color: string }[]}
          onSave={(patch) => saveSlotConfig(configSlot, patch)}
          onClose={() => setConfigSlot(null)}
        />
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
        {/* C2: Macros en vivo */}
        <MacroStrip />
        {/* C1: Performance Grid */}
        <PerformanceGrid />
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
