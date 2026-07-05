// store.ts — Estado global del frontend (zustand).
//   * transport: alimentado por stream.onState (30 FPS)
//   * datos cacheados (clips/fixtures/effects/sections/summary): vía control RPC,
//     refetch cuando cambia `rev` (alguien editó el modelo).
import { create } from "zustand";
import { control } from "./api/control";
import { stream, TransportState } from "./api/stream";
import type { Pattern, PatternInstance } from "./api/types";

// Contadores de peticiones para descartar respuestas desordenadas.
let _clipsReqToken = 0;
let _patternsReqToken = 0;
let _patternInstancesReqToken = 0;

export type Clip = {
  id: string; uid: string; track: number; start_ms: number; end_ms: number;
  effect_id: number; scope: string; color: string; layer: number;
  label: string; locked: boolean; muted: boolean; category: string;
  channel_effect_id: string | null; preset_id: string | null; params: Record<string, any>;
  param_links: Record<string, any>[]; events: Record<string, any>[];
  channel_effects: Array<{ id: string; params: Record<string, any> }>;
};
export type Fixture = {
  fixture_id: string; profile_id: string; universe: number; dmx_start: number;
  position: number[]; rotation: number[]; label: string;
  legacy_bar_idx: number | null; target_ip: string | null;
  manual_channels: Record<string, number>;
  patch_x?: number | null; patch_y?: number | null;
  kind_override?: string | null;
  kind?: string | null; // D1: icon by type (from profile or kind_override)
  notes?: string | null;
  channel_map?: Array<{ch: number; role: string}> | null;
  height_m?: number | null;
};
export type EffectInfo = { id: number; name: string; family: string; description: string };
export type Preset = {
  preset_id: string; name: string; kind: string; base_effect_id: number;
  channel_effect_id: string | null; category: string;
  family: string; params: Record<string, any>; color: string; scope: string;
};
export type ChannelEffectInfo = {
  effect_id: string; name: string; category: string;
  required_channels: string[]; default_params: Record<string, any>;
};
export type Section = { idx?: number; start: number; end: number; name: string; type: string; energy?: number };
export type Cue = { slot: number; time_ms: number; name: string; color: string };
export type MarkerCategory = "intro" | "verso" | "estribillo" | "bridge" | "outro" | "custom";
export type Marker = { time_ms: number; name: string; color: string; category: MarkerCategory };
export type Group = { name: string; bars: number[]; color: string; subgroups: string[] };

export type Tab = "projects" | "timeline" | "live" | "analyzer" | "patch" | "viewer3d" | "preview";

// ── Envelopes de respuesta RPC (tipado de control.call; revisión 2026-06-30) ──
// La sección puede llegar con `label` en vez de `name` (analyzer legacy).
type RawSection = Partial<Section> & { label?: string; start: number; end: number };
type SummaryResponse = {
  available?: boolean;
  summary?: { file?: string; bpm?: number; duration_s?: number;
              key?: string | { tonic?: string; mode?: string } };
};

// Familia de efecto → variable CSS de color (design tokens)
export const FAM_COLOR: Record<string, string> = {
  flash: "var(--fam-flash)", wave: "var(--fam-wave)", gradient: "var(--fam-gradient)",
  pattern: "var(--fam-pattern)", spectral: "var(--fam-color)", color: "var(--fam-color)",
  ring: "var(--fam-wave)", "": "var(--txt-3)",
};
export function famColor(fam: string): string {
  return FAM_COLOR[fam] ?? "var(--txt-3)";
}

