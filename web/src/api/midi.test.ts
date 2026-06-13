// midi.test.ts — Tests unitarios de funciones puras de MIDI (ROADMAP v2, C3).
// Solo testea lógica pura: parseMidiKey, scaleCCToMacro y roundtrip de mapping.
// No instancia la Web MIDI API real (solo funciona en Chromium con hardware físico).
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { parseMidiKey, scaleCCToMacro } from "./midi";

// ── parseMidiKey ─────────────────────────────────────────────────────────────

describe("parseMidiKey", () => {
  it("Note On canal 0 → note:<n>", () => {
    expect(parseMidiKey(0x90, 60)).toBe("note:60");
  });
  it("Note Off canal 0 → note:<n>", () => {
    expect(parseMidiKey(0x80, 60)).toBe("note:60");
  });
  it("CC canal 0 → cc:<n>", () => {
    expect(parseMidiKey(0xB0, 74)).toBe("cc:74");
  });
  it("Program Change (0xC0) → null (ignorar)", () => {
    expect(parseMidiKey(0xC0, 5)).toBeNull();
  });
  it("Note On en canal 1 (0x91) → note:<n> (ignora nibble de canal)", () => {
    expect(parseMidiKey(0x91, 36)).toBe("note:36");
  });
  it("CC en canal 2 (0xB2) → cc:<n>", () => {
    expect(parseMidiKey(0xB2, 7)).toBe("cc:7");
  });
});

// ── scaleCCToMacro ───────────────────────────────────────────────────────────

describe("scaleCCToMacro", () => {
  it("brightness_mul CC=127 → 2.0", () => {
    expect(scaleCCToMacro(127, "brightness_mul")).toBeCloseTo(2.0);
  });
  it("brightness_mul CC=0 → 0.0", () => {
    expect(scaleCCToMacro(0, "brightness_mul")).toBeCloseTo(0.0);
  });
  it("brightness_mul CC=63 ≈ 63/127*2", () => {
    expect(scaleCCToMacro(63, "brightness_mul")).toBeCloseTo(63 / 127 * 2, 3);
  });
  it("hue_shift CC=0 → -180.0", () => {
    expect(scaleCCToMacro(0, "hue_shift")).toBeCloseTo(-180.0);
  });
  it("hue_shift CC=127 → 180.0", () => {
    expect(scaleCCToMacro(127, "hue_shift")).toBeCloseTo(180.0);
  });
  it("speed_mul CC=127 → 4.0", () => {
    expect(scaleCCToMacro(127, "speed_mul")).toBeCloseTo(4.0);
  });
  it("strobe_rate CC=127 → 30.0", () => {
    expect(scaleCCToMacro(127, "strobe_rate")).toBeCloseTo(30.0);
  });
});

// ── Mapping roundtrip vía handle degradado (localStorage mock) ───────────────

describe("MidiMapping roundtrip", () => {
  const store: Record<string, string> = {};

  beforeEach(() => {
    vi.stubGlobal("localStorage", {
      getItem:    (k: string) => store[k] ?? null,
      setItem:    (k: string, v: string) => { store[k] = v; },
      removeItem: (k: string) => { delete store[k]; },
    });
    // requestMIDIAccess presente pero rechaza → handle degradado (sin hardware real)
    vi.stubGlobal("navigator", {
      requestMIDIAccess: () => Promise.reject(new Error("no midi in tests")),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    for (const k of Object.keys(store)) delete store[k];
  });

  it("setMapping → getMapping devuelve el mismo objeto", async () => {
    const { initMidi } = await import("./midi");
    const handle = await initMidi({
      onSlotTrigger:  () => {},
      onMacroChange:  () => {},
      onDeviceChange: () => {},
    });

    const mapping = {
      "note:60": { type: "slot"  as const, slot_idx: 0 },
      "cc:74":   { type: "macro" as const, key: "brightness_mul" as const },
    };
    handle.setMapping(mapping);
    expect(handle.getMapping()).toEqual(mapping);
  });

  it("clearMapping → getMapping devuelve {}", async () => {
    const { initMidi } = await import("./midi");
    const handle = await initMidi({
      onSlotTrigger:  () => {},
      onMacroChange:  () => {},
      onDeviceChange: () => {},
    });
    handle.setMapping({ "note:1": { type: "slot" as const, slot_idx: 0 } });
    handle.clearMapping();
    expect(handle.getMapping()).toEqual({});
  });
});
