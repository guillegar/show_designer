import { useEffect, useRef } from "react";

export type MenuItem =
  | { type: "sep" }
  | { type?: "item"; label: string; onClick: () => void; danger?: boolean; disabled?: boolean; hint?: string };

export type MenuState = { x: number; y: number; items: MenuItem[] } | null;

export function ContextMenu({ state, onClose }: { state: MenuState; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!state) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", esc); };
  }, [state, onClose]);

  if (!state) return null;
  // mantener dentro de la ventana
  const x = Math.min(state.x, window.innerWidth - 220);
  const y = Math.min(state.y, window.innerHeight - state.items.length * 30 - 16);

  return (
    <div ref={ref} className="ctx-menu" style={{ left: x, top: y }}>
      {state.items.map((it, i) =>
        "type" in it && it.type === "sep" ? (
          <div key={i} className="ctx-sep" />
        ) : (
          <button key={i} className={"ctx-item" + ((it as any).danger ? " danger" : "")}
            disabled={(it as any).disabled}
            onClick={() => { (it as any).onClick(); onClose(); }}>
            <span>{(it as any).label}</span>
            {(it as any).hint && <span className="ctx-hint">{(it as any).hint}</span>}
          </button>
        )
      )}
    </div>
  );
}