type Store = {
  // transport
  t: number; playing: boolean; duration: number; loop: boolean; rec: boolean;
  section: string; bar: number; beat: number; fps: number; rev: number; clipCount: number;
  // ui
  tab: Tab;
  // datos
  song: { title: string; bpm: number; key: string; duration: number };
  clips: Clip[];
  fixtures: Fixture[];
  effects: EffectInfo[];
  channelEffects: ChannelEffectInfo[];
  sections: Section[];
  presets: Preset[];
  cues: Cue[];
  markers: Marker[];
  groups: Group[];
  // selección compartida
  selectedClipId: string | null;
  selectedFixtureId: string | null;
  clipboard: Clip | null;
  // A3 — Patterns
  patterns: Pattern[];
  patternInstances: PatternInstance[];
  selectedPatternInstanceId: string | null;
  // L3 — rol multiusuario
  role: "operator" | "assistant" | "anonymous";

  setTab: (t: Tab) => void;
  setRole: (r: "operator" | "assistant" | "anonymous") => void;
  setTransport: (s: TransportState) => void;
  selectClip: (id: string | null) => void;
  setClipboard: (c: Clip | null) => void;
  selectFixture: (id: string | null) => void;
  selectPatternInstance: (id: string | null) => void;
  refreshAll: () => Promise<void>;
  refreshClips: () => Promise<void>;
  refreshFixtures: () => Promise<void>;
  refreshPresets: () => Promise<void>;
  refreshCues: () => Promise<void>;
  refreshMarkers: () => Promise<void>;
  refreshSections: () => Promise<void>;
  refreshGroups: () => Promise<void>;
  refreshPatterns: () => Promise<void>;
  refreshPatternInstances: () => Promise<void>;
  applyPatternMovesOptimistic: (
    calls: Array<{ instance_uid: string; new_start_ms?: number; new_track_offset?: number }>
  ) => void;
};

