import React from "react";
import { Clip, EffectInfo } from "../store";
import { control } from "../api/control";

interface ClipInspectorProps {
  clip: Clip | null;
  effects: EffectInfo[];
  lastDuration: number;
  onDurationChange: (dur: number) => void;
  onClipUpdate: () => void;
}

export function ClipInspector({
  clip,
  effects,
  lastDuration,
  onDurationChange,
  onClipUpdate,
}: ClipInspectorProps) {
  const [editingDuration, setEditingDuration] = React.useState(false);

  if (!clip) {
    return (
      <div className="inspector inspector-empty">
        <p>Selecciona un clip</p>
      </div>
    );
  }

  const effect = effects.find((e) => e.id === clip.effect_id);
  const dur = (clip.end_ms - clip.start_ms) / 1000;
  const paramCount = Object.keys(clip.params || {}).length;

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
      // Create undo snapshot
      try {
        await control.call("snapshot");
      } catch (e) {
        // Undo not available
      }
    } catch (err) {
      console.error("Duration change failed:", err);
    }
  };

  return (
    <div className="inspector" data-param-count={paramCount}>
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
            <span
              onClick={() => setEditingDuration(true)}
              className="duration-value"
            >
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
            await control.call("set_clip_scope", {
              clip_id: clip.id,
              scope: e.target.value,
            });
            onClipUpdate();
          }}
        >
          <option value="pixel:all">Todos los píxeles</option>
          <option value="per_bar">Por barra</option>
          <option value="fixture">Fixture</option>
        </select>
      </div>

      {/* Color */}
      <div className="inspector-section">
        <label>Color</label>
        <input
          type="color"
          value={clip.color || "#ccf"}
          onChange={async (e) => {
            await control.call("set_clip_color", {
              clip_id: clip.id,
              color: e.target.value,
            });
            onClipUpdate();
          }}
        />
      </div>

      {/* Dynamic params */}
      {paramCount > 0 && (
        <div className="inspector-section params-section">
          <h4>Parámetros</h4>
          {Object.entries(clip.params || {}).map(([k, v]) => (
            <div key={k} className="param-field">
              <label>{k}</label>
              <input
                type="text"
                defaultValue={String(v)}
                onBlur={(e) => {
                  let val: any = e.target.value;
                  const n = Number(val);
                  if (val.trim() !== "" && !isNaN(n)) val = n;

                  control.call("set_clip_params", {
                    clip_id: clip.id,
                    params: { [k]: val },
                  });
                }}
              />
            </div>
          ))}
        </div>
      )}

      {/* Actions */}
      <div className="inspector-actions">
        <button
          onClick={async () => {
            await control.call("set_clip_lock", {
              clip_id: clip.id,
              locked: !clip.locked,
            });
            onClipUpdate();
          }}
          className={clip.locked ? "active" : ""}
          title="Bloquear/Desbloquear"
        >
          🔒
        </button>
        <button
          onClick={async () => {
            await control.call("set_clip_mute", {
              clip_id: clip.id,
              muted: !clip.muted,
            });
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
