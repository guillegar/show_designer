import { useEffect, useRef, useState } from "react";
import { control } from "../api/control";
import { stream, LEDS, DmxState } from "../api/stream";
import type { BlackoutChangedEvent } from "../api/stream";
import { useStore, Fixture } from "../store";

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

function PatchStage({ fixtures }: { fixtures: Fixture[] }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const sel = useStore((s) => s.selectedFixtureId);
  const selectFixture = useStore((s) => s.selectFixture);
  const refreshFixtures = useStore((s) => s.refreshFixtures);
  const L = useLayout(fixtures);
  const { nx, nz } = L;
  const [posOverride, setPosOverride] = useState<Record<string, number[]>>({});
  const dragRef = useRef<{ id: string; moved: boolean } | null>(null);

  const posOf = (f: Fixture) => posOverride[f.fixture_id] ?? f.position ?? [0, 1, 0];

  useEffect(() => {
    let raf = 0;
    const m = 60;
    const roundRect = (c: CanvasRenderingContext2D, x: number, y: number, ww: number, hh: number, r: number) => {
      c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + ww, y, x + ww, y + hh, r);
      c.arcTo(x + ww, y + hh, x, y + hh, r); c.arcTo(x, y + hh, x, y, r); c.arcTo(x, y, x + ww, y, r); c.closePath();
    };
    const draw = () => {
      const cv = ref.current;
      if (cv) {
        const dpr = Math.min(2, window.devicePixelRatio || 1);
        const w = cv.clientWidth, h = cv.clientHeight;
        if (cv.width !== w * dpr) { cv.width = w * dpr; cv.height = h * dpr; }
        const ctx = cv.getContext("2d")!;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);
        const step = 42;
        ctx.strokeStyle = "rgba(120,130,160,0.06)"; ctx.lineWidth = 1;
        for (let x = 0; x < w; x += step) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
        for (let y = 0; y < h; y += step) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
        ctx.strokeStyle = "rgba(110,120,160,0.35)"; ctx.lineWidth = 1.5;
        ctx.setLineDash([6, 5]); ctx.strokeRect(m, m, w - 2 * m, h - 2 * m); ctx.setLineDash([]);
        ctx.fillStyle = "rgba(150,160,190,0.4)"; ctx.font = "11px 'JetBrains Mono'";
        ctx.fillText("ESCENARIO", m + 8, m + 18);
        ctx.fillText("◇ PÚBLICO", w / 2 - 30, h - m + 24);

        for (const f of fixtures) {
          const p = posOf(f);
          const cx = m + nx(p[0] ?? 0) * (w - 2 * m);
          const cy = m + nz(p[2] ?? p[1] ?? 0) * (h - 2 * m);
          const [r, g, b] = fixtureColor(f);
          ctx.save(); ctx.translate(cx, cy); ctx.rotate(((f.rotation?.[1] ?? 0) * Math.PI) / 180);
          const grd = ctx.createRadialGradient(0, 0, 2, 0, 0, 46);
          grd.addColorStop(0, `rgba(${r},${g},${b},0.5)`); grd.addColorStop(1, `rgba(${r},${g},${b},0)`);
          ctx.fillStyle = grd; ctx.beginPath(); ctx.arc(0, 0, 46, 0, 7); ctx.fill();
          const bw = 10, bh = 46;
          ctx.fillStyle = "#0a0c10"; ctx.strokeStyle = sel === f.fixture_id ? "#a070ff" : "rgba(150,160,190,0.5)";
          ctx.lineWidth = sel === f.fixture_id ? 2.5 : 1.2;
          roundRect(ctx, -bw / 2, -bh / 2, bw, bh, 3); ctx.fill(); ctx.stroke();
          ctx.fillStyle = `rgb(${r},${g},${b})`; roundRect(ctx, -bw / 2 + 2.5, -bh / 2 + 3, bw - 5, bh - 6, 2); ctx.fill();
          ctx.restore();
          ctx.fillStyle = sel === f.fixture_id ? "#c9a8ff" : "rgba(170,180,200,0.7)";
          ctx.font = "600 10px 'Hanken Grotesk'"; ctx.textAlign = "center";
          ctx.fillText(f.label || f.fixture_id, cx, cy + bh / 2 + 15);
        }
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [fixtures, sel, nx, nz, posOverride]);

  const nearest = (mx: number, my: number, w: number, h: number) => {
    const m = 60; let best: Fixture | null = null, bd = 1e9;
    for (const f of fixtures) {
      const p = posOf(f);
      const cx = m + nx(p[0] ?? 0) * (w - 2 * m);
      const cy = m + nz(p[2] ?? p[1] ?? 0) * (h - 2 * m);
      const d = Math.hypot(mx - cx, my - cy);
      if (d < bd && d < 34) { bd = d; best = f; }
    }
    return best;
  };

  const onMouseDown = (e: React.MouseEvent) => {
    const cv = ref.current!, r = cv.getBoundingClientRect();
    const f = nearest(e.clientX - r.left, e.clientY - r.top, r.width, r.height);
    if (!f) return;
    selectFixture(f.fixture_id);
    dragRef.current = { id: f.fixture_id, moved: false };
  };
  useEffect(() => {
    const m = 60;
    const move = (e: MouseEvent) => {
      const d = dragRef.current; if (!d) return;
      const cv = ref.current!, r = cv.getBoundingClientRect();
      const w = r.width, h = r.height;
      const xnorm = Math.max(0, Math.min(1, (e.clientX - r.left - m) / (w - 2 * m)));
      const znorm = Math.max(0, Math.min(1, (e.clientY - r.top - m) / (h - 2 * m)));
      const x = L.minX + xnorm * (L.maxX - L.minX);
      const z = L.minZ + znorm * (L.maxZ - L.minZ);
      const f = fixtures.find((ff) => ff.fixture_id === d.id);
      const y = f?.position?.[1] ?? 1;
      d.moved = true;
      setPosOverride((o) => ({ ...o, [d.id]: [x, y, z] }));
    };
    const up = () => {
      const d = dragRef.current; dragRef.current = null;
      if (!d || !d.moved) return;
      const pos = posOverride[d.id];
      if (pos) control.call("move_fixture", { fixture_id: d.id, position: pos })
        .then(() => { refreshFixtures(); setPosOverride((o) => { const n = { ...o }; delete n[d.id]; return n; }); });
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
  }, [fixtures, posOverride, L.minX, L.maxX, L.minZ, L.maxZ, refreshFixtures]);

  return <canvas ref={ref} onMouseDown={onMouseDown} style={{ cursor: "grab" }} />;
}

function AddFixtureModal({ profiles, onClose, onAdded }: {
  profiles: any[]; onClose: () => void; onAdded: () => void;
}) {
  const [profileId, setProfileId] = useState(profiles[0]?.profile_id ?? "");
  const [name, setName] = useState("");
  const [universe, setUniverse] = useState(11);
  const [dmxStart, setDmxStart] = useState(1);
  const create = async () => {
    const fid = (name || profileId || "fixture").toLowerCase().replace(/[^a-z0-9]+/g, "_") + "_" + Date.now().toString().slice(-4);
    await control.call("add_fixture", {
      fixture_id: fid, profile_id: profileId, universe, dmx_start: dmxStart,
      position: [0, 1, 0], label: name || fid,
    });
    onAdded();
  };
  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="preset-editor">
        <div className="ci-head"><h4>Añadir fixture</h4><button className="x" onClick={onClose}>×</button></div>
        <div className="ci-body">
          <div className="ci-row"><label>Perfil</label>
            <select value={profileId} onChange={(e) => setProfileId(e.target.value)}>
              {profiles.map((p) => <option key={p.profile_id} value={p.profile_id}>{p.name} ({p.kind}, {p.num_channels}ch)</option>)}
            </select></div>
          <div className="ci-row"><label>Nombre</label><input value={name} onChange={(e) => setName(e.target.value)} placeholder="(auto)" /></div>
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
    control.call("identify_fixture", { fixture_id: f.fixture_id, duration_ms: 2000 })
      .catch(() => {});
    setTimeout(() => setIdentifying(null), 2100);
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

      {/* Color picker para test */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 11, color: "var(--txt-3)" }}>Color test:</span>
        <input
          type="color"
          value={testColor}
          onChange={(e) => setTestColor(e.target.value)}
          style={{ width: 30, height: 22, border: "none", cursor: "pointer", background: "none" }}
        />
        <span className="mono" style={{ fontSize: 10, color: "var(--txt-3)" }}>{testColor.toUpperCase()}</span>
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
                title="Identificar: enciende a blanco 2 s"
              >🔦</button>
              <button
                className={"btn sm ghost" + (isTestActive ? " on acc" : "")}
                style={{ fontSize: 10, padding: "1px 6px" }}
                onClick={() => universe != null && testUniverse(universe)}
                disabled={universe == null}
                title={isTestActive ? "Desactivar test" : "Test universo con color seleccionado"}
              >🎨</button>
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

export function PatchView() {
  const fixtures = useStore((s) => s.fixtures);
  const sel = useStore((s) => s.selectedFixtureId);
  const selectFixture = useStore((s) => s.selectFixture);
  const refreshFixtures = useStore((s) => s.refreshFixtures);

  const [dmx, setDmx] = useState<DmxState>({});
  const [profiles, setProfiles] = useState<any[]>([]);
  const [adding, setAdding] = useState(false);
  const [edit, setEdit] = useState<Record<string, number>>({});

  useEffect(() => { const off = stream.onDmx((d) => setDmx(d)); return off; }, []);
  useEffect(() => { control.call("list_fixture_profiles").then((r) => setProfiles(r.profiles || [])).catch(() => {}); }, []);

  const selFx = fixtures.find((f) => f.fixture_id === sel) || fixtures[0];
  useEffect(() => { setEdit({}); }, [sel]);

  const setProp = (key: string, value: any) =>
    control.call("set_fixture_property", { fixture_id: selFx.fixture_id, key, value }).then(refreshFixtures);
  const del = () =>
    control.call("delete_fixture", { fixture_id: selFx.fixture_id }).then(() => { selectFixture(null); refreshFixtures(); });

  const isMover = selFx && selFx.legacy_bar_idx == null;
  const chans = isMover && selFx ? Object.keys(dmx[selFx.fixture_id] || {}) : [];
  const chVal = (ch: string) => edit[ch] ?? (dmx[selFx.fixture_id]?.[ch] ?? 0);
  const setCh = (ch: string, v01: number) => {
    setEdit((e) => ({ ...e, [ch]: v01 }));
    control.call("set_fixture_channel", { fixture_id: selFx.fixture_id, channel_name: ch, value: v01 });
  };
  const clearOverrides = () => {
    for (const ch of Object.keys(edit)) control.call("set_fixture_channel", { fixture_id: selFx.fixture_id, channel_name: ch, value: null });
    setEdit({});
  };

  return (
    <div className="patch">
      <div className="patch-stage">
        <div className="patch-toolbar">
          <button className="btn sm" onClick={() => setAdding(true)}>+ Fixture</button>
        </div>
        <PatchStage fixtures={fixtures} />
        <div className="patch-legend">
          <div className="lg"><i style={{ border: "2px solid var(--acc-2)", background: "none" }} />Seleccionada · arrastra para mover</div>
        </div>
      </div>

      <div className="patch-side">
        <div className="panel-head"><h3>Fixtures</h3><span className="ph-spacer" /><span className="chip">{fixtures.length}</span></div>
        <div style={{ flex: "0 0 auto", maxHeight: "38%", overflow: "auto" }}>
          {fixtures.map((f) => {
            const [r, g, b] = fixtureColor(f);
            return (
              <div key={f.fixture_id} className={"fix-item" + (sel === f.fixture_id ? " sel" : "")} onClick={() => selectFixture(f.fixture_id)}>
                <span className="sw" style={{ background: `rgb(${r},${g},${b})` }} />
                <div className="fi-txt">
                  <div className="fi-name">{f.label || f.fixture_id}</div>
                  <div className="fi-meta">{f.target_ip || f.profile_id} · U{f.universe}</div>
                </div>
                <span className="fi-leds">{f.legacy_bar_idx != null ? `${LEDS} px` : f.profile_id}</span>
              </div>
            );
          })}
        </div>

        {selFx && (
          <div className="panel-body" style={{ flex: 1, overflow: "auto" }}>
            <div className="panel-head" style={{ borderTop: "1px solid var(--line)" }}><h3>Propiedades · {selFx.label || selFx.fixture_id}</h3></div>
            <div className="form-row"><span className="fl">Nombre</span><div className="fv">
              <input className="field" defaultValue={selFx.label} style={{ width: 120 }} key={"n" + selFx.fixture_id}
                onBlur={(e) => setProp("label", e.target.value)} /></div></div>
            <div className="form-row"><span className="fl">IP / Host</span><div className="fv">
              <input className="field" defaultValue={selFx.target_ip || ""} style={{ width: 130 }} key={"ip" + selFx.fixture_id}
                onBlur={(e) => setProp("target_ip", e.target.value)} /></div></div>
            <div className="form-row"><span className="fl">Universo</span><div className="fv">
              <input className="field" type="number" defaultValue={selFx.universe} style={{ width: 60 }} key={"u" + selFx.fixture_id}
                onBlur={(e) => setProp("universe", +e.target.value)} /></div></div>
            <div className="form-row"><span className="fl">DMX start</span><div className="fv">
              <input className="field" type="number" defaultValue={selFx.dmx_start} style={{ width: 60 }} key={"d" + selFx.fixture_id}
                onBlur={(e) => setProp("dmx_start", +e.target.value)} /></div></div>
            <div className="form-row"><span className="fl">Perfil</span><div className="fv">
              <span className="mono" style={{ color: "var(--txt-3)", fontSize: 11 }}>{selFx.profile_id}</span></div></div>

            {isMover && chans.length > 0 && (
              <>
                <div className="ci-sub" style={{ padding: "8px 14px 2px" }}>Canales DMX (override manual)</div>
                {chans.map((ch) => (
                  <div className="slider-row" key={ch}>
                    <span className="lab">{ch}</span>
                    <input className="rng" type="range" min={0} max={255} value={Math.round(chVal(ch) * 255)}
                      onChange={(e) => setCh(ch, +e.target.value / 255)} />
                    <span className="val">{Math.round(chVal(ch) * 255)}</span>
                  </div>
                ))}
                <div style={{ padding: "4px 14px" }}>
                  <button className="btn sm ghost" disabled={Object.keys(edit).length === 0} onClick={clearOverrides}>⊘ Limpiar overrides</button>
                </div>
              </>
            )}

            <div style={{ padding: 12, display: "flex", gap: 8 }}>
              <button className="btn ghost" style={{ color: "var(--bad)" }} onClick={del}>Borrar fixture</button>
            </div>
          </div>
        )}
        <FixtureTestPanel fixtures={fixtures} />
        <DmxUsbPanel />
        <OscPanel />
      </div>

      {adding && <AddFixtureModal profiles={profiles} onClose={() => setAdding(false)}
        onAdded={() => { setAdding(false); refreshFixtures(); }} />}
    </div>
  );
}