export const useStore = create<Store>((set, get) => ({
  t: 0, playing: false, duration: 0, loop: false, rec: false,
  section: "—", bar: 1, beat: 1, fps: 0, rev: -1, clipCount: 0,
  tab: "timeline",
  song: { title: "—", bpm: 120, key: "", duration: 0 },
  clips: [], fixtures: [], effects: [], channelEffects: [], sections: [], presets: [], cues: [], markers: [], groups: [],
  selectedClipId: null, selectedFixtureId: null, clipboard: null,
  patterns: [], patternInstances: [], selectedPatternInstanceId: null,
  role: "operator",

  setTab: (tab) => set({ tab }),
  setRole: (role) => set({ role }),
  setClipboard: (c) => set({ clipboard: c }),

  setTransport: (s) => {
    const prevRev = get().rev;
    set({
      t: s.t, playing: s.playing, duration: s.duration, loop: s.loop, rec: s.rec,
      section: s.section, bar: s.bar, beat: s.beat, fps: s.fps, clipCount: s.clip_count,
    });
    if (s.rev !== prevRev) {
      set({ rev: s.rev });
      if (prevRev !== -1) {
        // el modelo cambió (edición por UI o por Claude/MCP) → refetch listas
        get().refreshClips();
        get().refreshFixtures();
        get().refreshPresets();
        get().refreshCues();
        get().refreshMarkers();
        get().refreshPatterns();
        get().refreshPatternInstances();
      }
    }
  },

  selectClip: (id) => set({ selectedClipId: id }),
  selectFixture: (id) => set({ selectedFixtureId: id }),
  selectPatternInstance: (id) => set({ selectedPatternInstanceId: id }),

  refreshAll: async () => {
    const [summary, clips, fixtures, effects, chEffects, sections, presets] = await Promise.all([
      control.call<SummaryResponse>("analyzer_summary").catch(() => null),
      control.call<{ clips: Clip[] }>("list_clips").catch(() => ({ clips: [] as Clip[] })),
      control.call<{ fixtures: Fixture[] }>("list_fixtures").catch(() => ({ fixtures: [] as Fixture[] })),
      control.call<{ effects: EffectInfo[] }>("list_effects").catch(() => ({ effects: [] as EffectInfo[] })),
      control.call<{ effects: ChannelEffectInfo[] }>("list_channel_effects").catch(() => ({ effects: [] as ChannelEffectInfo[] })),
      control.call<{ sections: RawSection[] }>("analyzer_list_sections").catch(() => ({ sections: [] as RawSection[] })),
      control.call<{ presets: Preset[] }>("list_presets").catch(() => ({ presets: [] as Preset[] })),
    ]);
    get().refreshCues();
    get().refreshMarkers();
    get().refreshGroups();
    let song = get().song;
    if (summary?.available && summary.summary) {
      const su = summary.summary;
      const key = su.key
        ? (typeof su.key === "string" ? su.key : `${su.key.tonic ?? ""} ${su.key.mode ?? ""}`.trim())
        : "";
      const title = (su.file || "Show").replace(/\.[^.]+$/, "");
      song = { title, bpm: su.bpm ?? 120, key, duration: su.duration_s ?? 0 };
    }
    set({
      song,
      clips: clips.clips ?? [],
      fixtures: fixtures.fixtures ?? [],
      effects: effects.effects ?? [],
      channelEffects: chEffects.effects ?? [],
      sections: (sections.sections ?? []).map((s) => ({
        ...s, name: s.name || s.label || "—", type: s.type || "",
      })) as Section[],
      presets: presets.presets ?? [],
    });
  },

  refreshClips: async () => {
    // Token monótono: si llegan varias respuestas de list_clips desordenadas
    // (p.ej. una disparada por `rev` del stream mientras se comitea un move),
    // solo aplica la última pedida. Evita que una respuesta vieja pise una
    // posición recién movida.
    const token = ++_clipsReqToken;
    const r = await control.call<{ clips: Clip[] }>("list_clips").catch(() => null);
    if (r && token === _clipsReqToken) set({ clips: r.clips ?? [] });
  },
  refreshFixtures: async () => {
    const r = await control.call<{ fixtures: Fixture[] }>("list_fixtures").catch(() => null);
    if (r) set({ fixtures: r.fixtures ?? [] });
  },
  refreshPresets: async () => {
    const r = await control.call<{ presets: Preset[] }>("list_presets").catch(() => null);
    if (r) set({ presets: r.presets ?? [] });
  },
  refreshCues: async () => {
    const r = await control.call<{ cues: Cue[] }>("list_cue_points").catch(() => null);
    if (r) set({ cues: r.cues ?? [] });
  },
  refreshMarkers: async () => {
    const r = await control.call<{ markers: Marker[] }>("list_markers").catch(() => null);
    if (r) set({ markers: r.markers ?? [] });
  },
  refreshSections: async () => {
    const r = await control.call<{ sections: RawSection[] }>("analyzer_list_sections").catch(() => null);
    if (r) set({
      sections: (r.sections ?? []).map((s) => ({ ...s, name: s.name || s.label || "—", type: s.type || "" })) as Section[],
    });
  },
  refreshGroups: async () => {
    const r = await control.call<{ groups: Group[] }>("list_groups").catch(() => null);
    if (r) set({ groups: r.groups ?? [] });
  },

  // A3 — Patterns
  refreshPatterns: async () => {
    const token = ++_patternsReqToken;
    const r = await control.call<{ patterns: Pattern[] }>("list_patterns").catch(() => null);
    if (r && token === _patternsReqToken) set({ patterns: r.patterns ?? [] });
  },
  refreshPatternInstances: async () => {
    const token = ++_patternInstancesReqToken;
    const r = await control.call<{ instances: PatternInstance[] }>("list_pattern_instances").catch(() => null);
    if (r && token === _patternInstancesReqToken) set({ patternInstances: r.instances ?? [] });
  },
  applyPatternMovesOptimistic: (calls) => {
    const byId = new Map(calls.map((p) => [p.instance_uid, p]));
    useStore.setState((s) => ({
      patternInstances: s.patternInstances.map((inst) => {
        const p = byId.get(inst.uid);
        if (!p) return inst;
        return {
          ...inst,
          ...(p.new_start_ms != null ? { start_ms: Math.max(0, Math.round(p.new_start_ms)) } : {}),
          ...(p.new_track_offset != null ? { track_offset: p.new_track_offset } : {}),
        };
      }),
    }));
  },
}));

// Conectar el stream al store (una vez)
stream.onState((s) => useStore.getState().setTransport(s));
