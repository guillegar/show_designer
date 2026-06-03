import { useEffect } from "react";
import { useStore, Tab } from "./store";
import { control } from "./api/control";
import { Ico } from "./icons";
import { Transport } from "./components/Transport";
import { CueBar } from "./components/CueBar";
import { TimelineView } from "./views/Timeline";
import { LiveView } from "./views/Live";
import { AnalyzerView } from "./views/Analyzer";
import { PatchView } from "./views/Patch";
import { Viewer3DView } from "./views/Viewer3D";

const TABS: { id: Tab; label: string; icon: keyof typeof Ico }[] = [
  { id: "timeline", label: "Timeline", icon: "timeline" },
  { id: "live", label: "Live · Feedback", icon: "live" },
  { id: "analyzer", label: "Analyzer", icon: "analyzer" },
  { id: "patch", label: "Patch", icon: "patch" },
  { id: "viewer3d", label: "3D Viewer", icon: "live" },
];

export function App() {
  const tab = useStore((s) => s.tab);
  const setTab = useStore((s) => s.setTab);
  const playing = useStore((s) => s.playing);
  const fps = useStore((s) => s.fps);
  const song = useStore((s) => s.song);
  const clipCount = useStore((s) => s.clipCount);
  const fixtures = useStore((s) => s.fixtures);
  const refreshAll = useStore((s) => s.refreshAll);

  useEffect(() => {
    refreshAll();
    control.onReconnect = () => refreshAll();
  }, [refreshAll]);

  // Atajos globales de transporte/edición (ignora si se escribe en un campo)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el?.isContentEditable) return;
      const st = useStore.getState();
      const k = e.key;
      if (e.code === "Space") { e.preventDefault(); control.call(st.playing ? "pause" : "play"); }
      else if (k === "Home") control.call("seek", { t_sec: 0 });
      else if (k === "End") control.call("seek", { t_sec: st.duration });
      else if (k === "ArrowLeft") control.call("seek", { t_sec: Math.max(0, st.t - (e.shiftKey ? 0.1 : 1)) });
      else if (k === "ArrowRight") control.call("seek", { t_sec: Math.min(st.duration, st.t + (e.shiftKey ? 0.1 : 1)) });
      else if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "z") { e.preventDefault(); control.call(e.shiftKey ? "redo" : "undo"); }
      else if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "y") { e.preventDefault(); control.call("redo"); }
      else if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "s") { e.preventDefault(); control.call("save_show"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const badges: Record<Tab, number | null> = {
    timeline: clipCount || null,
    live: null,
    analyzer: null,
    patch: fixtures.length || null,
    viewer3d: null,
  };

  return (
    <div className="app">
      {/* TOP BAR */}
      <div className="topbar">
        <div className="brand">
          <div className="mark" />
          <div className="name">LUC<span>ES</span></div>
        </div>
        <div className="project-pill">
          <span className="dot" />
          <span><b>{song.title}</b></span>
          <span className="bpm">{Math.round(song.bpm)} BPM{song.key ? ` · ${song.key}` : ""}</span>
        </div>
        <div className="top-spacer" />
        <div className="io-chip"><span className={"led " + (playing ? "on" : "off")} /> ART-NET · 10 univ.</div>
        <div className="io-chip">{playing ? Math.round(fps) : 0} FPS</div>
        <button className="icon-btn" title="Guardar" onClick={() => control.call("save_show")}><Ico.save width="15" /></button>
        <button className="icon-btn" title="Ajustes"><Ico.gear width="16" /></button>
      </div>

      {/* TABS */}
      <div className="tabs">
        {TABS.map((tb) => {
          const I = Ico[tb.icon];
          return (
            <button key={tb.id} className={"tab" + (tab === tb.id ? " active" : "")} onClick={() => setTab(tb.id)}>
              <I className="ti" />{tb.label}
              {badges[tb.id] != null && <span className="badge">{badges[tb.id]}</span>}
            </button>
          );
        })}
      </div>

      {/* STAGE */}
      <div className="stage">
        {tab === "timeline" && <TimelineView />}
        {tab === "live" && <LiveView />}
        {tab === "analyzer" && <AnalyzerView />}
        {tab === "patch" && <PatchView />}
        {tab === "viewer3d" && <Viewer3DView />}
      </div>

      {/* CUES (modo directo) */}
      <CueBar />

      {/* TRANSPORT */}
      <Transport />
    </div>
  );
}
