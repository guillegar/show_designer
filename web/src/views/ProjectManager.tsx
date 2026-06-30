import { useCallback, useEffect, useState } from "react";
import { control } from "../api/control";
import { stream } from "../api/stream";
import type { ProjectChangedEvent } from "../api/stream";
import { useStore } from "../store";
import { ToastContainer, useToast } from "../components/Toast";

// ── Tipos (espejo de list_projects_detailed / list_components del backend) ───
type SongMeta = {
  title: string; bpm: number | null; duration_s: number | null;
  analysis_slug: string; audio_path: string;
};
type ProjectDetailed = {
  slug: string; name: string; is_current: boolean; notes: string; created: string;
  song: SongMeta; rig: { fixture_count: number }; sequence: { clip_count: number };
  has_presets: boolean; has_autovj: boolean;
};
type RigItem = { source_slug: string; source_name: string; fixture_count: number; is_current: boolean };
type SongItem = { analysis_slug: string; title: string; bpm: number | null; duration_s: number | null; audio_path: string; used_by: string[] };
type SeqItem = { source_slug: string; source_name: string; clip_count: number; pattern_count: number; duration_ms: number | null; is_current: boolean };
type PresetItem = { source_slug: string; source_name: string; count: number; is_current: boolean };
type AutovjItem = { source_slug: string; source_name: string; rule_count: number; is_current: boolean };
type Components = {
  current: string | null;
  rigs: RigItem[]; songs: SongItem[]; sequences: SeqItem[];
  presets: PresetItem[]; autovj: AutovjItem[];
};
type AnalysisItem = { analysis_slug: string; title: string; bpm: number | null; duration_s: number | null };

const fmtDur = (s: number | null | undefined) => {
  if (s == null) return "—";
  const m = Math.floor(s / 60), ss = Math.round(s % 60);
  return `${m}:${ss.toString().padStart(2, "0")}`;
};
const fmtBpm = (b: number | null | undefined) => (b == null ? "" : ` · ${Math.round(b)} BPM`);

type AddToast = (m: string, t?: "info" | "success" | "error" | "warning") => void;

