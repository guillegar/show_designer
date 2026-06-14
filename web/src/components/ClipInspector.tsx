import React, { useCallback, useEffect, useRef, useState } from "react";
import { Clip, ChannelEffectInfo, EffectInfo } from "../store";
import { control } from "../api/control";
import {
  EffectSchema,
  hexToRgb,
  rgbToHex,
  detectColorGroups,
  colorGroupKeys,
} from "../api/schema";

// ── G3: Preview SVG trayectoria pan/tilt ────────────────────────────────────

function PanTiltPreview({ mode, speed, panCenter, tiltCenter, panRange, tiltRange }: {
  mode: string; speed: number; panCenter: number; tiltCenter: number;
  panRange: number; tiltRange: number;
}) {
  const SIZE = 80;
  const cx = SIZE / 2;
  const cy = SIZE / 2;
  const rx = panRange * SIZE;
  const ry = tiltRange * SIZE;

  // Genera la trayectoria SVG de 1 ciclo completo (64 puntos)
  const nPts = 64;
  let points: string[] = [];
  for (let i = 0; i <= nPts; i++) {
    const t = (i / nPts) / speed;
    const omega = 2 * Math.PI * speed * t;
    let px: number, py: number;
    if (mode === "circle") { px = Math.cos(omega); py = Math.sin(omega); }
    else if (mode === "fig8") { px = Math.sin(omega); py = Math.sin(2 * omega) / 2; }
    else if (mode === "bounce_pan") { px = Math.sin(omega); py = 0; }
    else { px = 0; py = Math.sin(omega); }
    points.push(`${cx + px * rx},${cy + py * ry}`);
  }
  const pathD = "M " + points.join(" L ");

  // Punto de posición en t=0
  const dot = {
    x: mode === "circle" ? cx + rx : mode === "fig8" ? cx : mode === "bounce_pan" ? cx : cx,
    y: mode === "circle" ? cy : mode === "fig8" ? cy : cy,
  };

  return (
    <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}
      style={{ border: "1px solid var(--line-soft)", borderRadius: 4, display: "block" }}>
      <circle cx={cx} cy={cy} r={SIZE / 2 - 2} fill="none" stroke="var(--line-soft)" strokeWidth={0.5} />
      <path d={pathD} fill="none" stroke="var(--acc)" strokeWidth={1.2} opacity={0.7} />
      <circle cx={dot.x} cy={dot.y} r={3} fill="var(--acc)" />
    </svg>
  );
}

// ── G3: Sección Movimiento en el inspector ────────────────────────────────

