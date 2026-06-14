import { useMemo, useState, useEffect } from "react";
import { control } from "../api/control";
import { useStore, famColor, EffectInfo, Preset, ChannelEffectInfo } from "../store";
import type { Pattern } from "../api/types";
import { ContextMenu, MenuState } from "./ContextMenu";

type EditState = { create: boolean; preset: Partial<Preset> } | null;

export function Browser({
  activeFxId, activePresetId, onPickEffect, onPickPreset, onPickPattern,
}: {
  activeFxId: number | null;
  activePresetId: string | null;
  onPickEffect: (e: EffectInfo) => void;
  onPickPreset: (p: Preset) => void;
  onPickPattern?: (p: Pattern) => void;
}) {
  const effects = useStore((s) => s.effects);
  const channelEffects = useStore((s) => s.channelEffects);
  const presets = useStore((s) => s.presets);
  const patterns = useStore((s) => s.patterns);
  const patternInstances = useStore((s) => s.patternInstances);
  const refreshPresets = useStore((s) => s.refreshPresets);
  const refreshPatterns = useStore((s) => s.refreshPatterns);
  const refreshPatternInstances = useStore((s) => s.refreshPatternInstances);
  const t = useStore((s) => s.t);

  const [tab, setTab] = useState<"bank" | "base" | "patterns" | "marketplace">("bank");
  const [fam, setFam] = useState<string>("");
  const [menu, setMenu] = useState<MenuState>(null);
  const [edit, setEdit] = useState<EditState>(null);

  const families = useMemo(() => {
    const m = new Map<string, EffectInfo[]>();
    for (const e of effects) { if (!m.has(e.family)) m.set(e.family, []); m.get(e.family)!.push(e); }
    return [...m.entries()];
  }, [effects]);
  const effectById = useMemo(() => new Map(effects.map((e) => [e.id, e])), [effects]);

  // presets agrupados por familia/categoría, separando píxel y canal (movers)
  const groupBy = (arr: Preset[]) => {
    const m = new Map<string, Preset[]>();
    for (const p of arr) { const f = p.family || p.category || "otros"; if (!m.has(f)) m.set(f, []); m.get(f)!.push(p); }
    return [...m.entries()];
  };
  const pixelGroups = useMemo(() => groupBy(presets.filter((p) => p.kind !== "channel")), [presets]);
  const channelGroups = useMemo(() => groupBy(presets.filter((p) => p.kind === "channel")), [presets]);

  const openPreset = (create: boolean, p?: Preset) => {
    if (create) {
      const base = effects[0];
      setEdit({ create: true, preset: { name: "Nuevo preset", kind: "pixel", base_effect_id: base?.id ?? 0, channel_effect_id: null, category: "", family: base?.family ?? "", params: {}, color: "#3a7acc", scope: "project" } });
    } else if (p) {
      setEdit({ create: false, preset: { ...p, params: { ...p.params } } });
    }
  };

  const dupPreset = (p: Preset) =>
    control.call("create_preset", { name: p.name + " copia", kind: p.kind, base_effect_id: p.base_effect_id, channel_effect_id: p.channel_effect_id, params: p.params, color: p.color, scope: p.scope }).then(refreshPresets);

  const presetMenu = (e: React.MouseEvent, p: Preset) => {
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY, items: [
      { label: "Editar…", onClick: () => openPreset(false, p) },
      { label: "Duplicar", onClick: () => dupPreset(p) },
      { type: "sep" },
      { label: "Borrar", danger: true, onClick: () => control.call("delete_preset", { preset_id: p.preset_id }).then(refreshPresets) },
    ] });
  };

  const setDragData = (e: React.DragEvent, type: string, id: string | number) => {
    e.dataTransfer.effectAllowed = "copy";
    e.dataTransfer.setData("application/sd-drop", JSON.stringify({ type, id }));
  };

  const renderPreset = (p: Preset) => (
    <button key={p.preset_id}
      draggable
      className={"fx-item preset-item" + (activePresetId === p.preset_id ? " on" : "")}
      onClick={() => onPickPreset(p)}
      onDoubleClick={() => openPreset(false, p)}
      onContextMenu={(e) => presetMenu(e, p)}
      onDragStart={(e) => setDragData(e, p.kind === "channel" ? "channel-preset" : "preset", p.preset_id)}>
      <span className="sw" style={{ background: p.color }} />
      <span className="nm">{p.kind === "channel" ? "⬡ " : ""}{p.name}</span>
      <span className="scope">{p.scope === "global" ? "G" : "P"}</span>
    </button>
  );

  const fxMenu = (e: React.MouseEvent, fx: EffectInfo) => {
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY, items: [
      { label: `Dibujar con "${fx.name}"`, onClick: () => onPickEffect(fx) },
      { label: "Crear preset de esto…", onClick: () => setEdit({ create: true, preset: { name: fx.name, base_effect_id: fx.id, family: fx.family, params: {}, color: famHex(fx.family), scope: "project" } }) },
    ] });
  };

  return (
    <div className="tl-browser">
      <div className="bk-tabs">
        <button className={"bk-tab" + (tab === "bank" ? " on" : "")} onClick={() => setTab("bank")}>Banco</button>
        <button className={"bk-tab" + (tab === "base" ? " on" : "")} onClick={() => setTab("base")}>Efectos</button>
        <button className={"bk-tab" + (tab === "patterns" ? " on" : "")} onClick={() => setTab("patterns")}>Patterns</button>
        <button className={"bk-tab" + (tab === "marketplace" ? " on" : "")} onClick={() => setTab("marketplace")}>Market</button>
      </div>

      {tab === "bank" && (
        <>
          <div className="fx-list">
            {presets.length === 0 && <div className="muted" style={{ padding: 12, fontSize: 12 }}>Banco vacío. Crea un preset →</div>}
            {pixelGroups.map(([f, list]) => (
              <div key={"px-" + f}>
                <div className="bk-fam-h"><span className="sw" style={{ background: famColor(f) }} />{f}</div>
                {list.map((p) => renderPreset(p))}
              </div>
            ))}
            {channelGroups.length > 0 && (
              <div className="bk-fam-h" style={{ color: "var(--acc-2)", marginTop: 8 }}>⬡ MOVERS / CANAL</div>
            )}
            {channelGroups.map(([f, list]) => (
              <div key={"ch-" + f}>
                <div className="bk-fam-h"><span className="sw" style={{ background: "var(--acc-2)" }} />{f}</div>
                {list.map((p) => renderPreset(p))}
              </div>
            ))}
          </div>
          <div className="fx-foot" style={{ display: "flex", gap: 6 }}>
            <button className="btn sm primary" style={{ flex: 1 }} onClick={() => openPreset(true)}>+ Nuevo preset</button>
          </div>
        </>
      )}

      {tab === "base" && (
        <>
          <div className="fx-fams">
            {families.map(([f, list]) => (
              <button key={f} className={"fx-fam" + (fam === f || (!fam && families[0][0] === f) ? " on" : "")} onClick={() => setFam(f)}>
                <span className="sw" style={{ background: famColor(f) }} />{f || "otros"}
                <span className="n">{list.length}</span>
              </button>
            ))}
          </div>
          <div className="fx-list">
            {(families.find(([f]) => f === (fam || families[0]?.[0]))?.[1] ?? []).map((fx) => (
              <button key={fx.id} draggable
                className={"fx-item" + (activeFxId === fx.id ? " on" : "")}
                onClick={() => onPickEffect(fx)} onContextMenu={(e) => fxMenu(e, fx)}
                onDragStart={(e) => setDragData(e, "effect", fx.id)}>
                <span className="sw" style={{ background: famColor(fx.family) }} />
                <span className="nm">{fx.name}</span>
                <span className="hint">crear preset →</span>
              </button>
            ))}
          </div>
          <div className="fx-foot"><span className="kbd">B</span> dibujar · click derecho → crear preset</div>
        </>
      )}

      {tab === "patterns" && (
        <>
          <div className="fx-list">
            {patterns.length === 0 && (
              <div className="muted" style={{ padding: 12, fontSize: 12 }}>
                Sin patterns. Selecciona clips → clic derecho → "Crear pattern…"
              </div>
            )}
            {patterns.map((pat) => {
              const instCount = patternInstances.filter((i) => i.pattern_uid === pat.uid).length;
              return (
                <button key={pat.uid}
                  draggable
                  className="fx-item preset-item"
                  title={`${instCount} instancia${instCount !== 1 ? "s" : ""}`}
                  onClick={() => onPickPattern?.(pat)}
                  onDragStart={(e) => setDragData(e, "pattern", pat.uid)}
                  onDoubleClick={() => {
                    // Doble clic = añadir instancia en el t actual del transporte
                    const tMs = Math.round(t * 1000);
                    control.call("add_pattern_instance", {
                      pattern_uid: pat.uid, start_ms: tMs, track_offset: 0,
                    }).then(() => refreshPatternInstances());
                  }}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    setMenu({ x: e.clientX, y: e.clientY, items: [
                      { label: "Añadir instancia aquí", onClick: () => {
                        const tMs = Math.round(t * 1000);
                        control.call("add_pattern_instance", {
                          pattern_uid: pat.uid, start_ms: tMs, track_offset: 0,
                        }).then(() => refreshPatternInstances());
                      }},
                      { type: "sep" },
                      {
                        label: "Borrar" + (instCount > 0 ? ` (borra ${instCount} inst.)` : ""),
                        danger: true,
                        onClick: () => {
                          if (instCount > 0 && !confirm(`Borrar "${pat.name}" y sus ${instCount} instancias?`)) return;
                          control.call("delete_pattern", { pattern_uid: pat.uid })
                            .then(() => { refreshPatterns(); refreshPatternInstances(); });
                        },
                      },
                    ] });
                  }}>
                  <span className="sw" style={{ background: pat.color }} />
                  <span className="nm">{pat.name || "(sin nombre)"}</span>
                  <span className="scope" style={{ color: "var(--txt-3)" }}>{instCount}×</span>
                </button>
              );
            })}
          </div>
          <div className="fx-foot" style={{ fontSize: 11, color: "var(--txt-3)" }}>
            Clic = seleccionar · doble clic = instanciar · arrastrar al timeline
          </div>
        </>
      )}

      {tab === "marketplace" && <MarketplaceTab installedIds={effects.map((e) => e.id)} />}

      <ContextMenu state={menu} onClose={() => setMenu(null)} />

      {edit && (
        <PresetEditor
          state={edit} effects={effects} channelEffects={channelEffects}
          onClose={() => setEdit(null)}
          onSaved={() => { setEdit(null); refreshPresets(); }}
        />
      )}
    </div>
  );
}

