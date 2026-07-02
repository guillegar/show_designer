// MarkerContextMenu.tsx — I2: menú contextual de marcador (color/categoría/borrar).
// Autónomo (despiece de Timeline.tsx): posee su estado de edición; el padre solo
// controla apertura/posición y recibe onChanged para refrescar la lista.
import { useState } from "react";
import { control } from "../../api/control";
import type { MarkerCategory } from "../../store";

export type MarkerMenuState = {
  t_ms: number; x: number; y: number; color: string; category: string;
};

export function MarkerContextMenu({ initial, onClose, onChanged }: {
  initial: MarkerMenuState;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [menu, setMenu] = useState(initial);

  return (
    <div className="modal-overlay" style={{ background: "transparent" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="marker-ctx-menu" style={{ position: "fixed", top: menu.y, left: menu.x, zIndex: 300 }}>
        <div className="marker-ctx-row">
          <label style={{ fontSize: 10, color: "var(--txt-3)" }}>Color</label>
          <input type="color" value={menu.color} style={{ width: 32, height: 22, border: "none", padding: 0, cursor: "pointer" }}
            onChange={(e) => setMenu({ ...menu, color: e.target.value })}
            onBlur={() => {
              control.call("update_marker", { t_ms: menu.t_ms, color: menu.color }).then(onChanged);
            }} />
        </div>
        <div className="marker-ctx-row">
          <label style={{ fontSize: 10, color: "var(--txt-3)" }}>Categoría</label>
          <select className="field" style={{ height: 22, fontSize: 10 }} value={menu.category}
            onChange={(e) => {
              const cat = e.target.value as MarkerCategory;
              setMenu({ ...menu, category: cat });
              control.call("update_marker", { t_ms: menu.t_ms, category: cat }).then(onChanged);
            }}>
            <option value="intro">Intro</option>
            <option value="verso">Verso</option>
            <option value="estribillo">Estribillo</option>
            <option value="bridge">Bridge</option>
            <option value="outro">Outro</option>
            <option value="custom">Custom</option>
          </select>
        </div>
        <button className="btn sm ghost" style={{ width: "100%", marginTop: 4, color: "var(--err)" }}
          onClick={() => {
            control.call("delete_marker", { time_ms: menu.t_ms }).then(onChanged);
            onClose();
          }}>Borrar marcador</button>
      </div>
    </div>
  );
}
