// stream.ts — Cliente del stream en vivo (/ws/stream).
// Recibe:
//   - binario: frame RGB (NUM_BARS*LEDS*3 = 2790 bytes) → latestFrame
//   - texto JSON: {type:"state",...} y {type:"dmx",fixtures:{...}}
// Los frames NO pasan por React state (30 FPS): los componentes canvas leen
// `latestFrame` en su propio requestAnimationFrame. El estado de transporte sí
// se emite a los suscriptores (la barra de transporte se redibuja con él).

export const NUM_BARS = 10;
export const LEDS = 93;

export type TempoSyncState = {
  mode: "off" | "link" | "midi_clock";
  bpm: number;
  beat_phase: number;
  midi_device: string | null;
  synced: boolean;
};

export type TransportState = {
  type: "state";
  t: number;
  playing: boolean;
  duration: number;
  loop: boolean;
  rec: boolean;
  section: string;
  bar: number;
  beat: number;
  fps: number;
  rev: number;
  clip_count: number;
  tempo_sync?: TempoSyncState;
};

export type DmxState = Record<string, Record<string, number>>;

function wsUrl(path: string): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${path}`;
}

export type RenderProgressEvent = { pct: number; done?: boolean };
export type ExportProgressEvent = { pct: number; done?: boolean };
export type AutosaveAvailableEvent = { type: "autosave_available"; path: string; ts: string; filename: string };
export type LiveStateChangedEvent = { type: "live_state_changed"; slots: unknown[]; active: string[]; armed: string[] };
export type CueChangedEvent = { type: "cue_changed"; active_uid: string | null; fade_pct: number; next_uid: string | null };
export type BlackoutChangedEvent = { type: "blackout_changed"; enabled: boolean };
export type ProjectChangedEvent = { type: "project_changed"; slug: string; name: string; clips: number; duration_ms: number };

class StreamClient {
  latestFrame: Uint8Array | null = null;
  latestDmx: DmxState = {};
  private ws: WebSocket | null = null;
  private stateSubs = new Set<(s: TransportState) => void>();
  private dmxSubs = new Set<(d: DmxState) => void>();
  private renderProgressSubs = new Set<(e: RenderProgressEvent) => void>();
  private exportProgressSubs = new Set<(e: ExportProgressEvent) => void>();
  private autosaveSubs = new Set<(e: AutosaveAvailableEvent) => void>();
  private liveStateSubs = new Set<(e: LiveStateChangedEvent) => void>();
  private cueChangedSubs = new Set<(e: CueChangedEvent) => void>();
  private blackoutChangedSubs = new Set<(e: BlackoutChangedEvent) => void>();
  private projectChangedSubs = new Set<(e: ProjectChangedEvent) => void>();

  constructor() {
    this.connect();
  }

  private connect() {
    const ws = new WebSocket(wsUrl("/ws/stream"));
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onmessage = (e) => {
      if (e.data instanceof ArrayBuffer) {
        this.latestFrame = new Uint8Array(e.data);
        return;
      }
      let m: any;
      try {
        m = JSON.parse(e.data);
      } catch {
        return;
      }
      if (m.type === "state") {
        for (const f of this.stateSubs) f(m as TransportState);
      } else if (m.type === "dmx") {
        this.latestDmx = m.fixtures || {};
        for (const f of this.dmxSubs) f(this.latestDmx);
      } else if (m.type === "render_progress") {
        for (const f of this.renderProgressSubs) f({ pct: m.pct, done: m.done });
      } else if (m.type === "export_progress") {
        for (const f of this.exportProgressSubs) f({ pct: m.pct, done: m.done });
      } else if (m.type === "autosave_available") {
        for (const f of this.autosaveSubs) f(m as AutosaveAvailableEvent);
      } else if (m.type === "live_state_changed") {
        for (const f of this.liveStateSubs) f(m as LiveStateChangedEvent);
      } else if (m.type === "cue_changed") {
        for (const f of this.cueChangedSubs) f(m as CueChangedEvent);
      } else if (m.type === "blackout_changed") {
        for (const f of this.blackoutChangedSubs) f(m as BlackoutChangedEvent);
      } else if (m.type === "project_changed") {
        for (const f of this.projectChangedSubs) f(m as ProjectChangedEvent);
      }
    };
    ws.onclose = () => setTimeout(() => this.connect(), 1000);
    ws.onerror = () => ws.close();
  }

  onState(fn: (s: TransportState) => void): () => void {
    this.stateSubs.add(fn);
    return () => this.stateSubs.delete(fn);
  }
  onDmx(fn: (d: DmxState) => void): () => void {
    this.dmxSubs.add(fn);
    return () => this.dmxSubs.delete(fn);
  }
  onRenderProgress(fn: (e: RenderProgressEvent) => void): () => void {
    this.renderProgressSubs.add(fn);
    return () => this.renderProgressSubs.delete(fn);
  }
  onExportProgress(fn: (e: ExportProgressEvent) => void): () => void {
    this.exportProgressSubs.add(fn);
    return () => this.exportProgressSubs.delete(fn);
  }
  onBlackoutChanged(fn: (e: BlackoutChangedEvent) => void): () => void {
    this.blackoutChangedSubs.add(fn);
    return () => this.blackoutChangedSubs.delete(fn);
  }
  onAutosaveAvailable(fn: (e: AutosaveAvailableEvent) => void): () => void {
    this.autosaveSubs.add(fn);
    return () => this.autosaveSubs.delete(fn);
  }
  onLiveStateChanged(fn: (e: LiveStateChangedEvent) => void): () => void {
    this.liveStateSubs.add(fn);
    return () => this.liveStateSubs.delete(fn);
  }
  onCueChanged(fn: (e: CueChangedEvent) => void): () => void {
    this.cueChangedSubs.add(fn);
    return () => this.cueChangedSubs.delete(fn);
  }
  onProjectChanged(fn: (e: ProjectChangedEvent) => void): () => void {
    this.projectChangedSubs.add(fn);
    return () => this.projectChangedSubs.delete(fn);
  }

  // Color RGB de un LED concreto del último frame (para canvas Live/Patch)
  ledRGB(bar: number, led: number): [number, number, number] {
    const f = this.latestFrame;
    if (!f) return [0, 0, 0];
    const i = (bar * LEDS + led) * 3;
    return [f[i] || 0, f[i + 1] || 0, f[i + 2] || 0];
  }
}

export const stream = new StreamClient();