function MovimientoSection({ clip, onClipUpdate }: { clip: Clip; onClipUpdate: () => void }) {
  const [channelEffects, setChannelEffects] = useState<ChannelEffectInfo[]>([]);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    control.call("list_channel_effects", {}).then((r: any) => {
      if (r?.effects) setChannelEffects(r.effects.filter((e: ChannelEffectInfo) => e.category === "position"));
    }).catch(() => {});
  }, []);

  const activeEntry = (clip.channel_effects || []).find((e) =>
    channelEffects.some((ce) => ce.effect_id === e.id)
  ) ?? (clip.channel_effect_id ? { id: clip.channel_effect_id, params: clip.params } : null);

  if (clip.category !== "position" && !activeEntry) return null;

  const params = activeEntry?.params ?? {};
  const mode = String(params.mode ?? "circle");
  const speed = Number(params.speed ?? 0.5);
  const panCenter = Number(params.pan_center ?? 0.5);
  const tiltCenter = Number(params.tilt_center ?? 0.5);
  const panRange = Number(params.pan_range ?? 0.25);
  const tiltRange = Number(params.tilt_range ?? 0.25);

  const setEffect = async (effectId: string, newParams: Record<string, any>) => {
    await control.call("set_clip_channel_effect", {
      clip_id: clip.id, config: { id: effectId, params: newParams },
    });
    onClipUpdate();
  };

  const currentEffectId = activeEntry?.id ?? "pos_pantilt_wave";

  return (
    <div className="inspector-section movement-section">
      <div style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}
        onClick={() => setCollapsed((c) => !c)}>
        <label style={{ cursor: "pointer", flex: 1 }}>Movimiento</label>
        <span style={{ fontSize: 10, color: "var(--txt-4)" }}>{collapsed ? "▸" : "▾"}</span>
      </div>
      {!collapsed && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <select
              value={currentEffectId}
              onChange={(e) => setEffect(e.target.value, params)}
              style={{ flex: 1, fontSize: 11, background: "var(--bg-2)", color: "var(--txt)", border: "1px solid var(--line-soft)", borderRadius: 4, padding: "2px 4px" }}
            >
              {channelEffects.map((ce) => (
                <option key={ce.effect_id} value={ce.effect_id}>{ce.name}</option>
              ))}
            </select>
            <PanTiltPreview mode={mode} speed={speed}
              panCenter={panCenter} tiltCenter={tiltCenter}
              panRange={panRange} tiltRange={tiltRange} />
          </div>
          {currentEffectId === "pos_pantilt_wave" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ display: "flex", gap: 4 }}>
                {(["circle", "fig8", "bounce_pan", "bounce_tilt"] as const).map((m) => (
                  <button key={m}
                    className={`btn sm${mode === m ? " active" : " ghost"}`}
                    style={{ flex: 1, fontSize: 9, padding: "2px 3px" }}
                    onClick={() => setEffect(currentEffectId, { ...params, mode: m })}>
                    {m === "circle" ? "○" : m === "fig8" ? "∞" : m === "bounce_pan" ? "↔" : "↕"}
                  </button>
                ))}
              </div>
              {[
                { key: "speed", label: "Vel", min: 0.1, max: 4, step: 0.1 },
                { key: "pan_range", label: "Pan R", min: 0, max: 0.5, step: 0.05 },
                { key: "tilt_range", label: "Tilt R", min: 0, max: 0.5, step: 0.05 },
              ].map(({ key, label, min, max, step }) => (
                <div key={key} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <label style={{ fontSize: 10, minWidth: 32, color: "var(--txt-4)" }}>{label}</label>
                  <input type="range" min={min} max={max} step={step}
                    value={Number(params[key] ?? (key === "speed" ? 0.5 : 0.25))}
                    style={{ flex: 1 }}
                    onChange={(e) => setEffect(currentEffectId, { ...params, [key]: parseFloat(e.target.value) })} />
                  <span style={{ fontSize: 10, fontFamily: "var(--mono)", minWidth: 28, textAlign: "right" }}>
                    {Number(params[key] ?? (key === "speed" ? 0.5 : 0.25)).toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface ClipInspectorProps {
  clip: Clip | null;
  effects: EffectInfo[];
  lastDuration: number;
  onDurationChange: (dur: number) => void;
  onClipUpdate: () => void;
}

// ── Color picker agrupado ──────────────────────────────────────────────────

function ColorGroupControl({
  label,
  rKey,
  gKey,
  bKey,
  params,
  clipId,
  onClipUpdate,
}: {
  label: string;
  rKey: string;
  gKey: string;
  bKey: string;
  params: Record<string, unknown>;
  clipId: string;
  onClipUpdate: () => void;
}) {
  const r = Number(params[rKey] ?? 255);
  const g = Number(params[gKey] ?? 255);
  const b = Number(params[bKey] ?? 255);
  const hex = rgbToHex(r, g, b);

  return (
    <div className="param-field param-field--color">
      <label>{label}</label>
      <div className="param-color-row">
        <input
          type="color"
          value={hex}
          onChange={async (e) => {
            const rgb = hexToRgb(e.target.value);
            await control.call("set_clip_params", {
              clip_id: clipId,
              params: { [rKey]: rgb.r, [gKey]: rgb.g, [bKey]: rgb.b },
            });
            onClipUpdate();
          }}
        />
        <span
          className="color-swatch"
          style={{ background: hex, width: 24, height: 24, display: "inline-block", borderRadius: 3, border: "1px solid #555", verticalAlign: "middle" }}
        />
        <span className="param-value">{hex}</span>
      </div>
    </div>
  );
}

// ── Control individual por tipo ────────────────────────────────────────────

function ParamControl({
  name,
  spec,
  value,
  clipId,
  onClipUpdate,
}: {
  name: string;
  spec: EffectSchema[string];
  value: unknown;
  clipId: string;
  onClipUpdate: () => void;
}) {
  const label = spec.label ?? name;
  const unit = spec.unit ? ` ${spec.unit}` : "";

  const sendParam = async (val: unknown) => {
    await control.call("set_clip_params", {
      clip_id: clipId,
      params: { [name]: val },
    });
    onClipUpdate();
  };

  if (spec.type === "float" || spec.type === "int") {
    const min = spec.min ?? 0;
    const max = spec.max ?? 1;
    const step = spec.step ?? (spec.type === "int" ? 1 : 0.01);
    const cur = Number(value ?? spec.default ?? min);

    return (
      <div className="param-field param-field--range">
        <label>
          {label}
          {unit && <span className="param-unit">{unit}</span>}
        </label>
        <div className="param-range-row">
          <input
            type="range"
            min={min}
            max={max}
            step={step}
            value={cur}
            onChange={async (e) => {
              const v = spec.type === "int" ? parseInt(e.target.value) : parseFloat(e.target.value);
              await sendParam(v);
            }}
          />
          <input
            type="number"
            min={min}
            max={max}
            step={step}
            value={cur}
            className="param-number"
            onChange={async (e) => {
              const v = spec.type === "int" ? parseInt(e.target.value) : parseFloat(e.target.value);
              if (!isNaN(v)) await sendParam(v);
            }}
          />
        </div>
      </div>
    );
  }

  if (spec.type === "bool") {
    const checked = Boolean(value ?? spec.default ?? false);
    return (
      <div className="param-field param-field--bool">
        <label>{label}</label>
        <input
          type="checkbox"
          checked={checked}
          onChange={async (e) => {
            await sendParam(e.target.checked);
          }}
        />
      </div>
    );
  }

  if (spec.type === "enum") {
    const options = spec.options ?? [];
    const cur = String(value ?? spec.default ?? options[0] ?? "");
    return (
      <div className="param-field param-field--enum">
        <label>{label}</label>
        <select
          value={cur}
          onChange={async (e) => {
            await sendParam(e.target.value);
          }}
        >
          {options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </div>
    );
  }

  // K2 — tipo "str": texto puro (sin conversión numérica)
  if (spec.type === "str") {
    const cur = String(value ?? spec.default ?? "");
    return (
      <div className="param-field param-field--str">
        <label>{label}</label>
        <input
          type="text"
          defaultValue={cur}
          key={cur}
          placeholder={spec.label?.includes("Archivo") ? "ruta al archivo..." : ""}
          style={{ width: "100%", fontFamily: "monospace", fontSize: 11 }}
          onBlur={async (e) => {
            await sendParam(e.target.value);
          }}
        />
      </div>
    );
  }

  // fallback: texto genérico
  return (
    <div className="param-field">
      <label>{label}</label>
      <input
        type="text"
        defaultValue={String(value ?? "")}
        onBlur={async (e) => {
          let val: unknown = e.target.value;
          const n = Number(val);
          if ((val as string).trim() !== "" && !isNaN(n)) val = n;
          await sendParam(val);
        }}
      />
    </div>
  );
}

// ── Inspector principal ────────────────────────────────────────────────────

interface PresetChip {
  preset_id: string;
  name: string;
  color: string;
}

export function ClipInspector({
  clip,
  effects,
  lastDuration,
  onDurationChange,
  onClipUpdate,
}: ClipInspectorProps) {
  const [editingDuration, setEditingDuration] = useState(false);
  const [schema, setSchema] = useState<EffectSchema | null>(null);
  const [suggestedPresets, setSuggestedPresets] = useState<PresetChip[]>([]);
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);
  const [previewTms, setPreviewTms] = useState(0);
  const schemaCacheRef = useRef<Record<number, EffectSchema | null>>({});
  const presetCacheRef = useRef<Record<number, PresetChip[]>>({});
  const previewDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Carga el schema al cambiar el effect_id del clip
  useEffect(() => {
    if (!clip) { setSchema(null); return; }
    const id = clip.effect_id;
    if (id in schemaCacheRef.current) {
      setSchema(schemaCacheRef.current[id]);
      return;
    }
    control
      .call("get_effect_schema", { effect_id: id })
      .then((res: { ok: boolean; schema?: EffectSchema }) => {
        const s = res?.ok ? (res.schema ?? null) : null;
        schemaCacheRef.current[id] = s;
        setSchema(s);
      })
      .catch(() => {
        schemaCacheRef.current[id] = null;
        setSchema(null);
      });
  }, [clip?.effect_id]);

  // Carga presets sugeridos al cambiar el effect_id
  useEffect(() => {
    if (!clip) { setSuggestedPresets([]); return; }
    const id = clip.effect_id;
    if (id in presetCacheRef.current) {
      setSuggestedPresets(presetCacheRef.current[id]);
      return;
    }
    control
      .call("list_presets", { effect_id: id })
      .then((res: { presets?: PresetChip[] }) => {
        const chips = (res?.presets ?? []).slice(0, 3);
        presetCacheRef.current[id] = chips;
        setSuggestedPresets(chips);
      })
      .catch(() => {
        presetCacheRef.current[id] = [];
        setSuggestedPresets([]);
      });
  }, [clip?.effect_id]);

  // Fetch preview con debounce (200 ms)
  const fetchPreview = useCallback((effectId: number, effectParams: Record<string, unknown>, tMs: number) => {
    if (previewDebounceRef.current) clearTimeout(previewDebounceRef.current);
    previewDebounceRef.current = setTimeout(async () => {
      try {
        const res = await control.call("preview_effect_frame", {
          effect_id: effectId,
          params: effectParams,
          t_ms: tMs,
        }) as { ok: boolean; frame_b64?: string };
        if (res?.ok && res.frame_b64) {
          setPreviewSrc(`data:image/png;base64,${res.frame_b64}`);
        }
      } catch {
        // preview no crítico — silenciar errores
      }
    }, 200);
  }, []);

  // Re-fetch preview cuando cambian params, effect o t_ms
  useEffect(() => {
    if (!clip) { setPreviewSrc(null); return; }
    fetchPreview(clip.effect_id, clip.params || {}, previewTms);
  }, [clip?.effect_id, clip?.params, previewTms, fetchPreview]);

  if (!clip) {
    return (
      <div className="inspector inspector-empty">
        <p>Selecciona un clip</p>
      </div>
    );
  }

  const effect = effects.find((e) => e.id === clip.effect_id);
  const dur = (clip.end_ms - clip.start_ms) / 1000;
  const clipParams = clip.params || {};
  const hasSchema = schema && Object.keys(schema).length > 0;

  const handleDurationChange = async (newSec: number) => {
    const newMs = Math.max(100, Math.min(60000, newSec * 1000));
    const newEnd = clip.start_ms + newMs;
    try {
      await control.call("move_clip", {
        clip_id: clip.id,
        new_start_ms: clip.start_ms,
        new_end_ms: newEnd,
      });
      onDurationChange(newMs);
      onClipUpdate();
      try { await control.call("snapshot"); } catch (_) { /* undo not available */ }
    } catch (err) {
      console.error("Duration change failed:", err);
    }
  };

  // Construye los controles de parámetros según el schema
  const renderParams = () => {
    if (!hasSchema) {
      // Sin schema → inputs de texto genéricos (backwards compat)
      const paramCount = Object.keys(clipParams).length;
      if (paramCount === 0) return null;
      return (
        <div className="inspector-section params-section">
          <h4>Parámetros</h4>
          {Object.entries(clipParams).map(([k, v]) => (
            <div key={k} className="param-field">
              <label>{k}</label>
              <input
                type="text"
                defaultValue={String(v)}
                onBlur={(e) => {
                  let val: unknown = e.target.value;
                  const n = Number(val);
                  if ((val as string).trim() !== "" && !isNaN(n)) val = n;
                  control.call("set_clip_params", { clip_id: clip.id, params: { [k]: val } });
                }}
              />
            </div>
          ))}
        </div>
      );
    }

    const colorGroups = detectColorGroups(schema);
    const colorKeys = colorGroupKeys(schema);
    // Params del schema que NO son parte de un color group
    const individualEntries = Object.entries(schema).filter(([k]) => !colorKeys.has(k));

    return (
      <div className="inspector-section params-section">
        <h4>Parámetros</h4>

        {/* Color pickers agrupados */}
        {colorGroups.map((grp) => (
          <ColorGroupControl
            key={grp.keys[0]}
            label={grp.label}
            rKey={grp.keys[0]}
            gKey={grp.keys[1]}
            bKey={grp.keys[2]}
            params={clipParams}
            clipId={clip.id}
            onClipUpdate={onClipUpdate}
          />
        ))}

        {/* Controles individuales (sliders, bool, enum) */}
        {individualEntries.map(([k, spec]) => (
          <ParamControl
            key={k}
            name={k}
            spec={spec}
            value={clipParams[k]}
            clipId={clip.id}
            onClipUpdate={onClipUpdate}
          />
        ))}

        {/* Params adicionales no cubiertos por el schema → texto genérico */}
        {Object.entries(clipParams)
          .filter(([k]) => !(k in schema) && !colorKeys.has(k))
          .map(([k, v]) => (
            <div key={k} className="param-field">
              <label>{k}</label>
              <input
                type="text"
                defaultValue={String(v)}
                onBlur={(e) => {
                  let val: unknown = e.target.value;
                  const n = Number(val);
                  if ((val as string).trim() !== "" && !isNaN(n)) val = n;
                  control.call("set_clip_params", { clip_id: clip.id, params: { [k]: val } });
                }}
              />
            </div>
          ))}
      </div>
    );
  };

  return (
    <div className="inspector" data-param-count={Object.keys(clipParams).length}>
      <div className="inspector-header">
        <h3>{effect?.name || "Desconocido"}</h3>
        <span className="inspector-id">#{clip.id}</span>
      </div>

      {/* Live preview miniatura */}
      {previewSrc && (
        <div className="inspector-section preview-section">
          <img
            src={previewSrc}
            alt="preview"
            className="effect-preview-img"
            style={{ width: "100%", imageRendering: "pixelated", borderRadius: 3 }}
          />
          <div className="preview-tms-row">
            <label className="preview-tms-label">t</label>
            <input
              type="range"
              min={0}
              max={2000}
              step={50}
              value={previewTms}
              className="preview-tms-slider"
              onChange={(e) => setPreviewTms(Number(e.target.value))}
            />
            <span className="preview-tms-val">{(previewTms / 1000).toFixed(1)}s</span>
          </div>
        </div>
      )}

      {/* Duration section */}
      <div className="inspector-section duration-section">
        <label>Duración</label>
        <div className="duration-display">
          {editingDuration ? (
            <input
              type="number"
              min="0.1"
              max="60"
              step="0.1"
              value={dur.toFixed(2)}
              onBlur={(e) => {
                handleDurationChange(parseFloat(e.target.value));
                setEditingDuration(false);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  handleDurationChange(parseFloat(e.currentTarget.value));
                  setEditingDuration(false);
                }
              }}
              autoFocus
            />
          ) : (
            <span onClick={() => setEditingDuration(true)} className="duration-value">
              {dur.toFixed(2)}s
            </span>
          )}
        </div>
      </div>

      {/* Effect selector */}
      <div className="inspector-section">
        <label>Efecto</label>
        <select
          value={clip.effect_id}
          onChange={async (e) => {
            await control.call("set_clip_effect", {
              clip_id: clip.id,
              effect_id: +e.target.value,
              label: effects.find((fx) => fx.id === +e.target.value)?.name,
            });
            onClipUpdate();
          }}
        >
          {effects.map((fx) => (
            <option key={fx.id} value={fx.id}>
              {fx.name}
            </option>
          ))}
        </select>
      </div>

      {/* Scope */}
      <div className="inspector-section">
        <label>Ámbito</label>
        <select
          value={clip.scope}
          onChange={async (e) => {
            await control.call("set_clip_scope", { clip_id: clip.id, scope: e.target.value });
            onClipUpdate();
          }}
        >
          <option value="pixel:all">Todos los píxeles</option>
          <option value="per_bar">Por barra</option>
          <option value="fixture">Fixture</option>
        </select>
      </div>

      {/* Color del clip (color visual en el timeline, no params del efecto) */}
      <div className="inspector-section">
        <label>Color clip</label>
        <input
          type="color"
          value={clip.color || "#ccf"}
          onChange={async (e) => {
            await control.call("set_clip_color", { clip_id: clip.id, color: e.target.value });
            onClipUpdate();
          }}
        />
      </div>

      {/* Presets sugeridos */}
      {suggestedPresets.length > 0 && (
        <div className="inspector-section presets-section">
          <h4>Presets sugeridos</h4>
          <div className="preset-chips">
            {suggestedPresets.map((preset) => (
              <button
                key={preset.preset_id}
                className="preset-chip"
                style={{ borderColor: preset.color }}
                title={preset.name}
                onClick={async () => {
                  await control.call("set_clip_preset", {
                    clip_id: clip.id,
                    preset_id: preset.preset_id,
                  });
                  onClipUpdate();
                }}
              >
                <span
                  className="preset-chip-dot"
                  style={{ background: preset.color }}
                />
                {preset.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Dynamic params */}
      {renderParams()}

      {/* G3: Movimiento (solo si es un clip de canal de posición) */}
      <MovimientoSection clip={clip} onClipUpdate={onClipUpdate} />

      {/* Actions */}
      <div className="inspector-actions">
        <button
          onClick={async () => {
            await control.call("set_clip_lock", { clip_id: clip.id, locked: !clip.locked });
            onClipUpdate();
          }}
          className={clip.locked ? "active" : ""}
          title="Bloquear/Desbloquear"
        >
          🔒
        </button>
        <button
          onClick={async () => {
            await control.call("set_clip_mute", { clip_id: clip.id, muted: !clip.muted });
            onClipUpdate();
          }}
          className={clip.muted ? "active" : ""}
          title="Silenciar"
        >
          🔇
        </button>
        <button
          onClick={async () => {
            await control.call("delete_clip", { clip_id: clip.id });
            onClipUpdate();
          }}
          title="Borrar"
          className="danger"
        >
          ✕
        </button>
      </div>
    </div>
  );
}