// ── Marketplace tab (N1) ─────────────────────────────────────────────────────

interface MarketplacePlugin {
  name: string;
  author?: string;
  version?: string;
  description?: string;
  effect_ids?: number[];
  download_url: string;
}

function MarketplaceTab({ installedIds }: { installedIds: number[] }) {
  const [plugins, setPlugins] = useState<MarketplacePlugin[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [installing, setInstalling] = useState<Record<string, boolean>>({});
  const [installed, setInstalled] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setLoading(true);
    setError(null);
    control.call("list_marketplace_plugins", {})
      .then((r) => {
        if (r.ok) setPlugins(r.plugins ?? []);
        else setError(r.error ?? "error");
      })
      .catch(() => setError("error de red"))
      .finally(() => setLoading(false));
  }, []);

  const isInstalled = (p: MarketplacePlugin) =>
    installed[p.download_url] ||
    (p.effect_ids ?? []).some((id) => installedIds.includes(id));

  const doInstall = async (p: MarketplacePlugin) => {
    setInstalling((s) => ({ ...s, [p.download_url]: true }));
    try {
      const r = await control.call("install_plugin", { download_url: p.download_url });
      if (r.ok) {
        setInstalled((s) => ({ ...s, [p.download_url]: true }));
      } else {
        alert(`Error al instalar: ${r.error}`);
      }
    } catch {
      alert("Error de red al instalar");
    } finally {
      setInstalling((s) => ({ ...s, [p.download_url]: false }));
    }
  };

  if (loading) return <div style={{ padding: 12, fontSize: 12, color: "var(--txt-4)" }}>Cargando…</div>;
  if (error) return <div style={{ padding: 12, fontSize: 12, color: "var(--warn)" }}>Error: {error}</div>;
  if (plugins.length === 0) return <div style={{ padding: 12, fontSize: 12, color: "var(--txt-4)" }}>Sin plugins disponibles</div>;

  return (
    <div className="fx-list">
      {plugins.map((p) => {
        const busy = installing[p.download_url];
        const done = isInstalled(p);
        return (
          <div key={p.download_url} style={{ padding: "6px 10px", borderBottom: "1px solid var(--line-soft)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ flex: 1, fontWeight: 500, fontSize: 12 }}>{p.name}</span>
              {p.version && <span style={{ fontSize: 10, color: "var(--txt-4)" }}>v{p.version}</span>}
              {done ? (
                <span style={{ fontSize: 10, color: "var(--ok)" }}>✓ Instalado</span>
              ) : busy ? (
                <span style={{ fontSize: 10, color: "var(--txt-4)" }}>Instalando…</span>
              ) : (
                <button className="btn sm" style={{ fontSize: 10 }} onClick={() => doInstall(p)}>
                  Instalar
                </button>
              )}
            </div>
            {p.author && <div style={{ fontSize: 10, color: "var(--txt-4)" }}>por {p.author}</div>}
            {p.description && <div style={{ fontSize: 11, color: "var(--txt-3)", marginTop: 2 }}>{p.description}</div>}
          </div>
        );
      })}
    </div>
  );
}

function famHex(_f: string) { return "#3a7acc"; }

function PresetEditor({ state, effects, channelEffects, onClose, onSaved }: {
  state: { create: boolean; preset: Partial<Preset> };
  effects: EffectInfo[];
  channelEffects: ChannelEffectInfo[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [kind, setKind] = useState<string>(state.preset.kind ?? "pixel");
  const [name, setName] = useState(state.preset.name ?? "");
  const [baseId, setBaseId] = useState(state.preset.base_effect_id ?? 0);
  const [chId, setChId] = useState<string>(state.preset.channel_effect_id ?? channelEffects[0]?.effect_id ?? "");
  const [color, setColor] = useState(state.preset.color ?? "#3a7acc");
  const [scope, setScope] = useState(state.preset.scope ?? "project");
  const [hue, setHue] = useState<number>(Number(state.preset.params?.hue ?? 0));
  const [extra, setExtra] = useState<Record<string, any>>(() => {
    const p = { ...(state.preset.params || {}) }; delete (p as any).hue; return p;
  });

  // al elegir un channel effect, precargar sus default_params como editables
  const pickChannelEffect = (id: string) => {
    setChId(id);
    const ce = channelEffects.find((c) => c.effect_id === id);
    if (ce && state.create) setExtra({ ...ce.default_params });
  };

  const save = async () => {
    if (kind === "channel") {
      const payload: any = { name, kind: "channel", channel_effect_id: chId, params: extra, color };
      if (state.create) await control.call("create_preset", { ...payload, scope });
      else await control.call("update_preset", { preset_id: state.preset.preset_id, ...payload });
    } else {
      const params = { ...extra, hue };
      const payload: any = { name, kind: "pixel", base_effect_id: baseId, params, color };
      if (state.create) await control.call("create_preset", { ...payload, scope });
      else await control.call("update_preset", { preset_id: state.preset.preset_id, ...payload });
    }
    onSaved();
  };
  const del = async () => {
    if (!state.create && state.preset.preset_id) await control.call("delete_preset", { preset_id: state.preset.preset_id });
    onSaved();
  };

  const families = [...new Map(effects.map((e) => [e.family, true])).keys()];
  const chCats = [...new Map(channelEffects.map((c) => [c.category, true])).keys()];

  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="preset-editor">
        <div className="ci-head">
          <h4>{state.create ? "Nuevo preset" : "Editar preset"}</h4>
          <button className="x" onClick={onClose}>×</button>
        </div>
        <div className="ci-body">
          {state.create && (
            <div className="ci-row"><label>Tipo</label>
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="pixel">Píxel (barras LED)</option>
                <option value="channel">Mover / canal</option>
              </select>
            </div>
          )}
          <div className="ci-row"><label>Nombre</label><input value={name} onChange={(e) => setName(e.target.value)} /></div>

          {kind === "channel" ? (
            <div className="ci-row"><label>Efecto canal</label>
              <select value={chId} onChange={(e) => pickChannelEffect(e.target.value)}>
                {chCats.map((c) => (
                  <optgroup key={c} label={c}>
                    {channelEffects.filter((ce) => ce.category === c).map((ce) => <option key={ce.effect_id} value={ce.effect_id}>{ce.name}</option>)}
                  </optgroup>
                ))}
              </select>
            </div>
          ) : (
            <>
              <div className="ci-row"><label>Efecto base</label>
                <select value={baseId} onChange={(e) => setBaseId(+e.target.value)}>
                  {families.map((f) => (
                    <optgroup key={f} label={f || "otros"}>
                      {effects.filter((e) => e.family === f).map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
                    </optgroup>
                  ))}
                </select>
              </div>
              <div className="ci-row"><label>Hue</label>
                <input type="range" min={0} max={360} value={hue} onChange={(e) => setHue(+e.target.value)} />
                <span className="mono" style={{ width: 34, textAlign: "right", color: "var(--acc)" }}>{hue}°</span>
              </div>
            </>
          )}

          <div className="ci-row"><label>Color clip</label>
            <input type="color" value={color} onChange={(e) => setColor(e.target.value)} /></div>
          {state.create && (
            <div className="ci-row"><label>Ámbito</label>
              <select value={scope} onChange={(e) => setScope(e.target.value)}>
                <option value="project">Proyecto</option>
                <option value="global">Global</option>
              </select>
            </div>
          )}
          {Object.keys(extra).length > 0 && <div className="ci-sub">Parámetros</div>}
          {Object.entries(extra).map(([k, v]) => (
            <div className="ci-row" key={k}><label>{k}</label>
              <input className="mono" defaultValue={String(v)} onBlur={(e) => {
                let val: any = e.target.value; const n = Number(val);
                if (val.trim() !== "" && !isNaN(n)) val = n;
                setExtra((x) => ({ ...x, [k]: val }));
              }} /></div>
          ))}
          <div className="ci-row" style={{ marginTop: 6, gap: 6 }}>
            <button className="btn primary sm" style={{ flex: 1 }} onClick={save}>{state.create ? "Crear" : "Guardar"}</button>
            {!state.create && <button className="btn sm" style={{ color: "var(--bad)" }} onClick={del}>Borrar</button>}
          </div>
          {!state.create && <p className="muted" style={{ fontSize: 10.5, lineHeight: 1.4 }}>Al guardar, todos los clips de este preset se actualizan (enlace vivo).</p>}
        </div>
      </div>
    </div>
  );
}
