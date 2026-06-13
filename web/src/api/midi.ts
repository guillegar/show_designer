// midi.ts — Web MIDI API bridge (ROADMAP v2, C3).
// Controla el grid de performance (C1) y macros (C2) desde hardware físico.
// Solo funciona en Chromium — en otros navegadores se degrada limpiamente.
// CERO cambios de backend: reutiliza live_trigger/live_release/set_macro.

export type MacroKey = "brightness_mul" | "speed_mul" | "hue_shift" | "strobe_rate";

export type MidiTarget =
  | { type: "slot"; slot_idx: number }
  | { type: "macro"; key: MacroKey };

export type MidiMapping = Record<string, MidiTarget>;  // "note:60" | "cc:74" → target

export type MidiCallbacks = {
  onSlotTrigger: (slot_idx: number, on: boolean) => void;
  onMacroChange: (key: MacroKey, value: number) => void;  // value ya escalado al rango
  onDeviceChange: (devices: string[]) => void;
  onLearnComplete?: () => void;  // llamado tras mapear en modo learn (no en el spec, necesario para React)
};

export type MidiHandle = {
  getDevices(): string[];
  startLearn(target: MidiTarget): void;  // próximo msg MIDI → mapea a target, sale del learn
  stopLearn(): void;
  isLearning(): boolean;
  getLearnTarget(): MidiTarget | null;
  getMapping(): MidiMapping;
  setMapping(m: MidiMapping): void;
  clearMapping(): void;
  destroy(): void;
};

// ── Funciones puras exportadas (testables sin instanciar Web MIDI API) ───────

const LS_KEY = "show_designer_midi_map";

/**
 * Convierte status+data1 de un mensaje MIDI a la clave del mapa.
 * El nibble bajo (canal MIDI 0-15) se ignora — funciona en cualquier canal.
 *
 * Note On  (0x9x): "note:<data1>"
 * Note Off (0x8x): "note:<data1>"  — el caller distingue on/off por velocity (data2)
 * CC       (0xBx): "cc:<data1>"
 * Otros         : null (ignorar)
 */
export function parseMidiKey(status: number, data1: number): string | null {
  const type = status & 0xF0;
  if (type === 0x90 || type === 0x80) return `note:${data1}`;
  if (type === 0xB0) return `cc:${data1}`;
  return null;
}

const MACRO_RANGES: Record<MacroKey, [number, number]> = {
  brightness_mul: [0.0,   2.0],
  speed_mul:      [0.0,   4.0],
  hue_shift:      [-180.0, 180.0],
  strobe_rate:    [0.0,  30.0],
};

/**
 * Escala un valor CC (0–127) al rango numérico del macro.
 * Lerp lineal: cc127=0 → min, cc127=127 → max.
 * cc127 se clampea a [0, 127] antes de escalar.
 */
export function scaleCCToMacro(cc127: number, key: MacroKey): number {
  const [min, max] = MACRO_RANGES[key];
  const t = Math.max(0, Math.min(127, cc127)) / 127;
  return min + t * (max - min);
}

// ── Persistencia ─────────────────────────────────────────────────────────────

function loadMapping(): MidiMapping {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) return JSON.parse(raw) as MidiMapping;
  } catch { /* ignore */ }
  return {};
}

function saveMapping(m: MidiMapping): void {
  try { localStorage.setItem(LS_KEY, JSON.stringify(m)); } catch { /* ignore */ }
}

// ── Handle degradado (sin Web MIDI disponible) ────────────────────────────────

function makeDegradedHandle(): MidiHandle {
  let mapping = loadMapping();
  return {
    getDevices:     () => [],
    startLearn:     () => {},
    stopLearn:      () => {},
    isLearning:     () => false,
    getLearnTarget: () => null,
    getMapping:     () => ({ ...mapping }),
    setMapping:     (m) => { mapping = { ...m }; saveMapping(mapping); },
    clearMapping:   () => {
      mapping = {};
      try { localStorage.removeItem(LS_KEY); } catch { /* */ }
    },
    destroy: () => {},
  };
}