// ── Editar proyecto: nombre, notas, análisis ─────────────────────────────────
function EditProjectModal({ project, analyses, onClose, onDone, addToast }: {
  project: ProjectDetailed; analyses: AnalysisItem[];
  onClose: () => void; onDone: () => void; addToast: AddToast;
}) {
  const [name, setName] = useState(project.name);
  const [notes, setNotes] = useState(project.notes);
  const [analysisSlug, setAnalysisSlug] = useState(project.song.analysis_slug);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!name.trim()) { addToast("Nombre requerido", "warning"); return; }
    setBusy(true);
    try {
      const params: any = {
        slug: project.slug,
        name: name.trim(),
        notes: notes.trim(),
      };
      if (analysisSlug !== project.song.analysis_slug) {
        params.analysis_slug = analysisSlug;
      }
      const r: any = await control.call("update_project", params);
      if (r?.ok) {
        addToast("✓ Proyecto actualizado", "success");
        onDone();
      } else {
        addToast(r?.error || "Error al guardar", "error");
      }
    } catch {
      addToast("Error de red", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="pm-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="pm-modal">
        <div className="pm-modal-hdr"><strong>Editar "{project.name}"</strong><button className="x" onClick={onClose}>×</button></div>
        <div className="pm-modal-body">
          <label className="pm-field">
            <span>Nombre</span>
            <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </label>
          <label className="pm-field">
            <span>Notas</span>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} style={{ minHeight: "60px", fontFamily: "inherit" }} />
          </label>
          <label className="pm-field">
            <span>Canción (análisis)</span>
            <select value={analysisSlug} onChange={(e) => setAnalysisSlug(e.target.value)}>
              <option value="">— ninguno —</option>
              {analyses.map((a) => (
                <option key={a.analysis_slug} value={a.analysis_slug}>
                  {a.title}{a.bpm ? ` (${Math.round(a.bpm)} BPM)` : ""} · {fmtDur(a.duration_s)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="pm-modal-ftr">
          <button className="btn sm ghost" onClick={onClose}>Cancelar</button>
          <button className="btn sm" disabled={busy || !name.trim()} onClick={save}>
            {busy ? "Guardando…" : "Guardar"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Compositor: crear un proyecto eligiendo el origen de cada componente ─────
function ComposerModal({ projects, onClose, onDone, addToast }: {
  projects: ProjectDetailed[]; onClose: () => void;
  onDone: (slug: string, load: boolean) => void; addToast: AddToast;
}) {
  const [name, setName] = useState("");
  const [songFrom, setSongFrom] = useState("");
  const [rigFrom, setRigFrom] = useState("");
  const [seqFrom, setSeqFrom] = useState("");
  const [presetsFrom, setPresetsFrom] = useState("");
  const [autovjFrom, setAutovjFrom] = useState("");
  const [loadAfter, setLoadAfter] = useState(true);
  const [busy, setBusy] = useState(false);

  const opt = (sel: string, set: (v: string) => void, label: string, withSong?: boolean) => (
    <label className="pm-field">
      <span>{label}</span>
      <select value={sel} onChange={(e) => set(e.target.value)}>
        <option value="">— vacío / por defecto —</option>
        {projects.map((p) => (
          <option key={p.slug} value={p.slug}>
            {p.name}{withSong && p.song.title ? ` (${p.song.title})` : ""}
          </option>
        ))}
      </select>
    </label>
  );

  const create = async () => {
    if (!name.trim()) { addToast("Pon un nombre", "warning"); return; }
    setBusy(true);
    try {
      const r: any = await control.call("create_project_from_components", {
        name: name.trim(), song_from: songFrom, rig_from: rigFrom,
        sequence_from: seqFrom, presets_from: presetsFrom, autovj_from: autovjFrom,
      });
      if (r?.ok) { onDone(r.slug, loadAfter); }
      else addToast(r?.error || "No se pudo crear", "error");
    } catch { addToast("Error al crear", "error"); }
    finally { setBusy(false); }
  };

  return (
    <div className="pm-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="pm-modal">
        <div className="pm-modal-hdr"><strong>Nuevo proyecto</strong><button className="x" onClick={onClose}>×</button></div>
        <div className="pm-modal-body">
          <label className="pm-field"><span>Nombre</span>
            <input value={name} autoFocus onChange={(e) => setName(e.target.value)} placeholder="Mi show nuevo" />
          </label>
          <div className="pm-hint">Elige de qué proyecto sale cada componente (o déjalo vacío):</div>
          {opt(songFrom, setSongFrom, "Canción (audio + análisis)", true)}
          {opt(rigFrom, setRigFrom, "Rig (fixtures + posiciones 3D)")}
          {opt(seqFrom, setSeqFrom, "Secuencia de efectos")}
          {opt(presetsFrom, setPresetsFrom, "Presets")}
          {opt(autovjFrom, setAutovjFrom, "Auto-VJ")}
          <label className="pm-check"><input type="checkbox" checked={loadAfter} onChange={(e) => setLoadAfter(e.target.checked)} /> Cargar al crear</label>
        </div>
        <div className="pm-modal-ftr">
          <button className="btn sm ghost" onClick={onClose}>Cancelar</button>
          <button className="btn sm" disabled={busy} onClick={create}>{busy ? "Creando…" : "Crear"}</button>
        </div>
      </div>
    </div>
  );
}

// ── Duplicar un proyecto, opcionalmente cambiando un componente ──────────────
function DuplicateModal({ from, projects, onClose, onDone, addToast }: {
  from: ProjectDetailed; projects: ProjectDetailed[]; onClose: () => void;
  onDone: (slug: string) => void; addToast: AddToast;
}) {
  const [name, setName] = useState(`${from.name} (copia)`);
  const [comp, setComp] = useState("");
  const [src, setSrc] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      const params: any = { from_slug: from.slug, new_name: name.trim() };
      if (comp && src) params.swap = { component: comp, source_slug: src };
      const r: any = await control.call("duplicate_project", params);
      if (r?.ok) onDone(r.slug);
      else addToast(r?.error || "No se pudo duplicar", "error");
    } catch { addToast("Error al duplicar", "error"); }
    finally { setBusy(false); }
  };

  return (
    <div className="pm-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="pm-modal">
        <div className="pm-modal-hdr"><strong>Duplicar “{from.name}”</strong><button className="x" onClick={onClose}>×</button></div>
        <div className="pm-modal-body">
          <label className="pm-field"><span>Nombre de la copia</span>
            <input value={name} autoFocus onChange={(e) => setName(e.target.value)} />
          </label>
          <div className="pm-hint">Opcional: cambiar un componente por el de otro proyecto.</div>
          <label className="pm-field"><span>Componente a cambiar</span>
            <select value={comp} onChange={(e) => setComp(e.target.value)}>
              <option value="">— ninguno (copia exacta) —</option>
              <option value="song">Canción</option>
              <option value="rig">Rig</option>
              <option value="sequence">Secuencia</option>
              <option value="presets">Presets</option>
              <option value="autovj">Auto-VJ</option>
            </select>
          </label>
          {comp && (
            <label className="pm-field"><span>Tomarlo de</span>
              <select value={src} onChange={(e) => setSrc(e.target.value)}>
                <option value="">— elegir proyecto —</option>
                {projects.filter((p) => p.slug !== from.slug).map((p) => (
                  <option key={p.slug} value={p.slug}>{p.name}</option>
                ))}
              </select>
            </label>
          )}
        </div>
        <div className="pm-modal-ftr">
          <button className="btn sm ghost" onClick={onClose}>Cancelar</button>
          <button className="btn sm" disabled={busy || (!!comp && !src)} onClick={run}>{busy ? "Duplicando…" : "Duplicar"}</button>
        </div>
      </div>
    </div>
  );
}

// ── Vista principal ──────────────────────────────────────────────────────────
export function ProjectManagerView() {
  const { toasts, addToast, dismissToast } = useToast();
  const refreshAll = useStore((s) => s.refreshAll);
  const [projects, setProjects] = useState<ProjectDetailed[]>([]);
  const [comp, setComp] = useState<Components | null>(null);
  const [current, setCurrent] = useState<string>("");
  const [loadingSlug, setLoadingSlug] = useState<string | null>(null);
  const [swapOpen, setSwapOpen] = useState(false);
  const [composer, setComposer] = useState(false);
  const [dupFrom, setDupFrom] = useState<ProjectDetailed | null>(null);
  const [editFrom, setEditFrom] = useState<ProjectDetailed | null>(null);
  const [analyses, setAnalyses] = useState<AnalysisItem[]>([]);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    const [pr, co, ana] = await Promise.all([
      control.call("list_projects_detailed").catch(() => null),
      control.call("list_components").catch(() => null),
      control.call("list_available_analyses").catch(() => null),
    ]);
    if (pr?.ok) { setProjects(pr.projects ?? []); setCurrent(pr.current ?? ""); }
    if (co?.ok) setComp(co as Components);
    if (ana?.ok) setAnalyses(ana.analyses ?? []);
  }, []);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => stream.onProjectChanged((e: ProjectChangedEvent) => {
    setCurrent(e.slug); setLoadingSlug(null); reload();
  }), [reload]);

  const doLoad = (slug: string) => {
    if (slug === current || loadingSlug) return;
    setLoadingSlug(slug);
    control.call("switch_project", { slug }).then((r: any) => {
      if (!r?.ok) { setLoadingSlug(null); addToast(r?.error || "No se pudo cargar", "error"); }
    }).catch(() => { setLoadingSlug(null); addToast("Error al cargar", "error"); });
  };

  const applyComponent = async (method: string, params: any, label: string) => {
    if (busy) return;
    setBusy(true);
    try {
      const r: any = await control.call(method, params);
      if (r?.ok) { addToast(`✓ ${label} aplicado al proyecto actual`, "success"); await refreshAll(); await reload(); }
      else addToast(r?.error || "Error", "error");
    } catch { addToast("Error de red", "error"); }
    finally { setBusy(false); }
  };

  const isCur = (slug: string) => slug === current;

  return (
    <div className="pm-view">
      <div className="pm-head">
        <div>
          <h2 className="pm-title">Proyectos</h2>
          <div className="pm-sub">Activo: <b>{projects.find((p) => isCur(p.slug))?.name ?? current ?? "—"}</b></div>
        </div>
        <button className="btn sm" onClick={() => setComposer(true)}>+ Nuevo proyecto</button>
      </div>

      {/* GALERÍA */}
      <div className="pm-grid">
        {projects.map((p) => (
          <div key={p.slug} className={"pm-card" + (isCur(p.slug) ? " current" : "")}>
            <div className="pm-card-top">
              <strong className="pm-name">{p.name}</strong>
              {isCur(p.slug) && <span className="pm-badge cur">activo</span>}
            </div>
            <div className="pm-song">♪ {p.song.title}{fmtBpm(p.song.bpm)} · {fmtDur(p.song.duration_s)}</div>
            <div className="pm-meta">
              <span title="fixtures del rig">🎛 {p.rig.fixture_count}</span>
              <span title="clips de la secuencia">🎬 {p.sequence.clip_count}</span>
              {p.has_presets && <span className="pm-badge">presets</span>}
              {p.has_autovj && <span className="pm-badge">auto-VJ</span>}
            </div>
            {p.notes && <div className="pm-notes">{p.notes}</div>}
            <div className="pm-card-actions">
              <button className="btn sm" disabled={isCur(p.slug) || loadingSlug === p.slug}
                onClick={() => doLoad(p.slug)}>
                {loadingSlug === p.slug ? "Cargando…" : isCur(p.slug) ? "Cargado" : "Cargar"}
              </button>
              <button className="btn sm ghost" title="Editar" onClick={() => setEditFrom(p)}>⚙ Editar…</button>
              <button className="btn sm ghost" onClick={() => setDupFrom(p)}>Duplicar…</button>
            </div>
          </div>
        ))}
        {projects.length === 0 && <div className="pm-empty">No hay proyectos.</div>}
      </div>

      {/* INTERCAMBIAR COMPONENTES */}
      <div className="pm-swap">
        <button className="pm-swap-hdr" onClick={() => setSwapOpen((v) => !v)}>
          {swapOpen ? "▼" : "▶"} Intercambiar componentes en el proyecto activo
        </button>
        {swapOpen && comp && (
          <div className="pm-swap-body">
            <ComponentList title="Rigs" items={comp.rigs.map((r) => ({
              key: r.source_slug, is_current: r.is_current, name: r.source_name,
              detail: `${r.fixture_count} fixtures`,
              onApply: () => applyComponent("apply_rig", { from_slug: r.source_slug }, "Rig"),
            }))} busy={busy} />
            <ComponentList title="Secuencias" items={comp.sequences.map((s) => ({
              key: s.source_slug, is_current: s.is_current, name: s.source_name,
              detail: `${s.clip_count} clips${s.pattern_count ? ` · ${s.pattern_count} patterns` : ""}`,
              onApply: () => applyComponent("load_sequence", { from_slug: s.source_slug }, "Secuencia"),
            }))} busy={busy} />
            <ComponentList title="Presets" items={comp.presets.map((p) => ({
              key: p.source_slug, is_current: p.is_current, name: p.source_name,
              detail: `${p.count} presets`,
              onApply: () => applyComponent("apply_presets", { from_slug: p.source_slug }, "Presets"),
            }))} busy={busy} />
            <ComponentList title="Auto-VJ" items={comp.autovj.map((a) => ({
              key: a.source_slug, is_current: a.is_current, name: a.source_name,
              detail: `${a.rule_count} reglas`,
              onApply: () => applyComponent("apply_autovj", { from_slug: a.source_slug }, "Auto-VJ"),
            }))} busy={busy} />
            <ComponentList title="Canciones" items={comp.songs.map((s) => ({
              key: s.analysis_slug, is_current: s.analysis_slug === projects.find((p) => isCur(p.slug))?.song.analysis_slug,
              name: s.title, detail: `${fmtBpm(s.bpm).replace(" · ", "")} ${fmtDur(s.duration_s)}${s.used_by.length ? "" : " · sin usar"}`,
              onApply: () => applyComponent("apply_song", { analysis_slug: s.analysis_slug, audio_path: s.audio_path }, "Canción"),
            }))} busy={busy} note="Cambiar la canción re-temporiza el show (los beats difieren)." />
          </div>
        )}
      </div>

      {editFrom && (
        <EditProjectModal project={editFrom} analyses={analyses} addToast={addToast}
          onClose={() => setEditFrom(null)}
          onDone={() => { setEditFrom(null); reload(); }} />
      )}
      {composer && (
        <ComposerModal projects={projects} addToast={addToast} onClose={() => setComposer(false)}
          onDone={(slug, load) => { setComposer(false); addToast("✓ Proyecto creado", "success"); reload(); if (load) doLoad(slug); }} />
      )}
      {dupFrom && (
        <DuplicateModal from={dupFrom} projects={projects} addToast={addToast} onClose={() => setDupFrom(null)}
          onDone={(slug) => { setDupFrom(null); addToast("✓ Proyecto duplicado", "success"); reload(); void slug; }} />
      )}

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}

type CompRow = { key: string; is_current?: boolean; name: string; detail: string; onApply: () => void };
function ComponentList({ title, items, busy, note }: { title: string; items: CompRow[]; busy: boolean; note?: string }) {
  return (
    <div className="pm-clist">
      <div className="pm-clist-hdr">{title}</div>
      {note && <div className="pm-clist-note">{note}</div>}
      <div className="pm-clist-rows">
        {items.map((it) => (
          <div key={it.key} className={"pm-crow" + (it.is_current ? " current" : "")}>
            <div className="pm-crow-info">
              <span className="pm-crow-name">{it.name}{it.is_current ? " (actual)" : ""}</span>
              <span className="pm-crow-detail">{it.detail}</span>
            </div>
            <button className="btn xs ghost" disabled={busy || it.is_current} onClick={it.onApply}>Aplicar</button>
          </div>
        ))}
        {items.length === 0 && <div className="pm-clist-empty">—</div>}
      </div>
    </div>
  );
}
