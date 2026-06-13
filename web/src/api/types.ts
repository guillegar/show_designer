// types.ts — Tipos compartidos de las entidades del secuenciador (ROADMAP v2, F0.3).
// UN solo lugar: las vistas importan de aquí, nunca duplican estos tipos.
// Deben reflejar 1:1 lo que serializa el backend (timeline_model.py y módulos de fase).

/** Link de modulación de un parámetro a una señal del análisis (fase A1). */
export type ParamLink = {
  param: string;        // parámetro del efecto, ej. "brightness"
  source: string;       // señal normalizada, ej. "rms" | "flux" | "mel_bands.3"
  gain: number;
  offset: number;
  curve: "linear" | "exp" | "log" | "invert";
  min_v: number;
  max_v: number;
};

/** Punto de una curva de automatización (fase A2). */
export type AutomationPoint = {
  t_ms: number;
  value: number;        // 0..1 normalizado (el destino lo escala)
  shape: "linear" | "hold" | "smooth";
};

/** Lane de automatización (fase A2). */
export type AutomationLane = {
  uid: string;
  target: string;       // "clip:<uid>:<param>" | "track:<n>:<param>" | "master:<param>"
  points: AutomationPoint[];
  enabled: boolean;
};

/** Micro-evento: override puntual de parámetros dentro de un clip (fase A4). */
export type MicroEvent = {
  uid: string;
  t_ms_rel: number;     // tiempo relativo a clip.start_ms
  duration_ms: number;  // ventana de activación (default 100ms ≈ 3 frames @30FPS)
  params_override: Record<string, number | string | boolean>;
};

/** Pattern reutilizable (fase A3). Tiempos/tracks RELATIVOS al origen del pattern. */
export type Pattern = {
  uid: string;
  name: string;
  color: string;
  clips: unknown[];     // Clip[] serializados; la vista no los edita directamente
};

/** Instancia de un pattern colocada en el timeline (fase A3). */
export type PatternInstance = {
  uid: string;
  pattern_uid: string;
  start_ms: number;
  track_offset: number;
};

/** Cadena de post-procesado de una pista (fase B2). */
export type TrackChain = {
  brightness?: number;  // 0..1
  gamma?: number;       // 0.5..2.2
  hue_shift?: number;   // -180..180
  white_limit?: number; // 0..1
};

/** Estado del mixer (fase B2). */
export type MixerState = {
  tracks: Record<number, TrackChain>;
  master: TrackChain & { blackout_fade?: number };
};

/** Slot del performance grid (fase C1). */
export type LiveSlot = {
  uid: string;
  pattern_uid: string | null;
  key: string;
  quantize: "bar" | "beat" | "free";
  mode: "oneshot" | "loop" | "hold";
  idx: number;
  active: boolean;
  armed: boolean;
  degraded: boolean;        // true si quantize no pudo usar beats (degradó a free)
  armed_at_ms?: number;
};

/** Estado completo del motor live (fase C1). */
export type LiveState = {
  slots: LiveSlot[];
  active: string[];         // slot_uids activos
  armed: string[];          // slot_uids armados (pendientes de activar)
};

/** Macros en vivo (fase C2): estado de sesión, no se persiste en show.json. */
export type MacrosState = {
  brightness_mul: number;   // 0..2, default 1.0
  speed_mul:      number;   // 0..4, default 1.0
  hue_shift:      number;   // -180..180, default 0
  strobe_rate:    number;   // 0..30 Hz, default 0
};

// Re-exports MIDI (C3): importar desde aquí, no desde midi.ts directamente.
export type { MacroKey, MidiTarget, MidiMapping } from "./midi";
