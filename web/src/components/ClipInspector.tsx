import React, { useEffect, useRef, useState } from "react";
import { Clip, EffectInfo } from "../store";
import { control } from "../api/control";
import {
  EffectSchema,
  hexToRgb,
  rgbToHex,
  detectColorGroups,
  colorGroupKeys,
} from "../api/schema";

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

export function ClipInspector({
  clip,
  effects,
  lastDuration,
  onDurationChange,
  onClipUpdate,
}: ClipInspectorProps) {
  const [editingDuration, setEditingDuration] = useState(false);
  const [schema, setSchema] = useState<EffectSchema | null>(null);
  const schemaCacheRef = useRef<Record<number, EffectSchema | null>>({});

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

      {/* Dynamic params */}
      {renderParams()}

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
