import { useEffect, useState, useRef } from "react";
import { useStore, Tab } from "./store";
import { control } from "./api/control";
import { stream } from "./api/stream";
import type { ProjectChangedEvent } from "./api/stream";
import { Ico } from "./icons";
import { Transport } from "./components/Transport";
import { CueBar } from "./components/CueBar";
import { TimelineView } from "./views/Timeline";
import { LiveView } from "./views/Live";
import { AnalyzerView } from "./views/Analyzer";
import { PatchView } from "./views/Patch";
import { Viewer3DView } from "./views/Viewer3D";
import { PreviewView } from "./views/Preview";

type ProjectInfo = { slug: string; name: string; audio_path: string };

function ProjectSwitcher({ current }: { current: string }) {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const refreshAll = useStore((s) => s.refreshAll);

  useEffect(() => {
    control.call("list_projects").then((r: any) => {
      setProjects(r?.projects ?? []);
    }).catch(() => {});
  }, [current]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const doSwitch = (slug: string) => {
    if (slug === current || switching) return;
    setSwitching(slug);
    setOpen(false);
    control.call("switch_project", { slug }).catch(() => setSwitching(null));
  };

  if (projects.length <= 1) return null;
  return (
    <div ref={ref} style={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
      <button
        className="btn sm ghost"
        style={{ fontSize: 11, padding: "2px 8px", marginLeft: 6 }}
        onClick={() => setOpen((v) => !v)}
        title="Cambiar proyecto"
      >
        {switching ? "Cargando…" : "▾"}
      </button>
      {open && !switching && (
        <div style={{
          position: "absolute", top: "calc(100% + 4px)", left: 0, zIndex: 200,
          background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 6,
          minWidth: 160, padding: 4, boxShadow: "0 4px 16px rgba(0,0,0,.4)",
        }}>
          {projects.map((p) => (
            <button
              key={p.slug}
              onClick={() => doSwitch(p.slug)}
              style={{
                display: "block", width: "100%", textAlign: "left",
                padding: "5px 10px", fontSize: 12, borderRadius: 4, border: "none",
                background: p.slug === current ? "var(--acc)" : "transparent",
                color: p.slug === current ? "#fff" : "var(--txt-1)",
                cursor: p.slug === current ? "default" : "pointer",
              }}
            >{p.name}</button>
          ))}
        </div>
      )}
    </div>
  );
}

const TABS: { id: Tab; label: string; icon: keyof typeof Ico }[] = [
  { id: "timeline", label: "Timeline", icon: "timeline" },
  { id: "live", label: "Live · Feedback", icon: "live" },
  { id: "analyzer", label: "Analyzer", icon: "analyzer" },
  { id: "patch", label: "Patch", icon: "patch" },
  { id: "viewer3d", label: "3D Viewer", icon: "live" },
  { id: "preview", label: "Preview", icon: "analyzer" },
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
  const [currentSlug, setCurrentSlug] = useState<string>("");
  const [switching, setSwitching] = useState(false);

  useEffect(() => {
    refreshAll();
    control.onReconnect = () => refreshAll();
    control.call("list_projects").then((r: any) => {
      setCurrentSlug(r?.current ?? "");
    }).catch(() => {});
  }, [refreshAll]);

  // Reaccionar al evento project_changed: refrescar todo el estado
  useEffect(() => {
    return stream.onProjectChanged((e: ProjectChangedEvent) => {
      setCurrentSlug(e.slug);
      setSwitching(false);
      refreshAll();
    });
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
    preview: null,
  };

  return (
    <div className="app">
      {/* Overlay de cambio de proyecto */}
      {switching && (
        <div style={{
          position: "fixed", inset: 0, zIndex: 9999,
          background: "rgba(10,12,16,.7)", display: "flex",
          alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 12,
        }}>
          <div style={{ width: 40, height: 40, border: "3px solid var(--acc)", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
          <span style={{ color: "var(--txt-1)", fontSize: 14 }}>Cargando proyecto…</span>
        </div>
      )}
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
          <ProjectSwitcher current={currentSlug} />
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
        {tab === "preview" && <PreviewView />}
      </div>

      {/* CUES (modo directo) */}
      <CueBar />

      {/* TRANSPORT */}
      <Transport />
    </div>
  );
}
