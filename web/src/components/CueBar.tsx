import { useEffect, useState } from "react";
import { control } from "../api/control";
import { useStore } from "../store";
import { fmtTime } from "../icons";
import { ContextMenu, MenuState } from "./ContextMenu";

// Botonera de 9 cues (modo directo) + blackout. Atajos 1-9 disparar, Shift+1-9 set.
export function CueBar() {
  const cues = useStore((s) => s.cues);
  const t = useStore((s) => s.t);
  const refreshCues = useStore((s) => s.refreshCues);
  const [menu, setMenu] = useState<MenuState>(null);

  const slots = [1, 2, 3, 4, 5, 6, 7, 8, 9];
  const cueFor = (slot: number) => cues.find((c) => c.slot === slot);
  const isSet = (c?: { time_ms: number }) => !!c && c.time_ms >= 0;

  const trigger = (slot: number) => control.call("trigger_cue", { slot });
  const setHere = (slot: number) => control.call("set_cue", { slot, t_sec: t }).then(refreshCues);
  const clear = (slot: number) => control.call("clear_cue", { slot }).then(refreshCues);
  const rename = (slot: number) => {
    const name = window.prompt("Nombre del cue:");
    if (name != null) control.call("rename_cue", { slot, name }).then(refreshCues);
  };

  // atajos 1-9 (disparar) / Shift+1-9 (set) — ignora si se escribe en un campo
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el?.isContentEditable) return;
      if (e.key >= "1" && e.key <= "9") {
        const slot = +e.key;
        if (e.shiftKey) setHere(slot); else trigger(slot);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [t]);

  const cueMenu = (e: React.MouseEvent, slot: number) => {
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY, items: [
      { label: `Set aquí (${fmtTime(t)})`, onClick: () => setHere(slot) },
      { label: "Renombrar…", onClick: () => rename(slot) },
      { type: "sep" },
      { label: "Borrar cue", danger: true, onClick: () => clear(slot) },
    ] });
  };

  return (
    <div className="cue-bar">
      <span className="cue-label">CUES</span>
      {slots.map((slot) => {
        const c = cueFor(slot);
        const on = isSet(c);
        return (
          <button key={slot} className={"cue-btn" + (on ? " on" : "")}
            onClick={() => (on ? trigger(slot) : setHere(slot))}
            onContextMenu={(e) => cueMenu(e, slot)}
            title={on ? `${c!.name} · ${fmtTime(c!.time_ms / 1000)}` : "vacío — clic para fijar aquí"}>
            <span className="cue-n">{slot}</span>
            <span className="cue-name">{on ? (c!.name || fmtTime(c!.time_ms / 1000)) : "—"}</span>
          </button>
        );
      })}
      <span style={{ flex: 1 }} />
      <span className="muted" style={{ fontSize: 10.5 }}>1-9 disparar · ⇧1-9 fijar</span>
      <button className="btn sm" style={{ color: "var(--bad)" }} onClick={() => control.call("set_blackout")}>⬛ Blackout</button>
      <ContextMenu state={menu} onClose={() => setMenu(null)} />
    </div>
  );
}
