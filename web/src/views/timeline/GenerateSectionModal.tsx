// GenerateSectionModal.tsx — "✨ Generar": crea clips en una sección sincronizados
// a los eventos del análisis (beats/downbeats/kicks/...) con el efecto/preset activo.
// Autónomo (despiece de Timeline.tsx): posee su estado (sección/disparo/barras).
import { useState } from "react";
import { control } from "../../api/control";
import type { Section } from "../../store";
import { fmtTime } from "../../icons";

const NUM_BARS = 10;

export type DrawInfo = {
  effect_id: number;
  color: string;
  params: Record<string, any>;
  name: string;
};

export function GenerateSectionModal({ drawInfo, sections, onClose, onGenerated }: {
  drawInfo: DrawInfo;
  sections: Section[];
  onClose: () => void;
  onGenerated: () => void;
}) {
  const [sec, setSec] = useState(0);
  const [trigger, setTrigger] = useState("on_beat");
  const [allBars, setAllBars] = useState(true);

  const runGenerate = async () => {
    const s = sections[sec];
    if (!s) return;
    const base = {
      start_sec: s.start, end_sec: s.end, effect_id: drawInfo.effect_id,
      color: drawInfo.color, clip_params: drawInfo.params, trigger, scope: "per_bar",
    };
    if (allBars) {
      for (let b = 0; b < NUM_BARS; b++) await control.call("generate_section", { ...base, track: b });
    } else {
      await control.call("generate_section", { ...base, track: 0 });
    }
    onClose();
    onGenerated();
  };

  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="preset-editor">
        <div className="ci-head"><h4>Generar · {drawInfo.name}</h4><button className="x" onClick={onClose}>×</button></div>
        <div className="ci-body">
          <div className="ci-row"><label>Sección</label>
            <select value={sec} onChange={(e) => setSec(+e.target.value)}>
              {sections.map((s, i) => <option key={i} value={i}>{s.name} ({fmtTime(s.start)})</option>)}
            </select></div>
          <div className="ci-row"><label>Disparo</label>
            <select value={trigger} onChange={(e) => setTrigger(e.target.value)}>
              <option value="on_beat">en cada beat</option>
              <option value="on_downbeat">en cada compás</option>
              <option value="on_kick">en cada kick</option>
              <option value="on_snare">en cada snare</option>
              <option value="on_drop">en drops</option>
              <option value="every_500ms">cada 500 ms</option>
              <option value="fill">rellenar (1 clip)</option>
            </select></div>
          <div className="ci-row"><label>Barras</label>
            <select value={allBars ? "all" : "one"} onChange={(e) => setAllBars(e.target.value === "all")}>
              <option value="all">Todas (0-9)</option>
              <option value="one">Solo Bar 0</option>
            </select></div>
          <div className="ci-row" style={{ marginTop: 6 }}>
            <button className="btn primary sm" style={{ flex: 1 }} onClick={runGenerate}>Generar</button>
          </div>
          <p className="muted" style={{ fontSize: 10.5, lineHeight: 1.4 }}>Crea clips con el efecto/preset activo sincronizados a los eventos de la sección.</p>
        </div>
      </div>
    </div>
  );
}
