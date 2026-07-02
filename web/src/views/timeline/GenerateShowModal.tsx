// GenerateShowModal.tsx — M2: generación automática de show desde el análisis.
// Autónomo (despiece de Timeline.tsx): posee su propio estado (estilo/densidad/
// replace/status); el padre solo controla la apertura.
import { useState } from "react";
import { control } from "../../api/control";

export function GenerateShowModal({ onClose, onGenerated }: {
  onClose: () => void;
  onGenerated: () => void;
}) {
  const [style, setStyle] = useState("club");
  const [density, setDensity] = useState(0.5);
  const [replace, setReplace] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const generating = status === "Generando…";

  const generate = async () => {
    setStatus("Generando…");
    try {
      const r: any = await control.call("generate_show", { style, density, replace });
      if (r?.ok) {
        setStatus(`✓ ${r.clips_created} clips creados`);
        onGenerated();
        setTimeout(onClose, 1800);
      } else {
        setStatus(r?.error ?? "Error");
      }
    } catch (e: any) {
      setStatus("Error: " + e.message);
    }
  };

  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="preset-editor">
        <div className="ci-head"><h4>Generar show automático</h4><button className="x" onClick={onClose}>×</button></div>
        <div className="ci-body">
          <div className="ci-row"><label>Estilo</label>
            <select value={style} onChange={(e) => setStyle(e.target.value)}>
              {["minimal", "club", "festival", "chill"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select></div>
          <div className="ci-row"><label>Densidad</label>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1 }}>
              <input type="range" min={0} max={100} value={Math.round(density * 100)}
                onChange={(e) => setDensity(+e.target.value / 100)} style={{ flex: 1 }} />
              <span style={{ minWidth: 30, fontSize: 11 }}>{Math.round(density * 100)}%</span>
            </div></div>
          <div className="ci-row"><label>Reemplazar</label>
            <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
            <span style={{ fontSize: 11, color: "var(--txt-3)", marginLeft: 6 }}>Limpiar timeline antes</span>
          </div>
          <div className="ci-row" style={{ marginTop: 6 }}>
            <button className="btn primary sm" style={{ flex: 1 }} onClick={generate} disabled={generating}>
              {generating ? "Generando…" : "Generar show"}
            </button>
          </div>
          {status && !generating && (
            <div style={{ fontSize: 11, marginTop: 6, color: status.startsWith("✓") ? "var(--good)" : "var(--bad)" }}>
              {status}
            </div>
          )}
          <p className="muted" style={{ fontSize: 10.5, lineHeight: 1.4, marginTop: 6 }}>
            Genera clips sincronizados a beats/downbeats. Requiere análisis previo. Deshaciable con Ctrl+Z.
          </p>
        </div>
      </div>
    </div>
  );
}