// ── Inicialización principal ─────────────────────────────────────────────────

/**
 * Solicita acceso MIDI y construye el handle activo.
 *
 * Si Web MIDI API no existe en el navegador, o si el usuario deniega el permiso,
 * devuelve un handle degradado (getDevices()=[], todo no-op) sin lanzar excepción.
 * La UI detecta esto chequeando midiDevices.length o el flag midiUnsupported.
 *
 * Invariante I4: esta función es async/await y se llama desde useEffect —
 * el componente monta antes de que MIDI esté listo. Durante ese lapso
 * midiHandle.current es null y la UI debe tratar ese caso (nada lanza).
 */
export async function initMidi(callbacks: MidiCallbacks): Promise<MidiHandle> {
  if (!("requestMIDIAccess" in navigator)) {
    return makeDegradedHandle();
  }

  let access: MIDIAccess;
  try {
    // `as any` porque el tipo de navigator no incluye requestMIDIAccess en todas las versiones de @types/web
    access = await (navigator as any).requestMIDIAccess({ sysex: false });
  } catch {
    return makeDegradedHandle();
  }

  let mapping: MidiMapping = loadMapping();
  let learnTarget: MidiTarget | null = null;
  const connected = new Set<string>();

  const handleMessage = (event: MIDIMessageEvent) => {
    const data = event.data;
    if (!data || data.length < 2) return;
    const status = data[0];
    const data1  = data[1];
    const data2  = data.length > 2 ? data[2] : 0;

    const key = parseMidiKey(status, data1);
    if (!key) return;

    // Modo learn: mapear el primer mensaje al target activo y salir
    if (learnTarget !== null) {
      mapping[key] = learnTarget;
      saveMapping(mapping);
      learnTarget = null;
      callbacks.onLearnComplete?.();
      return;
    }

    const target = mapping[key];
    if (!target) return;

    const statusType = status & 0xF0;

    if (target.type === "slot") {
      // Note On velocity > 0 → trigger; Note Off o velocity 0 → release
      if (statusType === 0x90 && data2 > 0) {
        callbacks.onSlotTrigger(target.slot_idx, true);
      } else if (statusType === 0x80 || (statusType === 0x90 && data2 === 0)) {
        callbacks.onSlotTrigger(target.slot_idx, false);
      }
    } else if (target.type === "macro") {
      if (statusType === 0xB0) {
        callbacks.onMacroChange(target.key, scaleCCToMacro(data2, target.key));
      }
    }
  };

  const connectPort = (port: MIDIInput) => {
    if (connected.has(port.id)) return;
    port.onmidimessage = handleMessage;
    connected.add(port.id);
  };

  // Conectar todos los puertos actuales
  access.inputs.forEach(connectPort);

  // Reconectar puertos nuevos (plug/unplug) y notificar cambios de dispositivos
  access.onstatechange = () => {
    access.inputs.forEach(connectPort);
    callbacks.onDeviceChange(
      Array.from(access.inputs.values()).map((p) => p.name ?? p.id)
    );
  };

  return {
    getDevices: () => Array.from(access.inputs.values()).map((p) => p.name ?? p.id),
    startLearn: (target) => { learnTarget = target; },
    stopLearn:  () => { learnTarget = null; },
    isLearning: () => learnTarget !== null,
    getLearnTarget: () => learnTarget,
    getMapping:  () => ({ ...mapping }),
    setMapping:  (m) => { mapping = { ...m }; saveMapping(mapping); },
    clearMapping: () => {
      mapping = {};
      try { localStorage.removeItem(LS_KEY); } catch { /* */ }
    },
    destroy: () => {
      access.inputs.forEach((port) => { port.onmidimessage = null; });
      connected.clear();
    },
  };
}
