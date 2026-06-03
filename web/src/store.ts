// store.ts — Estado global del frontend (zustand).
//   * transport: alimentado por stream.onState (30 FPS)
//   * datos cacheados (clips/fixtures/effects/sections/summary): vía control RPC,
//     refetch cuando cambia `rev` (alguien editó el modelo).
import { create } from "zustand";
import { control } from "./api/control";
import { stream, TransportState } from "./api/stream";

export type Clip = {
  id: number; track: number; start_ms: number; end_ms: number;
  effect_id: number; scope: string; color: string; layer: number;
  label: string; locked: boolean; muted: boolean; category: string;
  channel_effect_id: string | null; preset_id: string | null; params: Record<string, any>;
};
export type Fixture = {
  fixture_id: string; profile_id: string; universe: number; dmx_start: number;
  position: number[]; rotation: number[]; label: string;
  legacy_bar_idx: number | null; target_ip: string | null;
  manual_channels: Record<string, number>;
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
export type Marker = { time_ms: number; name: string; color: string };
export type Group = { name: string; bars: number[]; color: string; subgroups: string[] };

export type Tab = "timeline" | "live" | "analyzer" | "patch" | "viewer3d";

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
  selectedClipId: number | null;
  selectedFixtureId: string | null;
  clipboard: Clip | null;

  setTab: (t: Tab) => void;
  setTransport: (s: TransportState) => void;
  selectClip: (id: number | null) => void;
  setClipboard: (c: Clip | null) => void;
  selectFixture: (id: string | null) => void;
  refreshAll: () => Promise<void>;
  refreshClips: () => Promise<void>;
  refreshFixtures: () => Promise<void>;
  refreshPresets: () => Promise<void>;
  refreshCues: () => Promise<void>;
  refreshMarkers: () => Promise<void>;
  refreshSections: () => Promise<void>;
  refreshGroups: () => Promise<void>;
};

export const useStore = create<Store>((set, get) => ({
  t: 0, playing: false, duration: 0, loop: false, rec: false,
  section: "—", bar: 1, beat: 1, fps: 0, rev: -1, clipCount: 0,
  tab: "timeline",
  song: { title: "—", bpm: 120, key: "", duration: 0 },
  clips: [], fixtures: [], effects: [], channelEffects: [], sections: [], presets: [], cues: [], markers: [], groups: [],
  selectedClipId: null, selectedFixtureId: null, clipboard: null,

  setTab: (tab) => set({ tab }),
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
      }
    }
  },

  selectClip: (id) => set({ selectedClipId: id }),
  selectFixture: (id) => set({ selectedFixtureId: id }),

  refreshAll: async () => {
    const [summary, clips, fixtures, effects, chEffects, sections, presets] = await Promise.all([
      control.call("analyzer_summary").catch(() => null),
      control.call("list_clips").catch(() => ({ clips: [] })),
      control.call("list_fixtures").catch(() => ({ fixtures: [] })),
      control.call("list_effects").catch(() => ({ effects: [] })),
      control.call("list_channel_effects").catch(() => ({ effects: [] })),
      control.call("analyzer_list_sections").catch(() => ({ sections: [] })),
      control.call("list_presets").catch(() => ({ presets: [] })),
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
      sections: (sections.sections ?? []).map((s: any) => ({
        ...s, name: s.name || s.label || "—", type: s.type || "",
      })),
      presets: presets.presets ?? [],
    });
  },

  refreshClips: async () => {
    const r = await control.call("list_clips").catch(() => null);
    if (r) set({ clips: r.clips ?? [] });
  },
  refreshFixtures: async () => {
    const r = await control.call("list_fixtures").catch(() => null);
    if (r) set({ fixtures: r.fixtures ?? [] });
  },
  refreshPresets: async () => {
    const r = await control.call("list_presets").catch(() => null);
    if (r) set({ presets: r.presets ?? [] });
  },
  refreshCues: async () => {
    const r = await control.call("list_cue_points").catch(() => null);
    if (r) set({ cues: r.cues ?? [] });
  },
  refreshMarkers: async () => {
    const r = await control.call("list_markers").catch(() => null);
    if (r) set({ markers: r.markers ?? [] });
  },
  refreshSections: async () => {
    const r = await control.call("analyzer_list_sections").catch(() => null);
    if (r) set({
      sections: (r.sections ?? []).map((s: any) => ({ ...s, name: s.name || s.label || "—", type: s.type || "" })),
    });
  },
  refreshGroups: async () => {
    const r = await control.call("list_groups").catch(() => null);
    if (r) set({ groups: r.groups ?? [] });
  },
}));

// Conectar el stream al store (una vez)
stream.onState((s) => useStore.getState().setTransport(s));
